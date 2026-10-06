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
import time

from cds_cli._cli_io import (
    _format_output,
    _print_error,
    _print_error_context,
    _print_info,
    _print_rp_error,
    cmd_daemon,
    send_command_reverse,
)
from cts_shared import wire

# command name -> daemon method for the thin passthrough family. This is a CLI
# namespace, not the protocol's alias table (that one is command_registry
# ALIASES in the host): names here are what `cts <cmd>` accepts. "stop" is the
# PLC runtime stop, stop_plc; the daemon's own shutdown method is stop_daemon.
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
    "set-sync-folder": "set_sync_folder",
    "permissions": "permissions",
    "last-result": "last_result",
}


_PROFILE_LOOKUP_TIMEOUT = 10

#: Methods whose *refusal* is routine (an online import is refused at once),
#: so announcing "Timeout: 180s ..." before the call is noise: the command
#: never starts, and the line reads as if it had. The timeout is still used;
#: only the announcement is suppressed.
_NO_TIMEOUT_ANNOUNCE = frozenset(["sync_import_text"])


def _daemon_timeout(method, requested_timeout=None, fallback=30, announce=None):
    """Resolve a daemon-owned automatic timeout; explicit values win.

    ``timeout_profile`` is intentionally a short, read-only preflight which
    does not inspect the PLC connection. The daemon has already counted blocks
    at startup, so this never rescans the project or invalidates online state.
    Older daemons simply lack the profile and retain the conservative fallback.
    """
    if requested_timeout is not None:
        return requested_timeout
    if announce is None:
        announce = method not in _NO_TIMEOUT_ANNOUNCE
    try:
        response = send_command_reverse(
            "timeout_profile", {}, timeout=_PROFILE_LOOKUP_TIMEOUT
        )
        profile = response.get("data", {})
        value = profile.get("timeouts", {}).get(method, profile.get("default"))
        if value is not None:
            blocks = profile.get("block_count")
            label = "unknown size" if blocks is None else "{0} ST block(s)".format(blocks)
            if announce:
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
        if command == "set-sync-folder":
            if getattr(args, "path", ""):
                params["path"] = args.path
            if getattr(args, "save", False):
                params["save"] = True
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
        if command == "build" and getattr(args, "install", False):
            params["install"] = True
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


#: How long the read-back waits for the PLC to show the value that was
#: written. A prepared write is applied by the runtime, not by the read: live,
#: writing FALSE read back TRUE because the read raced the next task cycle.
#: The budget is wall-clock, and deliberately short -- a value the program
#: overwrites every cycle will never match, and the CLI must still return.
_READ_BACK_BUDGET_S = 2.0
_READ_BACK_POLL_S = 0.2


def _handle_write(args, output_fmt):
    """Write a variable, then read it back and confirm it took effect.

    The read-back polls for up to ``_READ_BACK_BUDGET_S`` because the PLC
    applies the write on a task cycle. When the value still differs, the
    response says so explicitly (``confirmed: false`` and a ``note``) instead
    of printing the write as if it had been verified.
    """
    try:
        timeout = _daemon_timeout("write_variable", args.timeout, 25)
        wr = send_command_reverse(
            "write_variable",
            {"name": args.name, "value": args.value},
            timeout=timeout,
        )
        if not wire.response_ok(wr):
            _print_rp_error(wr, "write_variable")
            sys.exit(1)
        read_back, confirmed = _confirm_write(args.name, args.value, timeout)
        payload = {"written": True, "read_back": read_back, "confirmed": confirmed}
        if not confirmed and not read_back.get("unavailable"):
            payload["note"] = (
                "the PLC still reports {0!r} after writing {1!r} and waiting "
                "{2:g}s; the program may overwrite it every cycle, or the "
                "write may not have taken effect. Not confirmed.".format(
                    read_back.get("value"), args.value, _READ_BACK_BUDGET_S
                )
            )
        print(_format_output(payload, fmt=output_fmt, title="write"))
    except RuntimeError as e:
        _print_error("Write failed: {0}".format(e))
        sys.exit(1)


def _confirm_write(name, value, timeout):
    """Read *name* back until it shows *value*. Return ``(read_back, confirmed)``.

    An unavailable read-back stops the poll at once (the value is unknown, not
    stale); so does budget exhaustion. What is returned is the last read-back
    seen, so the caller can show what the PLC actually said.
    """
    deadline = time.monotonic() + _READ_BACK_BUDGET_S
    while True:
        read_back = _read_back(name, timeout)
        if read_back.get("unavailable"):
            return read_back, False
        if _values_agree(value, read_back.get("value")):
            return read_back, True
        if time.monotonic() >= deadline:
            return read_back, False
        time.sleep(_READ_BACK_POLL_S)


def _values_agree(written, read):
    """Whether the PLC's rendering of a variable matches what was written.

    Case and whitespace are ignored, and two spellings of the same number
    compare equal; anything else is a mismatch -- an unconfirmed write must
    not be reported as verified on a guess.
    """
    if read is None:
        return False
    left = "{0}".format(written).strip()
    right = "{0}".format(read).strip()
    if left.upper() == right.upper():
        return True
    try:
        return abs(float(left) - float(right)) <= 1e-9 * max(1.0, abs(float(left)))
    except (TypeError, ValueError):
        return False


def _read_back(name, timeout):
    """Read a variable back after a write. The value, or why it is unavailable.

    A failed read-back is a daemon response like any other: its ``[ctx]`` line
    goes to stderr, the same one ``_print_rp_error`` would print. Reporting an
    empty read-back as if the variable were empty would turn a failed
    verification into a wrong fact about the PLC, so it is an explicit
    ``unavailable`` instead.
    """
    rb = send_command_reverse("read_variable", {"name": name}, timeout=timeout)
    if wire.response_ok(rb):
        return rb.get("data", {})
    _print_error_context(rb)
    return {
        "unavailable": wire.response_error(rb, "read-back failed (no error reported)")
    }
