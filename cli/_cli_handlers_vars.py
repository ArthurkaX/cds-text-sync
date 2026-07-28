# -*- coding: utf-8 -*-
"""
_cli_handlers_vars.py - Variable map/snapshot/restore handlers and helpers.

Covers cmd_read_vars, cmd_variable_map, cmd_variable_snapshot,
cmd_variable_restore, and their helpers (_resolve_project_view,
_build_map_rows, _write_csv, _batch).
"""

from __future__ import annotations

import csv as _csv
import os
import sys

from cli._cli_io import (
    _batch,
    _format_output,
    _print_error,
    send_command_reverse,
)


# -- Shared helpers -----------------------------------------------------------


def _resolve_project_view(sync_folder, timeout=10, quiet=False):
    """Return (project_view_dir, sync_folder_base).

    Uses --sync-folder when given, else asks the daemon for sync_folder.

    ``timeout`` bounds the wait for the IDE to connect to the reverse pipe.
    ``quiet`` suppresses the failure messages: callers for which a project
    view is optional still get the ``SystemExit``, but a user who never
    asked for the IDE is not told that it is missing.
    """
    base = sync_folder
    if not base:
        try:
            resp = send_command_reverse("status", {}, timeout=timeout)
            if resp.get("ok"):
                base = resp.get("data", {}).get("sync_folder")
        except Exception as e:
            if not quiet:
                _print_error("Could not get sync folder from daemon: {0}".format(e))
            sys.exit(1)
    if not base:
        if not quiet:
            _print_error("No sync folder. Pass --sync-folder or start the daemon.")
        sys.exit(1)
    base = str(base)
    if os.path.basename(os.path.normpath(base)) == "project-view" and os.path.isdir(
        base
    ):
        return base, os.path.dirname(os.path.normpath(base))
    pv = os.path.join(base, "project-view")
    if not os.path.isdir(pv):
        if not quiet:
            _print_error("project-view not found under: {0}".format(base))
        sys.exit(1)
    return pv, base


def _build_map_rows(path_filter, sync_folder, include_programs):
    import variable_map as vm

    pv, base = _resolve_project_view(sync_folder)
    rows, stats = vm.build_map_from_dir(pv, include_programs=include_programs)
    if path_filter:
        rows = vm.filter_rows_by_path(rows, path_filter)
        if not rows:
            _print_error("Path filter matched nothing: {0}".format(path_filter))
            sys.exit(1)
    return rows, stats, base, vm


def _write_csv(path, columns, rows):
    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# -- Command handlers ---------------------------------------------------------


def cmd_read_vars(names, file_path="", timeout=30, output_fmt="json"):
    """Batch-read multiple PLC variables/expressions.

    Names come from positional args and/or a --file (one expression per line,
    blank lines and #-comments ignored). Sends a proper JSON list to the
    daemon's read_variables, so this avoids the `rp read_variables` string
    pitfall where --names is passed as a raw string.
    """
    exprs = list(names or [])
    if file_path:
        if not os.path.exists(file_path):
            _print_error("File not found: {0}".format(file_path))
            sys.exit(1)
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exprs.append(line)
    if not exprs:
        _print_error("No variable names given. Pass names as arguments or via --file.")
        sys.exit(1)

    try:
        results = _batch("read_variables", "names", exprs, timeout)
    except RuntimeError as e:
        _print_error("read-vars failed: {0}".format(e))
        sys.exit(1)

    # Preserve the requested order in the output.
    ordered = [
        results.get(
            name, {"name": name, "read_ok": False, "read_error": "no result returned"}
        )
        for name in exprs
    ]
    print(
        _format_output(
            {"results": ordered, "count": len(ordered)},
            fmt=output_fmt,
            title="read_variables",
        )
    )


def cmd_variable_map(
    path_filter="", out="", sync_folder="", include_programs=True, output_fmt="json"
):
    """Build an offline variable map (CSV) from project-view declarations."""
    rows, stats, base, vm = _build_map_rows(path_filter, sync_folder, include_programs)
    if not out:
        out = os.path.join(base, "variable-map.csv")
    _write_csv(out, vm.MAP_COLUMNS, rows)
    summary = {
        "output": out,
        "rows": len(rows),
        "readable_leaves": sum(1 for r in rows if r.get("leaf")),
        "owners": stats.get("owners"),
    }
    print(_format_output(summary, fmt=output_fmt, title="variable_map"))


