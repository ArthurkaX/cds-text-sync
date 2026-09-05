# -*- coding: utf-8 -*-
"""
ide_reverse_pipe_loop.py — CODESYS-side reverse pipe daemon.

This module runs inside CODESYS as a polling loop.
It connects to a CLI-created named pipe server, reads one command,
executes it in the main script context, and writes back the result.

Architecture (reverse pipe):
  1. CLI creates \named pipecds-cli-<user> as server, writes command, waits
  2. CODESYS loop (every 200ms) tries to connect as client
  3. If pipe exists: read command, execute CODESYS API, write response, close
  4. If pipe does not exist: sleep and continue

This avoids calling CODESYS APIs from a background thread.
"""

from __future__ import print_function

import os
import sys
import time
import traceback

try:
    import clr
except ImportError:
    # The dispatch metadata is also inspected by the CPython test suite.
    # CODESYS provides ``clr`` through IronPython, but it is not available
    # when this module is imported offline.
    clr = None

# Add ide_bridge dir to path
_LOOP_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOOP_DIR not in sys.path:
    sys.path.insert(0, _LOOP_DIR)


if clr is not None:
    clr.AddReference("System.IO.Pipes")
    clr.AddReference("System.IO")
    from System.IO.Pipes import NamedPipeClientStream, PipeDirection
else:
    NamedPipeClientStream = None
    PipeDirection = None

# ── Shared state / helpers (imported from ide_daemon_state) ───────────────

from ide_daemon_state import (
    PIPE_NAME,
    VERSION,
    CONNECT_TIMEOUT_MS,
    _log,
    _read_json_from_pipe,
    _write_json_to_pipe,
    _load_daemon_config,
    _check_permission,
    _get_active_project,
    _get_status_info,
    _get_plc_status_snapshot,
)

from ide_daemon_helpers import (
    _get_sync_folder,
)
from ide_timeout_profile import count_st_blocks, make_timeout_profile
from ide_online_helpers import adopt_existing_online_session

from ide_handlers_plc import (
    _cmd_start_plc,
    _cmd_stop_plc,
    _cmd_reset_plc,
    _cmd_create_boot_app,
    _cmd_source_download,
    _cmd_plc_files,
    _cmd_plc_download,
    _cmd_plc_upload,
    _cmd_plc_log,
    _cmd_read_log,
)

from ide_handlers_build import (
    _cmd_export,
    _cmd_build,
    _cmd_export_csv,
    _cmd_export_st,
    _cmd_application_tree,
)

from ide_handlers_project import (
    _cmd_project_info,
    _cmd_set_sync_folder,
    _cmd_project_tree,
    _cmd_application_state,
    _cmd_connect_to_device,
    _cmd_disconnect_from_device,
    _cmd_download,
    _cmd_read_variable,
    _cmd_write_variable,
    _cmd_read_variables,
    _cmd_write_variables,
    _cmd_read_object,
    _cmd_device_status,
    _cmd_test_online,
    _cmd_explore_api,
    _cmd_help,
    _cmd_probe_oa,
    _cmd_project_open,
    _cmd_project_close,
    _cmd_project_list,
    _cmd_list_devices,
    _cmd_set_simulation_mode,
    _cmd_set_credentials,
    _cmd_diagnose_online,
    _cmd_discover,
)

from ide_handlers_crc import (
    _cmd_app_crc,
    _cmd_app_info,
    _cmd_app_history,
    _cmd_compare_crc,
    _cmd_permissions,
)

from ide_handlers_sync import (
    _cmd_sync_info,
    _cmd_sync_export,
    _cmd_sync_import,
    _cmd_sync_compare,
    _cmd_sync_export_text,
    _cmd_sync_import_text,
    _cmd_sync_compare_text,
    _cmd_update_pou,
    _cmd_delete_pou,
)

from ide_handlers_cicd import _cmd_cicd

# ── UI Dashboard (WinForms) ────────────────────────────────────────────────

_DASHBOARD = None
_ui = None
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    import ide_daemon_ui as _ui

    _DASHBOARD = "winforms"
except Exception:
    _ui = None

# ── Global state ──────────────────────────────────────────────────────────

if not hasattr(sys, "_codesys_daemon_loop"):
    sys._codesys_daemon_loop = {
        "running": False,
        "started": False,
        "projects": None,
        "system": None,
        "started_at": None,
        "command_count": 0,
        "last_command": None,
        "online_app": None,
        "online_target_app": None,
        "timeout_profile": None,
    }


# ── Capture globals ───────────────────────────────────────────────────────


