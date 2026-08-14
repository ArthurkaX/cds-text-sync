"""``cts fsm`` command handlers: offline scan, single-file render, desktop UI.

``dispatch_fsm(args)`` routes the parsed ``fsm`` subcommand (registered by
``cds_cli.parsers.fsm``) to a scan, show, or ui handler.  Everything here is
CPython only; the CODESYS host never imports this module.

EXIT CODES - load-bearing, do not "fix":
  0 - the command produced its output, INCLUDING "this file has no FSM" and
      "this workspace has no FSM".  Absence is reported in the payload (an
      empty machine list for json, a stderr diagnostic for mermaid/svg), never
      through the exit status.  For ``ui``: the window opened and closed
      normally.
  2 - invalid workspace, invalid/traversing path, bad machine index, a
      read/parse failure, or (for ``ui``) a startup failure or a missing
      pywebview dependency.
  NEVER use 1 for "no FSM found".  In this repository 1 already means "the
  analysis found something" (cds_static_analyzer.runner.exit_code: 0 clean,
  1 violations, 2 config, 3 incomplete), and reusing it for "nothing found"
  would invert that contract for every script already consuming ``cts analyze``.
"""

from __future__ import annotations

import json
import sys
import time

from .model import STATE_ERROR, STATE_FSM
from .render import to_mermaid_text, to_svg
from .scanner import Scanner
from .workspace import resolve_in_root


def _out():
    return sys.stdout


def _err():
    return sys.stderr


def _print_error(message):
    print(f"[ERROR] {message}", file=_err())


def _write_json(payload):
    _out().write(json.dumps(payload, ensure_ascii=False) + "\n")


def dispatch_fsm(args) -> int:
    """Route the parsed ``fsm`` subcommand.

    Exit codes are load-bearing; see the module docstring.  The short rule:
    0 means "output produced, including no FSM found" and 2 means "the command
    could not run".  1 is never used here.
    """
    action = getattr(args, "fsm_action", "") or ""
    if action == "scan":
        return _cmd_scan(args)
    if action == "show":
        return _cmd_show(args)
    if action == "ui":
        return _cmd_ui(args)
    _print_error(
        f"unknown fsm action: {action!r}; available actions: scan, show, ui"
    )
    return 2


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def _filter_paths(files, query):
    """Filter bootstrap file-index entries by a case-insensitive substring.

    Matches ``fsm_search._matching_files``: the query is stripped, folded, and
    tested against the forward-slash relative path; an empty query keeps every
    file.
    """
    needle = (query or "").strip().casefold()
    if not needle:
        return [entry["path"] for entry in files]
    return [
        entry["path"] for entry in files if needle in entry["path"].casefold()
    ]


def _wait_scan_done(scanner, job_id, timeout=600.0):
    """Poll until the scan leaves the running/queued states; return the poll."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = scanner.poll_scan(job_id)
        if last["state"] in ("completed", "cancelled", "failed"):
            return last
        time.sleep(0.01)
    state = last["state"] if last else "unknown"
    raise RuntimeError(f"scan did not finish within {timeout}s (state: {state})")


def _cmd_scan(args) -> int:
    workspace = getattr(args, "workspace", "")
    query = getattr(args, "query", "") or ""
    workers = getattr(args, "workers", None)
    as_json = bool(getattr(args, "json", False))
    try:
        scanner = Scanner(workspace, max_workers=workers)
    except Exception as error:
        _print_error(str(error))
        return 2
    try:
        bootstrap = scanner.bootstrap()
        paths = _filter_paths(bootstrap["files"], query)
        started = scanner.start_scan(paths)
        scan = _wait_scan_done(scanner, started["job_id"])
    except ValueError as error:
        _print_error(str(error))
        return 2
    finally:
        scanner.close()

    if scan["state"] != "completed":
        _print_error(
            f"scan did not complete (state: {scan['state']}); "
            f"{scan['completed']}/{scan['total']} files analysed"
        )
        return 2

    events = scan["events"]
    counts = {
        "total": scan["total"],
        "completed": scan["completed"],
        "hits": scan["hits"],
        "errors": scan["errors"],
    }
    if as_json:
        _write_json(
            {
                "workspace": bootstrap["workspace"],
                "source_root": bootstrap["source_root"],
                "snapshot": bootstrap["snapshot"],
                "counts": counts,
                "results": events,
            }
        )
        return 0

    for event in events:
        if event["state"] == STATE_ERROR:
            _err().write(f"{event['path']}: {event['error']}\n")
        elif event["state"] == STATE_FSM:
            selectors = ", ".join(m["selector"] for m in event["machines"])
            _out().write(
                f"{event['path']}: {len(event['machines'])} machine(s) "
                f"[{selectors}]\n"
            )
    _out().write(
        f"Scanned {counts['completed']} file(s): {counts['hits']} with FSM, "
        f"{counts['errors']} error(s)\n"
    )
    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def _cmd_show(args) -> int:
    workspace = getattr(args, "workspace", "")
    relative = getattr(args, "file", "") or ""
    try:
        machine_index = int(getattr(args, "machine", 0) or 0)
    except (TypeError, ValueError):
        _print_error("--machine must be an integer index")
        return 2
    fmt = getattr(args, "format", "json") or "json"

    try:
        scanner = Scanner(workspace)
    except Exception as error:
        _print_error(str(error))
        return 2
    try:
        scanner.bootstrap()
        # resolve_in_root is the traversal guard: a path that escapes the
        # source root resolves to None and analyze_file reports it as an
        # error row, which becomes exit 2 below.
        if resolve_in_root(scanner.source_root, relative) is None:
            _print_error(f"path is outside the source root: {relative}")
            return 2
        result = scanner.analyze_file(relative)
    except ValueError as error:
        _print_error(str(error))
        return 2
    finally:
        scanner.close()

    if result["state"] == STATE_ERROR:
        _print_error(result["error"] or f"could not analyse {relative}")
        return 2

    machines = result["machines"]
    if not machines:
        # No FSM is a VALID result: exit 0, report the absence in the payload.
        if fmt == "json":
            _write_json(result)
        else:
            _print_error(f"{relative}: no FSM found")
        return 0

    if machine_index < 0 or machine_index >= len(machines):
        _print_error(
            f"machine index {machine_index} is out of range "
            f"({len(machines)} machine(s) in {relative})"
        )
        return 2
    machine = machines[machine_index]

    if fmt == "json":
        _write_json(result)
    elif fmt == "mermaid":
        _out().write(to_mermaid_text(machine) + "\n")
    elif fmt == "svg":
        _out().write(to_svg(machine) + "\n")
    else:
        _print_error(f"unknown format: {fmt}")
        return 2
    return 0


# ---------------------------------------------------------------------------
# ui
# ---------------------------------------------------------------------------


def _cmd_ui(args) -> int:
    """Open the local FSM desktop window.

    ``--workspace`` is optional: an omitted path opens the window with the
    folder picker.  Exit codes are load-bearing: 0 = window opened and closed
    normally; 2 = invalid workspace, missing pywebview, or startup failure.
    """
    workspace = getattr(args, "workspace", "") or ""
    try:
        # Imported here so the CLI stays usable (and testable) without the
        # optional pywebview dependency.
        from cds_text_sync.fsm import ui as fsm_ui

        return int(fsm_ui.launch(workspace))
    except Exception as error:
        _print_error(str(error))
        return 2
