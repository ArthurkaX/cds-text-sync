"""Parallel, offline FSM search for an exported CODESYS workspace.

This module deliberately has no CODESYS dependency.  The IDE shell supplies a
workspace path and renders the returned machines, while CPython reads and
parses the ``project-view`` files in worker processes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path

from cts_shared.st.fsm import find_machines
from cds_text_sync.engine.variable_map import split_decl_impl


def _source_root(workspace: Path) -> Path:
    """Prefer the exported view, but accept a project-view path directly."""
    if workspace.name.casefold() == "project-view" and workspace.is_dir():
        return workspace
    candidate = workspace / "project-view"
    return candidate if candidate.is_dir() else workspace


def _machine_payload(machine):
    return {
        "selector": machine.selector,
        "states": [
            {"label": state.label, "aliases": state.aliases, "order": state.order}
            for state in machine.states
        ],
        "transitions": [
            {
                "source": transition.source,
                "target": transition.target,
                "guard": transition.guard,
                "offset": transition.offset,
                "lhs": transition.lhs,
                "deferred": transition.deferred,
            }
            for transition in machine.transitions
        ],
        "deferred": machine.deferred,
        "numeric": machine.numeric,
        "warnings": machine.warnings,
    }


def _scan_file(path_text: str) -> dict:
    """Worker entry point: it must stay module-level for Windows spawning."""
    path = Path(path_text)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        _declaration, implementation = split_decl_impl(text)
        machines = [
            _machine_payload(machine)
            for machine in find_machines(implementation if implementation is not None else text)
            if machine.is_fsm
        ]
        return {"path": str(path), "machines": machines}
    except Exception as error:
        return {"path": str(path), "machines": [], "error": str(error)}


def _matching_files(root: Path, query: str) -> list[Path]:
    needle = query.strip().casefold()
    paths = sorted(path for path in root.rglob("*.st") if path.is_file())
    if not needle:
        return paths
    return [
        path for path in paths
        if needle in path.relative_to(root).as_posix().casefold()
    ]


def _scan_until_first_machine(paths: list[Path], workers: int) -> list[dict]:
    """Parse in candidate order and stop at the first block holding a machine.

    ``Find next FSM`` only ever uses the first hit, so a broad path search must
    not pay to parse every match: a one-letter query matches most of a project
    and parsing all of it is what made the picker look hung.  Futures are
    consumed in submission order so the winner is the same file a serial scan
    would pick, and only a bounded window is ever in flight so an early hit
    does not first queue the whole candidate list.
    """
    scanned: list[dict] = []
    if workers == 1:
        for path in paths:
            result = _scan_file(str(path))
            scanned.append(result)
            if result["machines"]:
                break
        return scanned
    remaining = iter(paths)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = deque(
            pool.submit(_scan_file, str(path))
            for path in islice(remaining, workers * 4)
        )
        while pending:
            result = pending.popleft().result()
            scanned.append(result)
            if result["machines"]:
                for future in pending:
                    future.cancel()
                break
            for path in islice(remaining, 1):
                pending.append(pool.submit(_scan_file, str(path)))
    return scanned


def search_workspace(workspace: str | os.PathLike[str], query: str,
                     workers: int | None = None, parse: bool = True,
                     selected_path: str | None = None,
                     stop_at_first: bool = False) -> dict:
    """Find FSMs in files selected by a path search.

    ``query`` filters relative workspace paths before parsing begins.  Results
    are JSON-safe so a CODESYS IronPython caller can consume them directly.
    With ``stop_at_first`` the scan ends at the first block that holds a
    machine, and ``results`` then covers only the files actually parsed.
    """
    root = _source_root(Path(workspace).expanduser().resolve())
    if not root.is_dir():
        raise ValueError("Workspace/project-view does not exist: " + str(root))
    if selected_path is not None:
        candidate = (root / selected_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError("Selected path is outside project-view: " + str(selected_path))
        if candidate.suffix.casefold() != ".st" or not candidate.is_file():
            raise ValueError("Selected project-view block does not exist: " + str(selected_path))
        paths = [candidate]
    else:
        paths = _matching_files(root, query)
    candidates = [path.relative_to(root).as_posix() for path in paths]
    if not parse:
        return {
            "workspace": str(root),
            "query": query,
            "scanned": 0,
            "workers": 0,
            "candidates": candidates,
            "results": [],
            "errors": [],
            "stopped_early": False,
        }
    if workers is None:
        workers = min(6, os.cpu_count() or 1)
    workers = max(1, min(workers, len(paths) or 1))
    if stop_at_first:
        scanned = _scan_until_first_machine(paths, workers)
    elif workers == 1:
        scanned = [_scan_file(str(path)) for path in paths]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            scanned = list(pool.map(_scan_file, (str(path) for path in paths)))
    results = []
    errors = []
    for result in scanned:
        relative = Path(result["path"]).relative_to(root).as_posix()
        relative_result = result.get("error")
        if relative_result:
            errors.append({"path": relative, "error": result["error"]})
        row = {"path": relative, "machines": result.get("machines", [])}
        if relative_result:
            row["error"] = relative_result
        results.append(row)
    return {
        "workspace": str(root),
        "query": query,
        "scanned": len(scanned),
        "workers": workers,
        "candidates": candidates,
        "results": results,
        "errors": errors,
        "stopped_early": len(scanned) < len(paths),
    }


def _configure_stdout_utf8() -> None:
    """Emit UTF-8 whatever the console codepage is.

    The CODESYS host redirects this process's stdout to a file and decodes it
    as UTF-8. On Windows the default is the legacy ANSI codepage, which raises
    UnicodeEncodeError the moment a project path is Cyrillic - and these paths
    frequently are.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdout_utf8()
    parser = argparse.ArgumentParser(description="Find Structured Text FSMs in parallel.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--list-only", action="store_true",
                        help="return matching ST paths without parsing them")
    parser.add_argument("--stop-at-first", action="store_true",
                        help="stop parsing at the first block that holds a machine")
    parser.add_argument("--selected-path", default=None)
    args = parser.parse_args(argv)
    try:
        result = search_workspace(
            args.workspace, args.query, args.workers, parse=not args.list_only,
            selected_path=args.selected_path, stop_at_first=args.stop_at_first,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