def capture_codesys_globals():
    g = globals()
    projects_obj = g.get("projects")
    system_obj = g.get("system")

    if projects_obj is not None and hasattr(projects_obj, "primary"):
        sys._codesys_daemon_loop["projects"] = projects_obj
    else:
        try:
            import __main__

            if hasattr(__main__, "projects"):
                proj = __main__.projects
                if hasattr(proj, "primary"):
                    sys._codesys_daemon_loop["projects"] = proj
            if hasattr(__main__, "system"):
                sys._codesys_daemon_loop["system"] = __main__.system
        except Exception:
            pass

    if system_obj is not None:
        sys._codesys_daemon_loop["system"] = system_obj

    if sys._codesys_daemon_loop["projects"] is None:
        _log("WARNING: projects not captured!")
    if sys._codesys_daemon_loop["system"] is None:
        _log("WARNING: system not captured!")


# ── Command handler ────────────────────────────────────────────────────────


def _noarg(fn):
    def _call(params):
        return fn()
    return _call


def _handle_stop(params):
    sys._codesys_daemon_loop["running"] = False
    return {"ok": True, "data": {"message": "Daemon stopping..."}}


def _handle_ping(params):
    return {
        "ok": True,
        "data": {
            "status": "pong",
            "mode": "reverse_pipe",
            "pid": os.getpid(),
            "plc": _get_plc_status_snapshot(),
            "timeout_profile": sys._codesys_daemon_loop.get("timeout_profile"),
        },
    }


def _handle_status(params):
    result = _get_status_info()
    result["running"] = sys._codesys_daemon_loop.get("running", False)
    result["mode"] = "reverse_pipe"
    result["plc"] = _get_plc_status_snapshot()
    result["timeout_profile"] = sys._codesys_daemon_loop.get("timeout_profile")
    return {"ok": True, "data": result}


def _handle_timeout_profile(params):
    """Return startup-sized timeouts without probing the PLC session."""
    return {
        "ok": True,
        "data": sys._codesys_daemon_loop.get("timeout_profile", {}),
    }


import command_registry as _registry

_ALIASES = _registry.ALIASES
_NO_PERMISSION = _registry.NO_PERMISSION

_DISPATCH = {}
for _command_name, (_mode, _handler_name) in _registry.DISPATCH_SPECS.items():
    _handler = globals()[_handler_name]
    _DISPATCH[_command_name] = _noarg(_handler) if _mode == "noarg" else _handler


def handle_command(method, params):
    """Dispatch a command. All CODESYS API calls happen here, in the main loop."""
    _log("Command: {0}".format(method))
    method = _ALIASES.get(method, method)
    if method not in _NO_PERMISSION:
        allowed, reason = _check_permission(method)
        if not allowed:
            return {"ok": False, "error": reason}
    handler = _DISPATCH.get(method)
    if handler is None:
        return {"ok": False, "error": "Unknown method: {0}".format(method)}
    try:
        return handler(params)
    except Exception as e:
        _log("Command error: {0}\n{1}".format(e, traceback.format_exc()))
        return {"ok": False, "error": "{0}: {1}".format(type(e).__name__, e)}





# ── Main polling loop ─────────────────────────────────────────────────────


def _get_poll_interval():
    """Get current poll interval from config, default 0.2s."""
    config = sys._codesys_daemon_loop.get("config", {})
    if not config:
        config = _load_daemon_config()
        sys._codesys_daemon_loop["config"] = config
    return config.get("poll_ms", 200) / 1000.0


def _dashboard_command_label(method, params):
    """Return a readable dashboard label for an incoming command."""
    if method == "cicd":
        test_file = str((params or {}).get("file", "") or "").strip()
        if test_file:
            return "Run test: {0}".format(os.path.basename(test_file))
        return "Run tests: all"
    return method


def _dashboard_log_response(dash, method, response):
    """Append concise result lines to the dashboard after command execution."""
    if dash is None or method != "cicd":
        return
    try:
        if not response.get("ok"):
            dash.log_command(
                "FAIL tests: {0}".format(response.get("error", "unknown error"))
            )
            return
        data = response.get("data", {})
        summary = data.get("summary", {})
        total = int(summary.get("total", 0))
        passed = int(summary.get("ok", 0))
        failed = int(summary.get("not_ok", 0))
        for item in data.get("files", []):
            label = item.get("file") or item.get("plan") or "test"
            status = "PASS" if item.get("ok") else "FAIL"
            item_total = int(item.get("tests_ok", 0)) + int(item.get("tests_failed", 0))
            item_passed = int(item.get("tests_ok", 0))
            if item_total > 0:
                dash.log_command(
                    "{0} {1} ({2}/{3})".format(status, label, item_passed, item_total)
                )
            else:
                dash.log_command("{0} {1}".format(status, label))
        if failed:
            dash.log_command("Test suite FAIL ({0}/{1} passed)".format(passed, total))
        else:
            dash.log_command("Test suite PASS ({0}/{1})".format(passed, total))
    except Exception:
        pass


