# -*- coding: utf-8 -*-
"""
_cli_handlers_project.py - Project/device/PLC command handlers.

Covers cmd_project_*, cmd_compare, cmd_device_status, cmd_connect,
cmd_disconnect, cmd_read_var, cmd_write_var, cmd_simulate,
cmd_set_credentials, cmd_application_state, cmd_diagnose_online,
cmd_discover, cmd_pou_delete.
"""

from __future__ import annotations

from cds_cli._cli_io import (
    _daemon_path,
    _print_error,
    _print_warn,
    _project_command,
)


# -- Project commands ---------------------------------------------------------


def cmd_project_info():
    _project_command("project_info")


def cmd_project_tree(depth=0):
    _project_command("project_tree", {"depth": depth})


def cmd_project_read(path="", name="", guid=""):
    params = {}
    if path:
        params["path"] = path
    if name:
        params["name"] = name
    if guid:
        params["guid"] = guid
    _project_command("read_object", params)


def cmd_project_open(path=""):
    """Open a project in CODESYS."""
    # Loading a project from disk can take a while on large projects.
    _project_command("project_open", {"path": _daemon_path(path)}, timeout=180)


def cmd_project_close():
    """Close the current project in CODESYS.

    Closing a large or online project can exceed the default 30s timeout,
    so a longer timeout (60s) is used.  Note that a CODESYS modal dialog
    (disconnect / save prompt) may still block the daemon and requires
    manual dismissal.
    """
    _project_command("project_close", timeout=60)


def cmd_project_list():
    """List all open projects in CODESYS."""
    _project_command("project_list")


def cmd_project_snapshot(path=""):
    """Export project snapshot (full XML) via daemon."""
    _project_command("export", {"output": _daemon_path(path)} if path else {})


def cmd_project_build():
    """Build (compile) the project via daemon."""
    _project_command("build")


def cmd_project_list_devices():
    """List devices in the project via daemon."""
    _project_command("list_devices")


# -- Device / PLC commands ----------------------------------------------------


def cmd_device_status(device=""):
    """Check online/connection status of devices."""
    params = {}
    if device:
        params["device"] = device
    _project_command("device_status", params)


def cmd_connect(ip="", gateway="Gateway-1"):
    """Connect to a real PLC device."""
    params = {"ipAddress": ip, "gatewayName": gateway}
    _project_command("connect_to_device", params)


def cmd_disconnect():
    """Disconnect from PLC device."""
    _project_command("disconnect_from_device")


def cmd_read_var(name):
    """Read a PLC variable."""
    _project_command("read_variable", {"name": name})


def cmd_write_var(name, value):
    """Write a value to a PLC variable."""
    _project_command("write_variable", {"name": name, "value": value})


def cmd_simulate(enable="on"):
    """Enable/disable simulation mode."""
    # Toggling simulation scans the device tree and saves the project.
    _project_command(
        "set_simulation_mode",
        {"enable": enable},
        timeout=120,
    )


def cmd_set_credentials(username, password=""):
    """Set PLC login credentials."""
    _project_command(
        "set_credentials",
        {"username": username, "password": password},
    )


def cmd_application_state():
    """Get application online state."""
    _project_command("application_state")


def cmd_diagnose_online():
    """Diagnose online connection."""
    _project_command("diagnose_online")


def cmd_discover():
    """Discover CODESYS installations and open projects via daemon."""
    # Full object-tree + profile-coverage diagnostic is slow on large projects.
    _project_command("discover", timeout=180)


def cmd_compare(against=""):
    """Compare live project against a snapshot.

    Without --against the daemon compares against the newest snapshot in the
    sync folder's .dump/, the same one `import` would take, and reports a clear
    error if none exists.
    """
    # `compare` is a deprecated alias for the online CRC read; the snapshot
    # comparison that reads --against is `sync_compare`.
    _project_command("sync_compare", {"against": _daemon_path(against)}, timeout=120)


# -- POU deletion -------------------------------------------------------------


def cmd_pou_delete(name="", app=""):
    """Delete a POU from the project."""
    if not name:
        _print_error("POU name is required")
        return
    params = {"name": name}
    if app:
        params["app"] = app
    _project_command("delete_pou", params)


# -- Subcommand dispatch ------------------------------------------------------

# Hidden `project`/`pou` actions that duplicate a modern top-level command
# (same daemon method). They keep working but emit a deprecation warning to
# stderr pointing at the replacement. Actions absent here are unique — no
# top-level equivalent — and dispatch silently: open, close, list, snapshot
# (daemon `export`, not `sync_export_text`), list-devices, compare (unique
# --against), device-status, simulate, set-credentials, diagnose-online.
_DEPRECATED_PROJECT_ACTIONS = {
    "info": "cts project-info",
    "tree": "cts project-tree",
    "read": "cts read-object",
    "build": "cts build",
    "connect": "cts connect",
    "disconnect": "cts disconnect",
    "read-var": "cts read",
    "write-var": "cts write",
    "application-state": "cts app-state",
}


def _warn_deprecated(invocation, replacement):
    _print_warn(
        "'{0}' is deprecated; use '{1}' instead.".format(invocation, replacement)
    )


def dispatch_project(args):
    """Route a parsed `project` subcommand to its cmd_* handler."""
    action = args.project_action
    replacement = _DEPRECATED_PROJECT_ACTIONS.get(action)
    if replacement:
        _warn_deprecated("cts project {0}".format(action), replacement)
    if action == "info":
        cmd_project_info()
    elif action == "tree":
        cmd_project_tree(depth=args.depth)
    elif action == "read":
        cmd_project_read(path=args.path, name=args.name, guid=args.guid)
    elif action == "open":
        cmd_project_open(path=args.path)
    elif action == "close":
        cmd_project_close()
    elif action == "list":
        cmd_project_list()
    elif action == "snapshot":
        cmd_project_snapshot(path=args.path)
    elif action == "build":
        cmd_project_build()
    elif action == "list-devices":
        cmd_project_list_devices()
    elif action == "compare":
        cmd_compare(against=args.against)
    elif action == "device-status":
        cmd_device_status(device=args.device)
    elif action == "connect":
        cmd_connect(ip=args.ip, gateway=args.gateway)
    elif action == "disconnect":
        cmd_disconnect()
    elif action == "read-var":
        cmd_read_var(name=args.name)
    elif action == "write-var":
        cmd_write_var(name=args.name, value=args.value)
    elif action == "simulate":
        cmd_simulate(enable=args.enable)
    elif action == "set-credentials":
        cmd_set_credentials(username=args.username, password=args.password)
    elif action == "application-state":
        cmd_application_state()
    elif action == "diagnose-online":
        cmd_diagnose_online()


def dispatch_pou(args):
    """Route a parsed `pou` subcommand to its cmd_* handler."""
    if args.pou_action == "delete":
        _warn_deprecated("cts pou delete", "cts delete-pou")
        cmd_pou_delete(name=args.name, app=args.app)
