"""Parallel, offline FSM search for an exported CODESYS workspace.

This module deliberately has no CODESYS dependency.  The IDE shell supplies a
workspace path and renders the returned machines, while CPython reads and
parses the ``project-view`` files in worker processes.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
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
    except OSError as error:
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


def search_workspace(workspace: str | os.PathLike[str], query: str, workers: int | None = None) -> dict:
    """Find FSMs in files selected by a path search.

    ``query`` filters relative workspace paths before parsing begins.  Results
    are JSON-safe so a CODESYS IronPython caller can consume them directly.
    """
    root = _source_root(Path(workspace).expanduser().resolve())
    if not root.is_dir():
        raise ValueError("Workspace/project-view does not exist: " + str(root))
    paths = _matching_files(root, query)
    if workers is None:
        workers = min(6, os.cpu_count() or 1)
    workers = max(1, min(workers, len(paths) or 1))
    if workers == 1:
        scanned = [_scan_file(str(path)) for path in paths]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            scanned = list(pool.map(_scan_file, (str(path) for path in paths)))
    results = []
    errors = []
    for result in scanned:
        relative = Path(result["path"]).relative_to(root).as_posix()
        if result.get("error"):
            errors.append({"path": relative, "error": result["error"]})
        if result["machines"]:
            results.append({"path": relative, "machines": result["machines"]})
    return {
        "workspace": str(root),
        "query": query,
        "scanned": len(paths),
        "workers": workers,
        "results": results,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find Structured Text FSMs in parallel.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        result = search_workspace(args.workspace, args.query, args.workers)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
