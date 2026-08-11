# -*- coding: utf-8 -*-
"""
_cli_handlers_daemon.py - Top-level daemon-command dispatch.

Covers the thin ``cts <cmd>`` family that maps to a reverse-pipe daemon
method: ping, status, export, import, compare, build, disconnect, download,
start, stop, app-state, plc-crc, project-info, permissions, plus connect,
read, write, test, project-tree, read-object, update-pou, delete-pou,
read-log. Extracted from the main() dispatcher.

Unlike the pure project/pou/visu routers, a few of these carry logic:
  * import   -> --dry-run previews via sync_compare_text; online imports are rejected
  * download -> optional --start passthrough
  * plc-crc  -> optional build first
  * write    -> write_variable then read_variable read-back in one response
"""

from __future__ import annotations

import sys

from cds_cli._cli_io import (
    _format_output,
    _print_error,
    _print_info,
    _print_rp_error,
    cmd_daemon,
    send_command_reverse,
)

# command name -> daemon method for the thin passthrough family
_DAEMON_METHODS = {
    "ping": "ping",
    "status": "status",
    "export": "sync_export_text",
    "import": "sync_import_text",
    "compare": "sync_compare_text",
    "build": "build",
    "disconnect": "disconnect_from_device",
    "download": "download",
    "start": "start_plc",
    "stop": "stop_plc",
    "app-state": "application_state",
    "plc-crc": "plc_crc",
    "project-info": "project_info",
    "permissions": "permissions",
}


_PROFILE_LOOKUP_TIMEOUT = 10


def _daemon_timeout(method, requested_timeout=None, fallback=30):
    """Resolve a daemon-owned automatic timeout; explicit values win.

    ``status`` is intentionally a short, read-only preflight.  The daemon has
    already counted blocks at startup, so this never rescans the project.
    Older daemons simply lack the profile and retain the conservative fallback.
    """
    if requested_timeout is not None:
        return requested_timeout
    try:
        response = send_command_reverse("status", {}, timeout=_PROFILE_LOOKUP_TIMEOUT)
        profile = response.get("data", {}).get("timeout_profile", {})
        value = profile.get("timeouts", {}).get(method, profile.get("default"))
        if value is not None:
            blocks = profile.get("block_count")
            label = "unknown size" if blocks is None else "{0} ST block(s)".format(blocks)
            _print_info("Timeout: {0}s for {1}".format(value, label))
            return float(value)
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    return fallback


def dispatch_daemon(args, output_fmt="json"):
    """Handle a top-level daemon command. Return True if handled, else False."""
    command = args.command

    if command in _DAEMON_METHODS:
        params = {}
        if command == "import":
            if getattr(args, "dry_run", False):
                # Dry-run shows the same preview as compare.
                cmd_daemon(
                    "sync_compare_text",
                    {},
                    timeout=_daemon_timeout(
                        "sync_compare_text", getattr(args, "timeout", None), 60
                    ),
                    output_fmt=output_fmt,
                )
                return True
            if getattr(args, "save", False):
                params["save"] = True
            if getattr(args, "no_refresh", False):
                params["refresh"] = False
        if command == "download" and getattr(args, "start", None) is not None:
            params["start"] = args.start
        if command == "plc-crc" and getattr(args, "build", False):
            cmd_daemon(
                "build",
                {},
                timeout=_daemon_timeout("build", getattr(args, "timeout", None)),
                output_fmt=output_fmt,
            )
        timeout = _daemon_timeout(
            _DAEMON_METHODS[command], getattr(args, "timeout", None), 30
        )
        cmd_daemon(
            _DAEMON_METHODS[command],
            params,
            timeout=timeout,
            output_fmt=output_fmt,
        )
        return True

    if command == "connect":
        params = {}
        if args.ip:
            params["ipAddress"] = args.ip
        if args.gateway:
            params["gatewayName"] = args.gateway
        cmd_daemon(
            "connect_to_device", params, timeout=_daemon_timeout("connect_to_device", args.timeout, 60), output_fmt=output_fmt
        )
        return True

    if command == "read":
        cmd_daemon(
            "read_variable",
            {"name": args.name},
            timeout=_daemon_timeout("read_variable", args.timeout, 25),
            output_fmt=output_fmt,
        )
        return True

    if command == "write":
        _handle_write(args, output_fmt)
        return True

    if command == "test":
        params = {}
        if args.file:
            params["file"] = args.file
        cmd_daemon("cicd", params, timeout=_daemon_timeout("cicd", args.timeout, 120), output_fmt=output_fmt)
        return True

    if command == "project-tree":
        cmd_daemon(
            "project_tree",
            {"depth": args.depth},
            timeout=_daemon_timeout("project_tree", args.timeout, 30),
            output_fmt=output_fmt,
        )
        return True

    if command == "read-object":
        params = {}
        if args.path:
            params["path"] = args.path
        if args.name:
            params["name"] = args.name
        if args.guid:
            params["guid"] = args.guid
        cmd_daemon("read_object", params, timeout=_daemon_timeout("read_object", args.timeout, 30), output_fmt=output_fmt)
        return True

    if command == "update-pou":
        params = {
            "name": args.name,
            "st_path": args.st_path,
        }
        if args.app:
            params["app"] = args.app
        cmd_daemon("update_pou", params, timeout=_daemon_timeout("update_pou", args.timeout, 25), output_fmt=output_fmt)
        return True

    if command == "delete-pou":
        params = {"name": args.name}
        if args.app:
            params["app"] = args.app
        cmd_daemon("delete_pou", params, timeout=_daemon_timeout("delete_pou", args.timeout, 10), output_fmt=output_fmt)
        return True

    if command == "read-log":
        params = {}
        if args.last:
            params["last"] = args.last
        if args.clear:
            params["clear"] = True
        cmd_daemon("read_log", params, timeout=_daemon_timeout("read_log", args.timeout, 10), output_fmt=output_fmt)
        return True

    return False


def _handle_write(args, output_fmt):
    """Write a variable then read it back so callers can verify the value.

    Both the write and the read-back are returned in one response.
    """
    try:
        timeout = _daemon_timeout("write_variable", args.timeout, 25)
        wr = send_command_reverse(
            "write_variable",
            {"name": args.name, "value": args.value},
            timeout=timeout,
        )
        if not wr.get("ok"):
            _print_rp_error(wr, "write_variable")
            sys.exit(1)
        rb = send_command_reverse(
            "read_variable", {"name": args.name}, timeout=timeout
        )
        read_back = rb.get("data", {}) if rb.get("ok") else {}
        print(
            _format_output(
                {"written": True, "read_back": read_back},
                fmt=output_fmt,
                title="write",
            )
        )
    except RuntimeError as e:
        _print_error("Write failed: {0}".format(e))
        sys.exit(1)
