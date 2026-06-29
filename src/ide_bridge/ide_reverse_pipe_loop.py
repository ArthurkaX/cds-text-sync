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

import io
import json
import os
import sys
import tempfile
import time
import traceback

import clr

# Add ide_bridge dir to path
_LOOP_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOOP_DIR not in sys.path:
    sys.path.insert(0, _LOOP_DIR)

import ide_online_helpers as _helpers
import ide_runtime_common as _common

clr.AddReference("System.IO.Pipes")
clr.AddReference("System.IO")

from System.IO.Pipes import NamedPipeClientStream, PipeDirection

# ── Shared state / helpers (imported from ide_daemon_state) ───────────────

from ide_daemon_state import (
    PIPE_NAME,
    VERSION,
    POLL_INTERVAL,
    CONNECT_TIMEOUT_MS,
    LOG_FILE,
    MAX_MESSAGE_SIZE,
    _DEFAULT_CONFIG,
    _now,
    _log,
    _read_text_utf8,
    _read_json_from_pipe,
    _write_json_to_pipe,
    _require_param,
    _get_active_project,
    _obj_name,
    _json_safe,
    _build_path,
    _clear_path_cache,
    _load_daemon_config,
    _save_daemon_config,
    _check_permission,
    _get_status_info,
    _read_online_attr,
    _bool_or_none,
    _get_plc_status_snapshot,
)

from ide_daemon_helpers import (
    _get_project_info_object,
    _project_info_summary,
    _project_info_properties,
    _get_device_objects,
    _invalidate_device_cache,
    _find_object_in_project,
    _active_application_name,
    _read_text_member,
    _find_object_by_selector,
    _ensure_online_app,
    _build_tree,
    _get_sync_folder,
    _active_app_online_state,
)

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
        },
    }


def _handle_status(params):
    result = _get_status_info()
    result["running"] = sys._codesys_daemon_loop.get("running", False)
    result["mode"] = "reverse_pipe"
    result["plc"] = _get_plc_status_snapshot()
    return {"ok": True, "data": result}


_ALIASES = {
    "connect": "connect_to_device",
    "disconnect": "disconnect_from_device",
    "app": "application_state",
    "proj": "project_info",
    "tree": "project_tree",
}

_NO_PERMISSION = frozenset([
    "ping",
    "status",
    "help",
    "stop",
    "permissions",
    "sync",
    "project_info",
    "project_tree",
    "read_object",
    "explore",
])

_DISPATCH = {
    # params-taking handlers
    "project_tree": _cmd_project_tree,
    "read_object": _cmd_read_object,
    "connect_to_device": _cmd_connect_to_device,
    "download": _cmd_download,
    "read_variable": _cmd_read_variable,
    "write_variable": _cmd_write_variable,
    "read_variables": _cmd_read_variables,
    "write_variables": _cmd_write_variables,
    "export": _cmd_export,
    "build": _cmd_build,
    "device_status": _cmd_device_status,
    "test_online": _cmd_test_online,
    "sync_export": _cmd_sync_export,
    "sync_import": _cmd_sync_import,
    "sync_compare": _cmd_sync_compare,
    "sync_export_text": _cmd_sync_export_text,
    "sync_import_text": _cmd_sync_import_text,
    "sync_compare_text": _cmd_sync_compare_text,
    "update_pou": _cmd_update_pou,
    "delete_pou": _cmd_delete_pou,
    "cicd": _cmd_cicd,
    "read_log": _cmd_read_log,
    "reset_plc": _cmd_reset_plc,
    "source_download": _cmd_source_download,
    "probe": _cmd_probe_oa,
    "application_tree": _cmd_application_tree,
    "plc_files": _cmd_plc_files,
    "plc_log": _cmd_plc_log,
    "plc_download": _cmd_plc_download,
    "plc_upload": _cmd_plc_upload,
    "export_csv": _cmd_export_csv,
    "export_st": _cmd_export_st,
    "app_crc": _cmd_app_crc,
    "app_history": _cmd_app_history,
    "compare": _cmd_compare_crc,
    # inline special cases (already accept params)
    "stop": _handle_stop,
    "ping": _handle_ping,
    "status": _handle_status,
    # no-arg handlers
    "project_info": _noarg(_cmd_project_info),
    "application_state": _noarg(_cmd_application_state),
    "disconnect_from_device": _noarg(_cmd_disconnect_from_device),
    "explore": _noarg(_cmd_explore_api),
    "sync": _noarg(_cmd_sync_info),
    "help": _noarg(_cmd_help),
    "start_plc": _noarg(_cmd_start_plc),
    "stop_plc": _noarg(_cmd_stop_plc),
    "create_boot_app": _noarg(_cmd_create_boot_app),
    "app_info": _noarg(_cmd_app_info),
    "permissions": _noarg(_cmd_permissions),
}


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
    capture_codesys_globals()
    sys._codesys_daemon_loop["running"] = True
    sys._codesys_daemon_loop["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sys._codesys_daemon_loop["started"] = True

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
        except Exception as e:
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
    # Called from Project_daemon.py via exec()
    # Check if globals suggest we're inside CODESYS
    if globals().get("projects") is not None or globals().get("system") is not None:
        run_loop()