def cmd_variable_snapshot(
    path_filter="",
    out="",
    sync_folder="",
    include_programs=True,
    timeout=120,
    output_fmt="json",
):
    """Snapshot current online values for mapped leaves (CSV)."""
    import snapshot_engine as se

    rows, stats, base, vm = _build_map_rows(path_filter, sync_folder, include_programs)
    read_fn = lambda exprs: _batch("read_variables", "names", exprs, timeout)
    try:
        rows, rstats = se.run_snapshot(rows, read_fn)
    except RuntimeError as e:
        _print_error("Snapshot read failed: {0}".format(e))
        sys.exit(1)

    if not out:
        out = os.path.join(base, "variable-snapshot.csv")
    cols = vm.MAP_COLUMNS + se.SNAPSHOT_COLUMNS
    _write_csv(out, cols, rows)
    summary = {
        "output": out,
        "rows": len(rows),
        "read_ok": rstats["read_ok"],
        "read_failed": rstats["read_failed"],
        "failures": rstats.get("failures", []),
    }
    print(_format_output(summary, fmt=output_fmt, title="variable_snapshot"))


def cmd_variable_restore(
    input_path="",
    report="",
    path_filter="",
    do_apply=False,
    force=False,
    sync_folder="",
    timeout=120,
    output_fmt="json",
):
    """Restore PLC values from a snapshot CSV. Dry-run unless --apply."""
    import snapshot_engine as se

    if not input_path:
        _print_error("Specify --input <snapshot.csv>")
        sys.exit(1)
    if not os.path.exists(input_path):
        _print_error("Snapshot not found: {0}".format(input_path))
        sys.exit(1)

    import variable_map as vm

    with open(input_path, "r", newline="", encoding="utf-8") as f:
        snap_rows = list(_csv.DictReader(f))
    if path_filter:
        snap_rows = vm.filter_rows_by_path(snap_rows, path_filter)

    # Determine the project-view base for enum registry
    _pd, _pb = _resolve_project_view(sync_folder)
    enum_base = sync_folder
    if not enum_base:
        enum_base = _pb

    # Build an enum registry from the project-view so we can translate
    # 'TYPE.member' (snapshot) into a numeric value acceptable to
    # set_prepared_value (CODESYS double-prefixes qualified enumerators).
    enum_registry = {}
    if enum_base and os.path.isdir(enum_base):
        try:
            enum_registry = vm.build_enum_registry(enum_base)
        except Exception:
            pass

    eligible, skipped = se.plan_restore(
        snap_rows, force=force, enum_registry=enum_registry
    )

    base = sync_folder
    if not base:
        _, base = _resolve_project_view(sync_folder)
    if not report:
        report = os.path.join(base, "variable-restore-report.csv")

    if not do_apply:
        se.mark_dry_run(eligible)
        report_rows = eligible + skipped
        _write_csv(report, se.RESTORE_REPORT_COLUMNS, report_rows)
        summary = {
            "mode": "dry-run",
            "report": report,
            "would_write": len(eligible),
            "skipped": len(skipped),
            "hint": "re-run with --apply to write",
        }
        print(_format_output(summary, fmt=output_fmt, title="variable_restore"))
        return

    write_fn = lambda items: _batch("write_variables", "items", items, timeout)
    try:
        eligible, wstats = se.apply_restore(eligible, write_fn)
    except RuntimeError as e:
        _print_error("Restore write failed: {0}".format(e))
        sys.exit(1)

    report_rows = eligible + skipped
    _write_csv(report, se.RESTORE_REPORT_COLUMNS, report_rows)
    summary = {
        "mode": "apply",
        "report": report,
        "written": wstats["written"],
        "failed": wstats["failed"],
        "skipped": len(skipped),
    }
    print(_format_output(summary, fmt=output_fmt, title="variable_restore"))
