# -*- coding: utf-8 -*-
"""
_cli_handlers_project.py - Project/device/PLC command handlers.

Covers cmd_project_*, cmd_compare, cmd_device_status, cmd_connect,
cmd_disconnect, cmd_read_var, cmd_write_var, cmd_simulate,
cmd_set_credentials, cmd_application_state, cmd_diagnose_online,
cmd_discover, cmd_pou_delete.
"""

from __future__ import annotations

import sys

from cli._cli_io import _print_error, _project_command


# -- Project commands ---------------------------------------------------------


def cmd_project_info(use_reverse=False):
    _project_command("project_info", use_reverse=use_reverse)


def cmd_project_tree(depth=0, use_reverse=False):
    _project_command("project_tree", {"depth": depth}, use_reverse=use_reverse)


def cmd_project_read(path="", name="", guid="", use_reverse=False):
    params = {}
    if path:
        params["path"] = path
    if name:
        params["name"] = name
    if guid:
        params["guid"] = guid
    _project_command("read_object", params, use_reverse=use_reverse)


def cmd_project_open(path="", use_reverse=False):
    """Open a project in CODESYS."""
    _project_command("project_open", {"path": path}, use_reverse=use_reverse)


def cmd_project_close(use_reverse=False):
    """Close the current project in CODESYS."""
    _project_command("project_close", use_reverse=use_reverse)


def cmd_project_list(use_reverse=False):
    """List all open projects in CODESYS."""
    _project_command("project_list", use_reverse=use_reverse)


def cmd_project_snapshot(path="", use_reverse=False):
    """Export project snapshot (full XML) via daemon."""
    _project_command(
        "export", {"output": path} if path else {}, use_reverse=use_reverse
    )


def cmd_project_build(use_reverse=False):
    """Build (compile) the project via daemon."""
    _project_command("build", use_reverse=use_reverse)


def cmd_project_list_devices(use_reverse=False):
    """List devices in the project via daemon."""
    _project_command("list_devices", use_reverse=use_reverse)


# -- Device / PLC commands ----------------------------------------------------


def cmd_device_status(device="", use_reverse=False):
    """Check online/connection status of devices."""
    params = {}
    if device:
        params["device"] = device
    _project_command("device_status", params, use_reverse=use_reverse)


def cmd_connect(ip="", gateway="Gateway-1", use_reverse=False):
    """Connect to a real PLC device."""
    params = {"ipAddress": ip, "gatewayName": gateway}
    _project_command("connect_to_device", params, use_reverse=use_reverse)


def cmd_disconnect(use_reverse=False):
    """Disconnect from PLC device."""
    _project_command("disconnect_from_device", use_reverse=use_reverse)


def cmd_read_var(name, use_reverse=False):
    """Read a PLC variable."""
    _project_command("read_variable", {"name": name}, use_reverse=use_reverse)


def cmd_write_var(name, value, use_reverse=False):
    """Write a value to a PLC variable."""
    _project_command(
        "write_variable", {"name": name, "value": value}, use_reverse=use_reverse
    )


def cmd_simulate(enable="on", use_reverse=False):
    """Enable/disable simulation mode."""
    _project_command("set_simulation_mode", {"enable": enable}, use_reverse=use_reverse)


def cmd_set_credentials(username, password="", use_reverse=False):
    """Set PLC login credentials."""
    _project_command(
        "set_credentials",
        {"username": username, "password": password},
        use_reverse=use_reverse,
    )


def cmd_application_state(use_reverse=False):
    """Get application online state."""
    _project_command("application_state", use_reverse=use_reverse)


def cmd_diagnose_online(use_reverse=False):
    """Diagnose online connection."""
    _project_command("diagnose_online", use_reverse=use_reverse)


def cmd_discover(use_reverse=False):
    """Discover CODESYS installations and open projects via daemon."""
    _project_command("discover", use_reverse=use_reverse)


def cmd_compare(against="", use_reverse=False):
    """Compare live project against a snapshot."""
    if not against:
        _print_error("Specify --against <path> for compare")
        return
    _project_command(
        "compare", {"against": against}, timeout=120, use_reverse=use_reverse
    )


# -- POU deletion -------------------------------------------------------------


def cmd_pou_delete(name="", app="", use_reverse=False):
    """Delete a POU from the project."""
    if not name:
        _print_error("POU name is required")
        return
    params = {"name": name}
    if app:
        params["app"] = app
    _project_command("delete_pou", params, use_reverse=use_reverse)


# -- Subcommand dispatch ------------------------------------------------------


def dispatch_project(args, use_reverse=True):
    """Route a parsed `project` subcommand to its cmd_* handler."""
    action = args.project_action
    if action == "info":
        cmd_project_info(use_reverse=use_reverse)
    elif action == "tree":
        cmd_project_tree(depth=args.depth, use_reverse=use_reverse)
    elif action == "read":
        cmd_project_read(
            path=args.path, name=args.name, guid=args.guid, use_reverse=use_reverse
        )
    elif action == "open":
        cmd_project_open(path=args.path, use_reverse=use_reverse)
    elif action == "close":
        cmd_project_close(use_reverse=use_reverse)
    elif action == "list":
        cmd_project_list(use_reverse=use_reverse)
    elif action == "snapshot":
        cmd_project_snapshot(path=args.path, use_reverse=use_reverse)
    elif action == "build":
        cmd_project_build(use_reverse=use_reverse)
    elif action == "list-devices":
        cmd_project_list_devices(use_reverse=use_reverse)
    elif action == "compare":
        cmd_compare(against=args.against, use_reverse=use_reverse)
    elif action == "device-status":
        cmd_device_status(device=args.device, use_reverse=use_reverse)
    elif action == "connect":
        cmd_connect(ip=args.ip, gateway=args.gateway, use_reverse=use_reverse)
    elif action == "disconnect":
        cmd_disconnect(use_reverse=use_reverse)
    elif action == "read-var":
        cmd_read_var(name=args.name, use_reverse=use_reverse)
    elif action == "write-var":
        cmd_write_var(name=args.name, value=args.value, use_reverse=use_reverse)
    elif action == "simulate":
        cmd_simulate(enable=args.enable, use_reverse=use_reverse)
    elif action == "set-credentials":
        cmd_set_credentials(
            username=args.username, password=args.password, use_reverse=use_reverse
        )
    elif action == "application-state":
        cmd_application_state(use_reverse=use_reverse)
    elif action == "diagnose-online":
        cmd_diagnose_online(use_reverse=use_reverse)


def dispatch_pou(args, use_reverse=True):
    """Route a parsed `pou` subcommand to its cmd_* handler."""
    if args.pou_action == "delete":
        cmd_pou_delete(name=args.name, app=args.app, use_reverse=use_reverse)
