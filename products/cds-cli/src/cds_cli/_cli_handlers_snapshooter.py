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
    _format_output,
    _print_error,
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
        sys.exit(1)

    if not wire.response_ok(response):
        _print_rp_error(response, "snapshooter")
        sys.exit(1)

    data = response.get("data", {}) or {}
    print(_format_output(data, fmt=output_fmt, title="snapshooter"))
    return True


def _build_params(args):
    """Map the parsed sub-action onto the daemon's ``action`` payload."""
    action = getattr(args, "snap_action", "")
    if action == "ui-check":
        params = {"action": "ui_check", "app": getattr(args, "app", "") or "Application"}
        script = _split_script(getattr(args, "script", ""))
        if script:
            params["script"] = script
        return params

    params = {"action": action}
    if action == "tree":
        params["path"] = getattr(args, "path", "") or ""
    elif action == "take":
        paths = _collect_paths(args)
        if paths:
            params["paths"] = paths
        if getattr(args, "label", ""):
            params["label"] = args.label
        if getattr(args, "out", ""):
            params["out"] = args.out
    elif action in ("diff", "restore"):
        params["input"] = getattr(args, "input", "") or ""
        if action == "restore":
            params["apply"] = bool(getattr(args, "apply", False))
    return params


def _collect_paths(args):
    """Explicit ``--path`` values plus every non-comment line of ``--paths-file``."""
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