def run_loop():
    """Main polling loop. Runs inside CODESYS script context."""
    if clr is None:
        raise RuntimeError("The reverse-pipe loop must run inside CODESYS.")
    capture_codesys_globals()
    sys._codesys_daemon_loop["running"] = True
    sys._codesys_daemon_loop["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sys._codesys_daemon_loop["started"] = True

    # The supported operating order is IDE Online/Login first, daemon second.
    # Capture that existing session now; this creates only a wrapper and never
    # calls login or changes the PLC connection.
    try:
        project, _error = _get_active_project()
        online_app, _target_app = adopt_existing_online_session(project)
        if online_app is not None:
            _log("Adopted existing IDE online session")
    except Exception as error:
        _log("Could not adopt existing IDE online session: {0}".format(error))

    _log(
        "cds-text-sync v{0} started  pipe={1}  pid={2}".format(
            VERSION, PIPE_NAME, os.getpid()
        )
    )
    _log("Waiting for CLI commands...  cds-text-sync --help")

    # Warn if sync folder not configured
    sf, sf_err = _get_sync_folder()
    if sf is None:
        _log(
            '[WARN] Sync folder not configured. Set "cds-sync-folder" project property via Project_directory.py'
        )
    else:
        _log("Sync folder: {0}".format(sf))

    block_count = count_st_blocks(sf)
    profile = make_timeout_profile(block_count)
    sys._codesys_daemon_loop["timeout_profile"] = profile
    if block_count is None:
        _log("Timeout profile: project-view unavailable; using safe fallback")
    else:
        _log("Timeout profile: {0} ST block(s) counted at startup".format(block_count))

    # Show UI dashboard (WinForms window)
    _dash = None
    if _ui is not None:
        try:
            _dash = _ui.show_daemon_ui()
            # Push startup messages to dashboard
            if _dash is not None:
                _dash.log_command("Daemon v{0} started".format(VERSION))
                _dash.log_command("Waiting for CLI...")
                if sf is None:
                    _dash.log_command("[WARN] Sync folder not set")
                else:
                    _dash.log_command("Sync folder: {0}".format(os.path.basename(sf)))
        except Exception:
            _dash = None

    while sys._codesys_daemon_loop.get("running", False):
        pipe = None
        try:
            # Keep UI responsive
            if _dash is not None:
                _ui.pump_events(_dash)

            # Early exit if stop was requested via UI button
            if not sys._codesys_daemon_loop.get("running", False):
                break

            # Try to connect to the CLI's pipe server
            pipe = NamedPipeClientStream(".", PIPE_NAME, PipeDirection.InOut)
            pipe.Connect(CONNECT_TIMEOUT_MS)

            # Connected! Read the command
            cmd = _read_json_from_pipe(pipe)
            if cmd is None:
                try:
                    pipe.Close()
                except Exception:
                    pass
                time.sleep(_get_poll_interval())
                continue

            method = cmd.get("method", "")
            params = cmd.get("params", {})

            sys._codesys_daemon_loop["command_count"] = (
                sys._codesys_daemon_loop.get("command_count", 0) + 1
            )
            sys._codesys_daemon_loop["last_command"] = method

            # Log to UI
            if _dash is not None:
                try:
                    _dash.log_command(_dashboard_command_label(method, params))
                    _dash.set_command_count(sys._codesys_daemon_loop["command_count"])
                except Exception:
                    pass

            # Execute command in main script context
            response = handle_command(method, params)

            if _dash is not None:
                _dashboard_log_response(_dash, method, response)

            # Write response back
            ok = _write_json_to_pipe(pipe, response)
            if not ok:
                _log("Failed to write response for {0}".format(method))

            try:
                pipe.Close()
            except Exception:
                pass

            # If stop was requested, break out of the loop
            if method == "stop":
                break

        except Exception as e:
            # Expected: pipe not found (no CLI waiting)
            err_str = str(e)
            if (
                "timed out" in err_str.lower()
                or "Could not connect" in err_str
                or "not found" in err_str.lower()
            ):
                # Normal - no CLI pipe available
                pass
            else:
                _log("Pipe poll error: {0}".format(e))
            if pipe is not None:
                try:
                    pipe.Close()
                except Exception:
                    pass

        time.sleep(_get_poll_interval())

    _log("Reverse Pipe Daemon loop ended.")
    sys._codesys_daemon_loop["running"] = False

    # Close UI dashboard
    if _dash is not None and _ui is not None:
        try:
            _dash.close_window()
        except Exception:
            pass
    _dash = None


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__" or __name__ == "__builtin__":
    run_loop()
else:
    # Called from codesys_daemon_launcher.py via exec()
    # Check if globals suggest we're inside CODESYS
    if globals().get("projects") is not None or globals().get("system") is not None:
        run_loop()
