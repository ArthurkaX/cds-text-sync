# -*- coding: utf-8 -*-
"""``cts snapshooter`` -- PLC value presets over the daemon.

Thin wrapper over the daemon's ``snapshooter`` method: this module turns the
parsed arguments into the action/params payload the IronPython handler reads
and prints the daemon's data.  The preset format lives in the daemon-side
backend; nothing about it is reimplemented here.
"""

from __future__ import annotations

import os
import sys

from cds_cli._cli_io import (
    _daemon_path,
    _format_output,
    _print_daemon_unreachable,
    _print_error,
    _print_info,
    _print_rp_error,
    send_command_reverse,
)
from cts_shared import wire

DEFAULT_TIMEOUT = 300


def dispatch_snapshooter(args, output_fmt="json"):
    """Handle ``cts snapshooter``. Return True if this was the command, else False."""
    if getattr(args, "command", None) != "snapshooter":
        return False

    params = _build_params(args)
    timeout = float(getattr(args, "timeout", None) or DEFAULT_TIMEOUT)
    try:
        response = send_command_reverse("snapshooter", params, timeout=timeout)
    except RuntimeError as exc:
        _print_error("Reverse pipe error: {0}".format(exc))
        _print_daemon_unreachable()
        sys.exit(1)

    if not wire.response_ok(response):
        _print_rp_error(response, "snapshooter")
        sys.exit(1)

    data = response.get("data", {}) or {}
    print(_format_output(data, fmt=output_fmt, title="snapshooter"))
    _note_failed_ui_check_steps(data)
    return True


def _note_failed_ui_check_steps(data):
    """Name the ui-check steps that failed, on stderr.

    The exit code stays 0: the command answered and delivered the report, and
    a failed step is the *finding* -- a headless run exists to say which
    dialog handlers break -- not a failure of the command.  ``all_steps_ok``
    and ``failed_steps`` in the data are the machine-readable signal; this
    line is for whoever only reads the terminal (``cts verify`` reports
    incomplete stages the same way).
    """
    report = data.get("report") if isinstance(data, dict) else None
    if not isinstance(report, dict) or report.get("all_steps_ok", True):
        return
    failed = ", ".join(report.get("failed_steps") or []) or "?"
    _print_info(
        "ui-check: {0} of {1} steps failed: {2}".format(
            len(report.get("failed_steps") or []), len(report.get("steps") or []), failed
        )
    )


def _build_params(args):
    """Map the parsed sub-action onto the daemon's ``action`` payload.

    ``--out``/``--input`` are absolutised (see ``_daemon_path``); ``--paths-file``
    is read here, so it needs nothing.
    """
    action = getattr(args, "snap_action", "")
    if action == "ui-check":
        params = {"action": "ui_check", "app": getattr(args, "app", "") or "Application"}
        script = _split_script(getattr(args, "script", ""))
        if script:
            params["script"] = script
        return params

    params = {"action": action}
    if action == "tree":
        params.update(_tree_params(args))
    elif action == "take":
        paths = _collect_paths(args)
        if paths:
            params["paths"] = paths
        if getattr(args, "label", ""):
            params["label"] = args.label
        if getattr(args, "out", ""):
            params["out"] = _daemon_path(args.out)
    elif action in ("diff", "restore"):
        params["input"] = _daemon_path(getattr(args, "input", "") or "")
        if action == "restore":
            params["apply"] = bool(getattr(args, "apply", False))
    return params


def _tree_params(args):
    """The ``tree`` payload; ``refresh`` is sent only when asked."""
    params = {"path": getattr(args, "path", "") or ""}
    if getattr(args, "refresh", False):
        params["refresh"] = True
    return params


def _collect_paths(args):
    """Explicit ``--path`` values plus every non-comment line of ``--paths-file``.

    The file is opened here, so a relative ``--paths-file`` already means "from
    the shell's cwd" and needs no absolutising -- unlike the paths that go on to
    the daemon.
    """
    paths = list(getattr(args, "path", None) or [])
    file_path = getattr(args, "paths_file", "") or ""
    if file_path:
        if not os.path.exists(file_path):
            _print_error("File not found: {0}".format(file_path))
            sys.exit(1)
        with open(file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#"):
                    paths.append(line)
    return paths


def _split_script(value):
    return [name.strip() for name in str(value or "").split(",") if name.strip()]
