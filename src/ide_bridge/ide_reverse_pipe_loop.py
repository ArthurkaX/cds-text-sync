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


def handle_command(method, params):
    """Dispatch a command. All CODESYS API calls happen here, in the main loop."""
    _log("Command: {0}".format(method))

    # Command aliases (shorter CLI names -> full daemon method names)
    _ALIASES = {
        "connect": "connect_to_device",
        "disconnect": "disconnect_from_device",
        "app": "application_state",
        "proj": "project_info",
        "tree": "project_tree",
    }
    _original_method = method
    method = _ALIASES.get(method, method)

    # Commands that never require permission check (system/read-only)
    if method not in (
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
    ):
        allowed, reason = _check_permission(method)
        if not allowed:
            return {"ok": False, "error": reason}

    try:
        if method == "stop":
            sys._codesys_daemon_loop["running"] = False
            return {"ok": True, "data": {"message": "Daemon stopping..."}}

        elif method == "ping":
            return {
                "ok": True,
                "data": {
                    "status": "pong",
                    "mode": "reverse_pipe",
                    "pid": os.getpid(),
                    "plc": _get_plc_status_snapshot(),
                },
            }

        elif method == "status":
            result = _get_status_info()
            result["running"] = sys._codesys_daemon_loop.get("running", False)
            result["mode"] = "reverse_pipe"
            result["plc"] = _get_plc_status_snapshot()
            return {"ok": True, "data": result}

        elif method == "project_info":
            return _cmd_project_info()

        elif method == "project_tree":
            return _cmd_project_tree(params)

        elif method == "read_object":
            return _cmd_read_object(params)

        elif method == "application_state":
            return _cmd_application_state()

        elif method == "connect_to_device":
            return _cmd_connect_to_device(params)

        elif method == "disconnect_from_device":
            return _cmd_disconnect_from_device()

        elif method == "download":
            return _cmd_download(params)

        elif method == "read_variable":
            return _cmd_read_variable(params)

        elif method == "write_variable":
            return _cmd_write_variable(params)

        elif method == "read_variables":
            return _cmd_read_variables(params)

        elif method == "write_variables":
            return _cmd_write_variables(params)

        elif method == "export":
            return _cmd_export(params)

        elif method == "build":
            return _cmd_build(params)

        elif method == "device_status":
            return _cmd_device_status(params)

        elif method == "test_online":
            return _cmd_test_online(params)

        elif method == "explore":
            return _cmd_explore_api()

        elif method == "sync":
            return _cmd_sync_info()

        elif method == "sync_export":
            return _cmd_sync_export(params)

        elif method == "sync_import":
            return _cmd_sync_import(params)

        elif method == "sync_compare":
            return _cmd_sync_compare(params)

        elif method == "sync_export_text":
            return _cmd_sync_export_text(params)

        elif method == "sync_import_text":
            return _cmd_sync_import_text(params)
        elif method == "update_pou":
            return _cmd_update_pou(params)

        elif method == "delete_pou":
            return _cmd_delete_pou(params)

        elif method == "cicd":
            return _cmd_cicd(params)
        elif method == "sync_compare_text":
            return _cmd_sync_compare_text(params)

        elif method == "help":
            return _cmd_help()

        elif method == "read_log":
            return _cmd_read_log(params)

        elif method == "start_plc":
            return _cmd_start_plc()

        elif method == "stop_plc":
            return _cmd_stop_plc()

        elif method == "reset_plc":
            return _cmd_reset_plc(params)

        elif method == "create_boot_app":
            return _cmd_create_boot_app()

        elif method == "source_download":
            return _cmd_source_download(params)

        elif method == "probe":
            return _cmd_probe_oa(params)

        elif method == "application_tree":
            return _cmd_application_tree(params)

        elif method == "plc_files":
            return _cmd_plc_files(params)

        elif method == "plc_log":
            return _cmd_plc_log(params)

        elif method == "plc_download":
            return _cmd_plc_download(params)

        elif method == "plc_upload":
            return _cmd_plc_upload(params)

        elif method == "export_csv":
            return _cmd_export_csv(params)

        elif method == "export_st":
            return _cmd_export_st(params)

        elif method == "app_crc":
            return _cmd_app_crc(params)

        elif method == "app_info":
            return _cmd_app_info()

        elif method == "app_history":
            return _cmd_app_history(params)

        elif method == "permissions":
            return _cmd_permissions()

        elif method == "compare":
            return _cmd_compare_crc(params)

        else:
            return {"ok": False, "error": "Unknown method: {0}".format(method)}

    except Exception as e:
        _log("Command error: {0}\n{1}".format(e, traceback.format_exc()))
        return {"ok": False, "error": "{0}: {1}".format(type(e).__name__, e)}


# ── Command implementations ───────────────────────────────────────────────







def _cmd_app_crc(params):
    """Get CRC and metadata of the Application on PLC.

    Downloads Application.crc and Application.app info from PlcLogic.
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        online_dev = oa.get_online_device()
        if online_dev is None:
            return {"ok": False, "error": "get_online_device() returned None"}

        app_dir = None
        result = {}

        # If params specifies app_dir explicitly, use it directly
        if "app_dir" in params:
            app_dir = params["app_dir"]
        else:
            # Auto-detect application directory
            try:
                root_files = online_dev.get_file_list_of_directory("PlcLogic")
                if root_files is not None:
                    for f in root_files:
                        try:
                            sub_name = str(getattr(f, "name", "") or "")
                            if sub_name in (
                                ".",
                                "..",
                                "_cnc",
                                "ac_persistence",
                                "trend",
                                "alarms",
                                "visu",
                            ):
                                continue
                            # Check if this subdir has .crc files
                            try:
                                sub_files = online_dev.get_file_list_of_directory(
                                    "PlcLogic/" + sub_name
                                )
                                if sub_files is not None:
                                    for sf in sub_files:
                                        sf_name = str(getattr(sf, "name", "") or "")
                                        if sf_name.endswith(".crc"):
                                            app_dir = "PlcLogic/" + sub_name
                                            result["app_name"] = sub_name
                                            break
                            except Exception:
                                pass
                            if app_dir:
                                break
                        except Exception:
                            pass
            except Exception as e:
                result["detect_error"] = str(e)[:200]

        if app_dir is None:
            # Fallback to default
            app_dir = "PlcLogic/Application"
            result["app_name"] = "Application"

        # 1. List Application directory
        try:
            files = online_dev.get_file_list_of_directory(app_dir)
            if files is not None:
                for f in files:
                    try:
                        name = str(getattr(f, "name", "") or "")
                        if (
                            name.endswith(".app")
                            or name.endswith(".crc")
                            or name.endswith(".ret")
                        ):
                            info = {"name": name}
                            for attr in [
                                "length",
                                "Length",
                                "size",
                                "Size",
                                "creation_time",
                                "CreationTime",
                                "last_write_time",
                                "LastWriteTime",
                            ]:
                                if hasattr(f, attr):
                                    try:
                                        val = getattr(f, attr)
                                        if callable(val):
                                            val = val()
                                        if val is not None:
                                            info[attr.lower()] = str(val)
                                    except Exception:
                                        pass
                            result[name] = info
                    except Exception:
                        pass
        except Exception as e:
            result["list_error"] = str(e)[:200]

        # 2. Download and parse Application.crc
        if not hasattr(online_dev, "upload_file"):
            result["crc_note"] = "upload_file not available"
        else:
            tmp = tempfile.mktemp(suffix=".crc")
            try:
                # Find the .crc file name
                crc_filename = "Application.crc"
                try:
                    files = online_dev.get_file_list_of_directory(app_dir)
                    if files is not None:
                        for f in files:
                            fn = str(getattr(f, "name", "") or "")
                            if fn.endswith(".crc"):
                                crc_filename = fn
                                break
                except Exception:
                    pass

                online_dev.upload_file(app_dir + "/" + crc_filename, tmp, True)
                with open(tmp, "rb") as f:
                    data = f.read()
                if len(data) >= 8:
                    crc_bytes = data[:8]
                    # hex in IronPython 2.7 (no .hex())
                    result["crc_hex"] = "".join(
                        "{:02x}".format(ord(c)) for c in crc_bytes
                    )
                    # Try to interpret as two uint32 little-endian
                    try:
                        import struct

                        c1, c2 = struct.unpack("<II", data[:8])
                        result["crc_value"] = "{:08X}{:08X}".format(c1, c2)
                    except Exception:
                        pass
                if len(data) > 8:
                    name_part = data[8:].rstrip("\x00")
                    if name_part:
                        try:
                            result["app_name"] = str(name_part.decode("ascii"))
                        except Exception:
                            result["app_name"] = name_part
                result["crc_file_size"] = len(data)
            except Exception as e:
                result["crc_error"] = str(e)[:200]
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass

        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "App CRC error: {0}".format(e)}


def _cmd_app_info():
    """Get detailed information about the application on the PLC.

    Tries to extract: version, build date, checksum, signature, etc.
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        import System
        import System.Reflection

        info = {}

        # 1. Try common properties/methods that might have version info
        for attr in [
            "application_version",
            "version",
            "Version",
            "build",
            "Build",
            "build_version",
            "BuildVersion",
            "application_build",
            "ApplicationBuild",
            "checksum",
            "Checksum",
            "signature",
            "Signature",
            "hash",
            "Hash",
            "application_checksum",
            "ApplicationChecksum",
            "compiled_date",
            "CompiledDate",
            "compile_date",
            "CompileDate",
            "create_time",
            "CreateTime",
            "creation_date",
            "CreationDate",
        ]:
            if hasattr(oa, attr):
                try:
                    val = getattr(oa, attr)
                    if callable(val):
                        val = val()
                    if val is not None:
                        info[attr] = str(val)[:200]
                except Exception:
                    pass

        # 2. Try to get application info through the ScriptOnlineDevice
        online_dev = getattr(oa, "get_online_device", lambda: None)()
        if online_dev is not None:
            dev_info = {}
            for attr in dir(online_dev):
                if not attr.startswith("_"):
                    try:
                        val = getattr(online_dev, attr)
                        if not callable(val) and val is not None:
                            dev_info[attr] = str(val)[:200]
                    except Exception:
                        pass
            if dev_info:
                info["device_properties"] = dev_info

        # 3. Try reflection on oa type for version-related info
        try:
            oa_type = oa.GetType()
            info["oa_type"] = str(oa_type.FullName)
            # Check for assembly version
            try:
                asm = oa_type.Assembly
                if asm:
                    asm_name = asm.GetName()
                    if asm_name:
                        info["assembly_version"] = str(asm_name.Version)
            except Exception:
                pass
        except Exception:
            pass

        # 4. Try to get application state / running info
        for attr in [
            "application_state",
            "operation_state",
            "is_connected",
            "is_running",
            "is_logged_in",
            "timeout",
        ]:
            if hasattr(oa, attr):
                try:
                    val = getattr(oa, attr)
                    if callable(val):
                        val = val()
                    info[attr] = str(val)[:100]
                except Exception:
                    pass

        # 5. Try to get application name from target
        target = getattr(sys._codesys_daemon_loop, "online_target_app", None)
        if target is None:
            target = sys._codesys_daemon_loop.get("online_target_app")
        if target is not None:
            try:
                info["target_name"] = target.get_name()
            except Exception:
                pass

        if not info:
            info["note"] = "No detailed app info available via this API version"

        return {"ok": True, "data": info}
    except Exception as e:
        return {"ok": False, "error": "App info error: {0}".format(e)}


def _append_app_history(crc_data, app_name=""):
    """Append CRC entry to app_history.json in .dump/."""
    try:
        sync_dir, _ = _get_sync_folder()
        if not sync_dir:
            return
        history_path = os.path.join(sync_dir, ".dump", "app_history.json")
        import json as _json

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "crc_hex": crc_data,
            "app_name": app_name,
        }
        try:
            with open(history_path, "r") as f:
                history = _json.load(f)
        except Exception:
            history = []
        history.append(entry)
        history = history[-200:]  # max 200 entries
        history_dir = os.path.dirname(history_path)
        if history_dir and not os.path.exists(history_dir):
            os.makedirs(history_dir)
        with open(history_path, "w") as f:
            _json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log("app_history write error: {0}".format(e))


def _cmd_app_history(params):
    """Log current Application CRC to app_history.json in .dump/.

    Also can read the history.

    Args:
        --read: just read history without adding new entry
    """
    just_read = (
        str(params.get("read", "")).lower() in ("1", "true", "yes") if params else False
    )

    if not just_read:
        # Get current CRC from PLC
        crc_result = _cmd_app_crc(params)
        if not crc_result.get("ok"):
            return crc_result
        data = crc_result.get("data", {})
        crc_hex = data.get("crc_hex", "")
        app_name = data.get("app_name", "")
        if crc_hex:
            _append_app_history(crc_hex, app_name)

    # Read and return history
    try:
        sync_dir, _ = _get_sync_folder()
        if not sync_dir:
            return {
                "ok": True,
                "data": {"note": "No sync folder configured", "history": []},
            }
        history_path = os.path.join(sync_dir, ".dump", "app_history.json")
        import json as _json

        try:
            with open(history_path, "r") as f:
                history = _json.load(f)
        except Exception:
            history = []
        return {
            "ok": True,
            "data": {
                "history": history,
                "count": len(history),
                "last_entry": history[-1] if history else None,
            },
        }
    except Exception as e:
        return {"ok": False, "error": "App history error: {0}".format(e)}


def _cmd_compare_crc(params):
    """Compare IDE project CRC with PLC Application.crc.

    Downloads Application.crc from PLC and tries to find local
    CRC in build output or project directory.

    Args:
        --local PATH: path to local .crc file (default: auto-detect)
    """
    project, err = _get_active_project()
    if err:
        return err
    oa, _target_app, online_err = _ensure_online_app(project)
    if oa is None:
        return {
            "ok": False,
            "error": "Not connected. Call connect_to_device first. {0}".format(
                online_err or ""
            ),
        }

    try:
        online_dev = oa.get_online_device()
        if online_dev is None:
            return {"ok": False, "error": "get_online_device() returned None"}

        result = {}
        app_dir = params.get("app_dir", "PlcLogic/Application")

        # 1. Download PLC CRC
        tmp_plc = tempfile.mktemp(suffix=".crc")
        try:
            online_dev.upload_file(app_dir + "/Application.crc", tmp_plc, True)
            with open(tmp_plc, "rb") as f:
                plc_data = f.read()
            if len(plc_data) >= 8:
                plc_crc = "".join("{:02x}".format(ord(c)) for c in plc_data[:8])
                result["plc_crc"] = plc_crc
            result["plc_file_size"] = len(plc_data)
        except Exception as e:
            result["plc_error"] = str(e)[:200]
            plc_data = None
        finally:
            try:
                os.remove(tmp_plc)
            except Exception:
                pass

        # 2. Try to find local CRC
        local_path = params.get("local", "")
        local_data = None
        if not local_path:
            # Try to find in project directory / build output
            projects = sys._codesys_daemon_loop.get("projects")
            if projects is not None:
                prj = projects.primary
                if prj is not None:
                    for attr in ["filename", "FileName", "FullName", "Path"]:
                        try:
                            val = getattr(prj, attr)
                            if val:
                                project_dir = os.path.dirname(str(val))
                                # Common build output locations
                                candidates = [
                                    os.path.join(project_dir, "Application.crc"),
                                    os.path.join(
                                        project_dir,
                                        "PlcLogic",
                                        "Application",
                                        "Application.crc",
                                    ),
                                    os.path.join(project_dir, "bin", "Application.crc"),
                                    os.path.join(
                                        project_dir, "Debug", "Application.crc"
                                    ),
                                    os.path.join(
                                        project_dir, "Release", "Application.crc"
                                    ),
                                ]
                                for c in candidates:
                                    if os.path.exists(c):
                                        local_path = c
                                        break
                                break
                        except Exception:
                            pass

        if local_path and os.path.exists(local_path):
            try:
                with open(local_path, "rb") as f:
                    local_data = f.read()
                if len(local_data) >= 8:
                    local_crc = "".join("{:02x}".format(ord(c)) for c in local_data[:8])
                    result["local_crc"] = local_crc
                    result["local_path"] = local_path
                    result["local_file_size"] = len(local_data)
                # Compare
                if plc_data and len(plc_data) >= 8 and len(local_data) >= 8:
                    match = plc_data[:8] == local_data[:8]
                    result["match"] = match
                    result["status"] = "MATCH" if match else "MISMATCH"
            except Exception as e:
                result["local_error"] = str(e)[:200]
        else:
            result["local_note"] = "No local .crc file found. Build the project first."

        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Compare CRC error: {0}".format(e)}


def _cmd_permissions():
    """Return current daemon security settings."""
    config = _load_daemon_config()
    return {"ok": True, "data": config}




def _cmd_sync_info():
    """Show sync folder and sync state information."""
    sync_dir, error = _get_sync_folder()
    result = {}
    if sync_dir:
        result["sync_folder"] = sync_dir
        result["dump_folder"] = os.path.join(sync_dir, ".dump")
        # Check if .dump exists
        dump_path = os.path.join(sync_dir, ".dump")
        if os.path.exists(dump_path):
            result["dump_exists"] = True
            try:
                items = os.listdir(dump_path)
                result["dump_items"] = len(items)
            except Exception:
                pass
        else:
            result["dump_exists"] = False
        # Check for _metadata.json
        meta_path = os.path.join(sync_dir, "_metadata.json")
        if os.path.exists(meta_path):
            result["metadata_exists"] = True
    else:
        result["error"] = error
    return {"ok": True, "data": result}


def _cmd_sync_export(params):
    """Export snapshot to sync folder / .dump.

    Args:
        --output PATH: custom output path (default: sync_folder/.dump/)
    """
    project, err = _get_active_project()
    if err:
        return err

    sync_dir, sf_err = _get_sync_folder()
    if sf_err and not params.get("output"):
        return {"ok": False, "error": sf_err}

    try:
        out_path = params.get("output", "")
        if not out_path:
            if sync_dir:
                dump_dir = os.path.join(sync_dir, ".dump")
                if not os.path.exists(dump_dir):
                    os.makedirs(dump_dir)
                out_path = os.path.join(
                    dump_dir, "snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S"))
                )
            else:
                out_path = os.path.join(
                    os.environ.get("TEMP", "C:\\Temp"),
                    "cds-snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S")),
                )

        # Same logic as _cmd_export but with sync folder awareness
        output_dir = os.path.dirname(out_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        objects = list(project.get_children(recursive=True))
        import tempfile as _tf

        fd, tmp_path = _tf.mkstemp(
            prefix="cds_export_", suffix=".xml", dir=output_dir or None
        )
        os.close(fd)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        try:
            project.export_native(objects, tmp_path, recursive=False)
            import shutil

            shutil.copy2(tmp_path, out_path)
            os.remove(tmp_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise
        size = os.path.getsize(out_path)
        _log("Exported snapshot: {0} ({1} bytes)".format(out_path, size))
        return {
            "ok": True,
            "data": {
                "path": out_path,
                "size": size,
                "sync_folder": sync_dir or "not set",
            },
        }
    except Exception as e:
        return {"ok": False, "error": "Sync export error: {0}".format(e)}


def _cmd_sync_import(params):
    """Import XML snapshot from .dump/ back into project.

    Args:
        --input PATH: specific XML file to import (default: latest from sync_folder/.dump/)
        --merge: merge instead of replace
    """
    project, err = _get_active_project()
    if err:
        return err

    in_path = params.get("input", "")
    if not in_path:
        sync_dir, sf_err = _get_sync_folder()
        if sf_err:
            return {"ok": False, "error": sf_err}
        dump_dir = os.path.join(sync_dir, ".dump")
        if not os.path.exists(dump_dir):
            return {"ok": False, "error": "No .dump directory at {0}".format(dump_dir)}
        xml_files = [
            f
            for f in os.listdir(dump_dir)
            if f.endswith(".xml") and f.startswith("snapshot-")
        ]
        if not xml_files:
            return {
                "ok": False,
                "error": "No snapshot XML files found in {0}".format(dump_dir),
            }
        xml_files.sort(reverse=True)
        in_path = os.path.join(dump_dir, xml_files[0])

    if not os.path.exists(in_path):
        return {"ok": False, "error": "File not found: {0}".format(in_path)}

    try:
        size = os.path.getsize(in_path)
        _log("Importing snapshot: {0} ({1} bytes)".format(in_path, size))

        # CODESYS API: project.import_native(path) — single arg only
        project.import_native(in_path)

        return {"ok": True, "data": {"path": in_path, "size": size}}
    except Exception as e:
        return {"ok": False, "error": "Sync import error: {0}".format(e)}


def _cmd_sync_compare(params):
    """Compare current project structure against .dump/ snapshot.

    Args:
        --against PATH: specific snapshot to compare against (default: latest from .dump/)
    """
    project, err = _get_active_project()
    if err:
        return err

    against = params.get("against", "")
    if not against:
        sync_dir, sf_err = _get_sync_folder()
        if sf_err:
            return {"ok": False, "error": sf_err}
        dump_dir = os.path.join(sync_dir, ".dump")
        if not os.path.exists(dump_dir):
            return {"ok": False, "error": "No .dump directory at {0}".format(dump_dir)}
        xml_files = [
            f
            for f in os.listdir(dump_dir)
            if f.endswith(".xml") and f.startswith("snapshot-")
        ]
        if not xml_files:
            return {
                "ok": False,
                "error": "No snapshot XML files found in {0}".format(dump_dir),
            }
        xml_files.sort(reverse=True)
        against = os.path.join(dump_dir, xml_files[0])

    if not os.path.exists(against):
        return {"ok": False, "error": "Snapshot not found: {0}".format(against)}

    try:
        # Compare by checking if import would cause changes:
        # 1. Get current project tree (list of tuples of object info)
        current_children = list(project.get_children(recursive=True))
        current_info = {}
        for child in current_children:
            try:
                name = str(getattr(child, "name", ""))
                typ = str(getattr(child, "type", ""))
                guid = str(getattr(child, "guid", ""))
                current_info[name] = {"name": name, "type": typ, "guid": guid}
            except Exception:
                pass

        # 2. Parse the XML and see what's different (basic check - just names)
        import xml.etree.ElementTree as ET

        tree = ET.parse(against)
        root = tree.getroot()

        xml_names = set()
        for elem in root.iter():
            name = elem.get("name", elem.get("Name", ""))
            if name:
                xml_names.add(name)

        current_names = set(current_info.keys())

        only_in_xml = xml_names - current_names
        only_in_project = current_names - xml_names

        # Build diff report
        diff = {
            "snapshot": against,
            "snapshot_size": os.path.getsize(against),
            "project_objects": len(current_children),
            "snapshot_objects": len(xml_names),
            "in_snapshot_only": sorted(only_in_xml)[:100],
            "in_project_only": sorted(only_in_project)[:100],
            "common_count": len(xml_names & current_names),
        }

        return {"ok": True, "data": diff}
    except Exception as e:
        return {"ok": False, "error": "Sync compare error: {0}".format(e)}


def _cmd_sync_export_text(params):
    # Step 1: Export XML
    export_result = _cmd_sync_export(params)
    if not export_result.get("ok"):
        return export_result

    out_path = export_result["data"]["path"]
    sync_folder = export_result["data"]["sync_folder"]

    # Step 2: Run engine_cli
    args = ["export", "--project-root", sync_folder, "--snapshot", out_path]
    success = _common.run_external_engine(args)
    if not success:
        return {"ok": False, "error": "external engine export failed"}

    export_result["data"]["text_sync"] = "success"
    return export_result




def _cmd_sync_import_text(params):
    import xml.etree.ElementTree as ET

    # Preflight: creating/adding POU/GVL/DUT is an offline operation. If a live
    # online session is active the new objects silently won't be created, so
    # fail early with a clear instruction to disconnect first.
    online, state = _active_app_online_state()
    if online and not params.get("force_online"):
        return {
            "ok": False,
            "error": (
                "Active application is online (state: {0}). Adding/creating "
                "objects is an offline operation. Run disconnect_from_device "
                "first, then retry sync_import_text. "
                "(Pass force_online=true to override.)"
            ).format(state or "connected"),
        }

    # Step 1: Export current IDE state to use as baseline
    export_result = _cmd_sync_export(params)
    if not export_result.get("ok"):
        return export_result

    out_path = export_result["data"]["path"]
    sync_folder = export_result["data"]["sync_folder"]
    patch_path = os.path.join(sync_folder, ".dump", "IMPORT.xml")

    # Step 2: Run engine_cli import to generate IMPORT.xml
    args = [
        "import",
        "--project-root",
        sync_folder,
        "--snapshot",
        out_path,
        "--patch",
        patch_path,
    ]
    success = _common.run_external_engine(args)
    if not success:
        return {"ok": False, "error": "external engine import failed"}

    if not os.path.exists(patch_path):
        return {"ok": False, "error": "IMPORT.xml was not generated"}

    compare_report_path = os.path.join(
        sync_folder, ".dump", "import_compare_report.json"
    )
    compare_args = [
        "compare",
        "--project-root",
        sync_folder,
        "--snapshot",
        out_path,
        "--report",
        compare_report_path,
        "--include-objects",
    ]
    _common.run_external_engine(compare_args)

    # Step 3: Parse IMPORT.xml and process CreateTextObjects
    project, p_err = _get_active_project()
    if p_err:
        return p_err

    try:
        tree = ET.parse(patch_path)
        root = tree.getroot()

        # Find and process CreateTextObjects
        text_creates = []
        for creates_elem in root.iter():
            local_tag = str(creates_elem.tag).rsplit("}", 1)[-1]
            if local_tag == "CreateTextObjects":
                for create_elem in list(creates_elem):
                    local_tag2 = str(create_elem.tag).rsplit("}", 1)[-1]
                    if local_tag2 == "CreateTextObject":
                        path = create_elem.attrib.get("Path", "")
                        name = create_elem.attrib.get("Name", "")
                        kind = create_elem.attrib.get("Kind", "")
                        type_guid = create_elem.attrib.get("TypeGuid", "")
                        parent_name = create_elem.attrib.get("ParentName", "")

                        # Read declaration/implementation from .st file
                        st_path = _find_st_file(sync_folder, path)
                        decl = ""
                        impl = ""
                        if st_path and os.path.exists(st_path):
                            content = _read_text_utf8(st_path)
                            decl, impl = _split_st_content(content)

                        text_creates.append(
                            {
                                "path": path,
                                "name": name,
                                "kind": kind,
                                "type_guid": type_guid,
                                "parent_name": parent_name,
                                "declaration": decl,
                                "implementation": impl,
                                "source_path": st_path,
                            }
                        )

        if text_creates:
            _log("Creating {0} new text objects...".format(len(text_creates)))
            created = {}
            for entry in text_creates:
                try:
                    _apply_text_create_entry(project, entry, created)
                except Exception as e:
                    _log("Failed to create {0}: {1}".format(entry["name"], str(e)))
            _log(
                "Created text objects: {0}".format(
                    ", ".join(e["name"] for e in text_creates)
                )
            )

        # Step 3b: Process CreateNativeObject entries (visualizations, image
        # pools, and other native objects). Unlike text objects, these carry a
        # full IArchivable payload that must be imported into their container.
        # The create+verify logic already exists in ide_apply_patch; reuse it so
        # this handler and apply_patch stay consistent.
        import ide_apply_patch as _iap

        native_creates = _iap._native_create_entries(root)
        created_native = []
        if native_creates:
            _log("Creating {0} new native objects...".format(len(native_creates)))
            for entry in native_creates:
                try:
                    _iap._apply_native_create(project, entry)
                    created_native.append(entry.get("name"))
                except Exception as e:
                    _log(
                        "Failed to create native {0}: {1}".format(
                            entry.get("name"), str(e)
                        )
                    )
                    return {
                        "ok": False,
                        "error": "native object create failed for {0}: {1}".format(
                            entry.get("name"), str(e)
                        ),
                    }
            _log("Created native objects: {0}".format(", ".join(created_native)))

        updated_text = []
        skipped_projection_objects = []
        if os.path.exists(compare_report_path):
            updated_text = _apply_modified_st_objects(project, compare_report_path)
            if updated_text:
                _log("Updated text objects: {0}".format(", ".join(updated_text)))
            # Detect modified objects whose projection changes could not be
            # applied automatically (e.g. non-ST projections).
            try:
                import json as _json

                _report = _json.loads(_read_text_utf8(compare_report_path))
                _updated_names = set(updated_text)
                for obj in (_report.get("objects") or {}).get("modified") or []:
                    _name = obj.get("name") or obj.get("guid") or "?"
                    if _name in _updated_names:
                        continue
                    _pd = obj.get("projection_diff") or {}
                    if _pd.get("format") and _pd.get("disk_content") is not None:
                        skipped_projection_objects.append(
                            {
                                "name": _name,
                                "path": obj.get("path", ""),
                                "format": _pd.get("format", ""),
                                "reason": (
                                    "projection change not applied automatically; "
                                    "use update-pou or edit in the IDE"
                                ),
                            }
                        )
            except Exception:
                pass

        # Step 4: Apply StructuredView (MAIN update) — skip if fails, objects are already created
        try:
            filtered_root = _strip_text_creates(root)
            if filtered_root is not None:
                handle, filtered_path = tempfile.mkstemp(suffix=".xml")
                os.close(handle)
                tree2 = ET.ElementTree(filtered_root)
                tree2.write(filtered_path, encoding="utf-8", xml_declaration=True)
                project.import_native(filtered_path)
                try:
                    os.remove(filtered_path)
                except Exception:
                    pass
        except Exception as e:
            import traceback

            _log(
                "StructuredView import skipped: {0}\n{1}".format(
                    e, traceback.format_exc()
                )
            )

        return_data = {
            "path": patch_path,
            "size": os.path.getsize(patch_path),
            "created_text_objects": [e["name"] for e in text_creates],
            "created_native_objects": created_native,
            "updated_text_objects": updated_text,
            "skipped_projection_objects": skipped_projection_objects,
        }
        if (
            not text_creates
            and not created_native
            and not updated_text
            and not skipped_projection_objects
        ):
            return_data["note"] = (
                "No objects were created, updated, or skipped. "
                "The compare report may show projection-only changes that "
                "cannot be applied automatically; use update-pou or edit "
                "the object in the IDE."
            )

        return {
            "ok": True,
            "data": return_data,
        }
    except Exception as e:
        return {"ok": False, "error": "Sync import error: {0}".format(e)}


def _split_st_update_content(content):
    marker = "// --- implementation ---"
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if marker in normalized:
        parts = normalized.split(marker, 1)
        return parts[0].strip(), parts[1].strip()
    return normalized.strip(), ""


def _replace_text_document(doc, text):
    if doc is None:
        return False
    if hasattr(doc, "text"):
        try:
            doc.text = text
            return True
        except Exception:
            pass
    if hasattr(doc, "replace"):
        doc.replace(text)
        return True
    return False


def _apply_text_to_object(target, decl, impl):
    decl_ok = True
    impl_ok = True
    if decl:
        decl_ok = False
        try:
            decl_ok = _replace_text_document(target.textual_declaration, decl)
        except Exception as e:
            _log("Warning: could not set declaration: {0}".format(e))
    if impl:
        impl_ok = False
        try:
            impl_ok = _replace_text_document(target.textual_implementation, impl)
        except Exception as e:
            _log("Warning: could not set implementation: {0}".format(e))
    return decl_ok, impl_ok


def _apply_modified_st_objects(project, report_path):
    try:
        report = json.loads(_read_text_utf8(report_path))
    except Exception as e:
        _log("Could not read import compare report: {0}".format(e))
        return []

    updated = []
    for obj in (report.get("objects") or {}).get("modified") or []:
        projection_diff = obj.get("projection_diff") or {}
        if str(projection_diff.get("format", "")).lower() != "st":
            continue
        disk_content = projection_diff.get("disk_content")
        if disk_content is None:
            continue
        target = _find_object_by_selector(
            project,
            {
                "guid": obj.get("guid", ""),
                "path": obj.get("path", ""),
                "name": obj.get("name", ""),
            },
        )
        if target is None:
            _log(
                "Could not find modified text object: {0}".format(
                    obj.get("name") or obj.get("guid")
                )
            )
            continue
        decl, impl = _split_st_update_content(disk_content)
        decl_ok, impl_ok = _apply_text_to_object(target, decl, impl)
        if decl_ok and impl_ok:
            updated.append(obj.get("name") or obj.get("guid") or "?")
        else:
            _log(
                "Text update incomplete for {0}: decl={1}, impl={2}".format(
                    obj.get("name") or obj.get("guid"), decl_ok, impl_ok
                )
            )
    return updated


def _find_st_file(sync_folder, rel_path):
    """Find the .st source file for a CreateTextObject entry."""
    views_path = os.path.join(sync_folder, "project-view")
    candidate = os.path.join(views_path, rel_path)
    if os.path.exists(candidate):
        return candidate
    # Try alternate paths
    base = os.path.basename(rel_path)
    for root, dirs, files in os.walk(views_path):
        if base in files:
            return os.path.join(root, base)
    return None


def _split_st_content(content):
    """Split .st content into declaration and implementation.

    Strips END_FUNCTION_BLOCK / END_FUNCTION / END_PROGRAM from implementation
    as CODESYS API auto-adds these.
    """
    marker = "// --- implementation ---"
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if marker in normalized:
        parts = normalized.split(marker, 1)
        decl = parts[0].strip()
        impl = parts[1].strip()
        # Strip trailing END_* keywords (CODESYS API auto-adds them)
        for end_kw in ["END_FUNCTION_BLOCK", "END_FUNCTION", "END_PROGRAM"]:
            if impl.rstrip().endswith(end_kw):
                impl = impl.rstrip()[: -len(end_kw)].rstrip()
                break
        return decl, impl
    return normalized.strip(), ""


def _strip_text_creates(root):
    """Remove create-only wrappers (CreateTextObjects / CreateNativeObjects)
    from the XML root.

    These are applied separately (text via _apply_text_create_entry, native via
    ide_apply_patch._apply_native_create) and must not be fed to the Step 4
    project.import_native pass: import_native ignores the CreateNativeObjects
    wrapper anyway, but stripping it keeps the StructuredView payload clean and
    avoids any double processing."""
    import copy

    filtered = copy.deepcopy(root)
    for child in list(filtered):
        local_tag = str(child.tag).rsplit("}", 1)[-1]
        if local_tag in ("CreateTextObjects", "CreateNativeObjects"):
            filtered.remove(child)
    if len(list(filtered)) == 0:
        return None
    return filtered


def _apply_text_create_entry(project, entry, created_by_name):
    """Create a single text object (POU, GVL, DUT) from a CreateTextObject entry."""
    import ide_apply_patch as _iap

    # Add source_path to entry for ide_apply_patch compatibility
    rel_path = entry["path"]
    container, container_chain = _iap._ensure_container_path_with_chain(
        project, rel_path
    )
    if container is None:
        raise Exception("Could not resolve container for {0}".format(rel_path))

    parent_name = entry.get("parent_name", "")
    if parent_name:
        parent = created_by_name.get(str(parent_name).lower())
        if parent is None:
            parent = _iap._find_child_transparent(container, parent_name)
        if parent is None:
            raise Exception(
                "Could not resolve parent POU '{0}' for {1}".format(
                    parent_name, rel_path
                )
            )
        container = parent

    obj_name = entry["name"]
    existing = _iap._find_child_transparent(container, obj_name)
    if existing is not None:
        obj = existing
    else:
        obj = _iap._create_text_object(
            container, entry, container_chain=container_chain
        )

    if obj is None:
        raise Exception(
            "CODESYS did not return created object for {0}".format(rel_path)
        )

    _iap._apply_textual_patch(obj, entry)
    created_by_name[_iap.object_name(obj).lower()] = obj
    _log("Created textual object: {0}".format(rel_path))


def _cmd_sync_compare_text(params):
    # Step 1: Export current IDE state
    export_result = _cmd_sync_export(params)
    if not export_result.get("ok"):
        return export_result

    out_path = export_result["data"]["path"]
    sync_folder = export_result["data"]["sync_folder"]
    report_path = os.path.join(sync_folder, ".dump", "compare_report.json")

    # Step 2: Run engine_cli compare
    args = [
        "compare",
        "--project-root",
        sync_folder,
        "--snapshot",
        out_path,
        "--report",
        report_path,
        "--include-objects",
    ]
    success = _common.run_external_engine(args)
    if not success:
        return {"ok": False, "error": "external engine compare failed"}

    if not os.path.exists(report_path):
        return {"ok": False, "error": "compare_report.json was not generated"}

    # Step 3: Read and return report
    try:
        report_data = json.loads(_read_text_utf8(report_path))
        return {"ok": True, "data": report_data}
    except Exception as e:
        return {"ok": False, "error": "failed to read report: " + str(e)}


def _cmd_update_pou(params):
    """Update a POU's textual declaration and implementation from a .st file.

    Args:
        name: POU name (e.g. "MAIN")
        app: Application name (e.g. "Application (from profile)")
        st_path: path to .st file (absolute or relative to project-view)
    """
    project, err = _get_active_project()
    if err:
        return err

    pou_name = params.get("name", "")
    app_name = params.get("app") or _active_application_name(project)
    st_path = params.get("st_path", "")

    if not pou_name or not st_path:
        return {"ok": False, "error": "name and st_path are required"}

    # Resolve st_path
    if not os.path.isabs(st_path):
        sf, sf_err = _get_sync_folder()
        if sf_err or not sf:
            return {
                "ok": False,
                "error": "Cannot resolve sync folder: {0}".format(sf_err or "unknown"),
            }
        st_path = os.path.join(sf, "project-view", st_path)

    if not os.path.exists(st_path):
        return {"ok": False, "error": "File not found: {0}".format(st_path)}

    # Read .st file
    content = _read_text_utf8(st_path)

    # Split into declaration and implementation
    marker = "// --- implementation ---"
    decl = content
    impl = ""
    if marker in content:
        parts = content.split(marker, 1)
        decl = parts[0].strip()
        impl = parts[1].strip()

    # Find the POU object in the project tree
    target, _target_type = _find_object_in_project(project, pou_name, app_name)

    if target is None:
        scope = app_name or "project"
        return {
            "ok": False,
            "error": "POU '{0}' not found in application '{1}'".format(pou_name, scope),
        }

    # Update declaration
    decl_ok = False
    impl_ok = False
    decl_skipped = None
    impl_skipped = None
    if decl:
        try:
            dd = target.textual_declaration
            if dd is not None:
                if hasattr(dd, "text"):
                    try:
                        dd.text = decl
                        decl_ok = True
                    except Exception:
                        dd.replace(decl)
                        decl_ok = True
                elif hasattr(dd, "replace"):
                    dd.replace(decl)
                    decl_ok = True
            else:
                _log("Warning: textual_declaration not available")
        except Exception as e:
            _log("Warning: could not set declaration: {0}".format(e))
    else:
        # Nothing to apply is success, not a failure.
        decl_ok = True
        decl_skipped = "no declaration text in .st"

    # Update implementation
    if impl:
        try:
            di = target.textual_implementation
            if di is not None:
                if hasattr(di, "text"):
                    try:
                        di.text = impl
                        impl_ok = True
                    except Exception:
                        di.replace(impl)
                        impl_ok = True
                elif hasattr(di, "replace"):
                    di.replace(impl)
                    impl_ok = True
            else:
                # Object has no implementation member (GVL/DUT/interface). The
                # .st carries implementation text but it cannot be applied.
                impl_skipped = "object has no implementation section"
                _log("Warning: textual_implementation not available")
        except Exception as e:
            _log("Warning: could not set implementation: {0}".format(e))
    else:
        # No implementation in the .st (e.g. GVL/DUT/interface). Nothing to
        # apply -> success with a note, instead of a scary impl_ok:false.
        impl_ok = True
        impl_skipped = "no implementation section in .st"

    _log(
        "Updated POU: {0} (app={1}, decl={2}, impl={3})".format(
            pou_name, app_name, decl_ok, impl_ok
        )
    )
    result = {
        "ok": True,
        "data": {
            "name": pou_name,
            "app": app_name,
            "decl_ok": decl_ok,
            "impl_ok": impl_ok,
            "decl_len": len(decl),
            "impl_len": len(impl),
        },
    }
    if decl_skipped:
        result["data"]["decl_skipped"] = decl_skipped
    if impl_skipped:
        result["data"]["impl_skipped"] = impl_skipped
    return result


def _cmd_delete_pou(params):
    """Delete an object from the project (POU, GVL, DUT, etc).

    Args:
        name: Object name (e.g. "MAIN", "Globals", "MyDataType")
        app: Optional application name. Defaults to the active application.
    """
    project, err = _get_active_project()
    if err:
        return err

    obj_name = params.get("name", "")
    app_name = params.get("app") or _active_application_name(project)

    if not obj_name:
        return {"ok": False, "error": "name is required"}

    # Find the object in the project tree
    target, target_type = _find_object_in_project(project, obj_name, app_name)

    if target is None:
        scope = app_name or "project"
        return {
            "ok": False,
            "error": "Object '{0}' not found in application '{1}'".format(
                obj_name, scope
            ),
        }

    # Try to delete the object using remove() method
    try:
        if hasattr(target, "remove"):
            target.remove()
            _invalidate_device_cache()
            _log(
                "Deleted object: {0} (type={1}, app={2})".format(
                    obj_name, target_type, app_name
                )
            )
            return {
                "ok": True,
                "data": {
                    "name": obj_name,
                    "type": target_type,
                    "deleted": True,
                    "note": "Object deleted successfully",
                },
            }
        else:
            msg = "Object type '{0}' does not support remove() method".format(
                target_type
            )
            _log("Error: {0}".format(msg))
            return {"ok": False, "error": msg}
    except Exception as e:
        msg = "Failed to delete '{0}': {1}".format(obj_name, str(e))
        _log("Error deleting object: {0}".format(e))
        return {"ok": False, "error": msg}


def _parse_codesys_value(raw):
    """Parse CODESYS value string like 'REAL#13.0', 'INT#5', 'BOOL#TRUE' into Python type."""
    if not raw:
        return raw
    s = str(raw).strip()
    if "#" in s:
        prefix, val = s.split("#", 1)
        prefix = prefix.upper()
        if prefix in (
            "REAL",
            "LREAL",
            "INT",
            "DINT",
            "UINT",
            "UDINT",
            "SINT",
            "USINT",
            "BYTE",
            "WORD",
            "DWORD",
        ):
            try:
                return float(val) if "." in val else int(val)
            except ValueError:
                return val
        if prefix == "BOOL":
            return val.upper() == "TRUE"
        if prefix == "STRING":
            return val
    # Try numeric
    try:
        return (
            int(s)
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit())
            else float(s)
        )
    except ValueError:
        pass
    return s


def _cicd_cold_reset(project, ip_address="", gateway_name="Gateway-1"):
    """Perform full cold reset cycle for CI/CD: stop PLC → cold reset → reconnect → build → start."""
    import time as _time

    _log("CICD: Cold reset sequence started")

    # 1. Stop PLC
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is not None and hasattr(oa, "stop"):
            _log("CICD: Stopping PLC")
            oa.stop()
            _time.sleep(0.3)
    except Exception as e:
        _log("CICD: Stop PLC (non-fatal): {0}".format(e))

    # 2. Cold reset via existing command
    _log("CICD: Performing cold reset")
    reset_result = _cmd_reset_plc({"kind": "cold"})
    if not reset_result.get("ok"):
        raise RuntimeError(
            "CICD cold reset failed: {0}".format(reset_result.get("error", ""))
        )

    _time.sleep(0.5)

    # 3. Clear cached online_app
    sys._codesys_daemon_loop["online_app"] = None
    sys._codesys_daemon_loop["online_target_app"] = None
    _invalidate_device_cache()

    # 4. Re-connect (creates fresh online_app, logs in)
    _log("CICD: Reconnecting after cold reset")
    from ide_online_helpers import connect_to_device_impl

    connect_to_device_impl(project, ip_address, gateway_name)

    _time.sleep(0.3)

    # 5. Build → online change (re-download application to PLC)
    _log("CICD: Building after cold reset")
    build_result = _cmd_build({})
    if not build_result.get("ok"):
        _log("CICD: Build warning: {0}".format(build_result.get("error", "")))

    # 6. Start PLC
    _log("CICD: Starting PLC after cold reset")
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is not None and hasattr(oa, "start"):
            oa.start()
    except Exception as e:
        _log("CICD: Start PLC (non-fatal): {0}".format(e))

    _log("CICD: Cold reset complete")


def _cmd_cicd(params):
    """Execute CI/CD test plan.

    Args:
        file: path to test JSON file (relative to sync_folder/.test/ or absolute)
    """
    import time as _time

    import ide_online_helpers as _helpers

    project, err = _get_active_project()
    if err:
        return err

    # Resolve file path
    file_path = params.get("file", "")
    sf, sf_err = _get_sync_folder()
    if sf_err:
        return {"ok": False, "error": sf_err}

    if not file_path:
        # No file specified: run all tests from .test/ by default.
        test_dir = os.path.join(sf, ".test")
        if not os.path.isdir(test_dir):
            legacy_test_dir = os.path.join(sf, "test")
            if os.path.isdir(legacy_test_dir):
                test_dir = legacy_test_dir
        if not os.path.isdir(test_dir):
            return {
                "ok": False,
                "error": (
                    "No .test/ directory found at {0}. "
                    "Create JSON test plans in <sync-folder>/.test/ "
                    "and run 'cts test --file plan.json'. "
                    "Format documentation: cli/TEST_FORMAT.md"
                ).format(test_dir),
            }
        json_files = sorted([f for f in os.listdir(test_dir) if f.endswith(".json")])
        if not json_files:
            return {"ok": False, "error": "No JSON files found in {0}".format(test_dir)}
        # Cold reset once before running all tests — handled by first plan via _prepare_cicd_plan
        sys._codesys_daemon_loop["cicd_reset_done"] = False

        results = []
        for jf in json_files:
            fp = os.path.join(test_dir, jf)
            plan = {}
            try:
                plan = json.loads(_read_text_utf8(fp))
            except Exception as e:
                results.append({"file": jf, "status": "FAIL", "error": str(e)})
                continue
            result = _run_test_plan(project, plan)
            result["file"] = jf
            results.append(result)
        return {"ok": True, "data": _summarize_cicd_results(results)}

    if not os.path.isabs(file_path):
        test_dir = os.path.join(sf, ".test")
        candidate = os.path.join(test_dir, file_path)
        if not os.path.exists(candidate):
            legacy_candidate = os.path.join(sf, "test", file_path)
            if os.path.exists(legacy_candidate):
                candidate = legacy_candidate
        file_path = candidate

    if not os.path.exists(file_path):
        return {"ok": False, "error": "Test file not found: {0}".format(file_path)}

    # Read and execute
    try:
        plan = json.loads(_read_text_utf8(file_path))
    except Exception as e:
        return {"ok": False, "error": "Failed to parse test file: {0}".format(e)}

    result = _run_test_plan(project, plan)
    result["file"] = os.path.basename(file_path)
    return {"ok": True, "data": _summarize_cicd_results([result])}


def _get_application_name(app):
    """Return a readable CODESYS application name."""
    if app is None:
        return ""
    for attr in ("get_name", "Name", "name"):
        try:
            value = getattr(app, attr)
            if callable(value):
                value = value()
            if value:
                return str(value)
        except Exception:
            pass
    return ""


def _find_application_by_name(project, name):
    """Find an application object by exact name in the active project."""
    if not name:
        return None
    try:
        app = project.active_application
        if app is not None and _get_application_name(app) == name:
            return app
    except Exception:
        pass
    try:
        for child in project.get_children(True):
            try:
                if hasattr(child, "is_application") and child.is_application:
                    if _get_application_name(child) == name:
                        return child
            except Exception:
                pass
    except Exception:
        pass
    return None


def _prepare_cicd_plan(project, plan):
    """Validate the plan target and prepare the online application."""
    application = str(plan.get("application", "") or "").strip()
    if not application:
        raise RuntimeError(
            'Test plan must specify the target application: {"application": "Application"}'
        )

    target_app = _find_application_by_name(project, application)
    if target_app is None:
        raise RuntimeError(
            "Application '{0}' not found in the active project".format(application)
        )

    active_name = ""
    try:
        active_name = _get_application_name(project.active_application)
    except Exception:
        pass
    if active_name and active_name != application:
        try:
            project.active_application = target_app
            sys._codesys_daemon_loop["online_app"] = None
            sys._codesys_daemon_loop["online_target_app"] = None
            active_name = application
        except Exception as e:
            raise RuntimeError(
                "Test plan targets application '{0}', but active application is '{1}'. "
                "Automatic switch failed: {2}".format(application, active_name, e)
            )

    ip_address = str(plan.get("ip", "") or plan.get("device_ip", "") or "").strip()
    gateway_name = str(
        plan.get("gateway", "") or plan.get("gateway_name", "Gateway-1") or "Gateway-1"
    ).strip()
    connect_result = _helpers.connect_to_device_impl(project, ip_address, gateway_name)

    # Cold reset if requested by plan (and not already done by bulk runner)
    if plan.get("reset") == "cold" and not sys._codesys_daemon_loop.get(
        "cicd_reset_done"
    ):
        _cicd_cold_reset(project, ip_address, gateway_name)
        sys._codesys_daemon_loop["cicd_reset_done"] = True

    if plan.get("start", True):
        start_result = _cmd_start_plc()
        if not start_result.get("ok"):
            start_error = start_result.get("error", "Failed to start PLC application")
            if (
                "state is run" not in str(start_error).lower()
                and "already" not in str(start_error).lower()
            ):
                raise RuntimeError(start_error)

    return {
        "application": application,
        "device": connect_result.get("device", ""),
        "state": connect_result.get("state", ""),
    }


def _summarize_cicd_results(results):
    """Return detailed results plus a compact machine/human summary."""
    passed = 0
    failed = 0
    total_tests = 0
    files = []
    for result in results:
        status = result.get("status", "FAIL")
        tests = result.get("tests", [])
        ok_tests = sum(1 for t in tests if t.get("status") == "PASS")
        bad_tests = sum(1 for t in tests if t.get("status") == "FAIL")
        if tests:
            passed += ok_tests
            failed += bad_tests
            total_tests += len(tests)
        else:
            total_tests += 1
            if status == "PASS":
                passed += 1
            else:
                failed += 1
        files.append(
            {
                "file": result.get("file", ""),
                "plan": result.get("plan", ""),
                "status": "SUCCESS" if status == "PASS" else "FAIL",
                "ok": status == "PASS",
                "tests_ok": ok_tests,
                "tests_failed": bad_tests,
                "error": result.get("error", ""),
                "total_ms": result.get("total_ms", 0),
            }
        )
    return {
        "status": "SUCCESS" if failed == 0 else "FAIL",
        "ok": failed == 0,
        "summary": {
            "ok": passed,
            "not_ok": failed,
            "total": total_tests,
            "files": len(results),
        },
        "files": files,
        "results": results,
    }


def _run_test_plan(project, plan):
    """Execute a single test plan and return results."""
    import time as _time

    import ide_online_helpers as _helpers

    plan_name = plan.get("name", "unnamed")
    plan_timeout = plan.get("timeout", 30000) / 1000.0  # convert to seconds
    plan_continue_on_fail = plan.get("continue_on_fail", False)
    tests = plan.get("tests", [])
    prepare_info = None

    start_all = _time.time()
    results = {
        "plan": plan_name,
        "application": str(plan.get("application", "") or ""),
        "status": "PASS",
        "total_ms": 0,
        "tests": [],
    }

    if not tests:
        results["status"] = "FAIL"
        results["error"] = "Test plan contains no tests"
        results["total_ms"] = int((_time.time() - start_all) * 1000)
        return results

    try:
        prepare_info = _prepare_cicd_plan(project, plan)
        results["prepare"] = prepare_info
    except Exception as e:
        results["status"] = "FAIL"
        results["error"] = str(e)
        results["total_ms"] = int((_time.time() - start_all) * 1000)
        return results

    for test in tests:
        test_name = test.get("name", "unnamed")
        test_timeout = test.get("timeout", plan_timeout * 1000) / 1000.0
        steps = test.get("steps", [])
        continue_on_fail = test.get("continue_on_fail", False)

        test_start = _time.time()
        test_result = {
            "name": test_name,
            "status": "PASS",
            "ms": 0,
            "steps": [],
        }

        test_failed = False
        for i, step in enumerate(steps):
            action = step.get("action", "")
            step_start = _time.time()

            # Check overall timeout
            if _time.time() - start_all > plan_timeout:
                step_result = {
                    "action": action,
                    "status": "FAIL",
                    "ms": 0,
                    "error": "Plan timeout exceeded",
                }
                test_result["steps"].append(step_result)
                test_failed = True
                break

            step_result = {"action": action}

            try:
                if action == "write":
                    var_name = step.get("variable", "")
                    value = step.get("value")
                    if not var_name:
                        raise Exception("write: variable name is required")
                    # Convert value to string (CODESYS online API expects str)
                    if isinstance(value, bool):
                        value_str = "TRUE" if value else "FALSE"
                    elif isinstance(value, float):
                        value_str = str(value)
                    elif isinstance(value, int):
                        value_str = str(value)
                    else:
                        value_str = str(value)
                    _helpers.write_variable_impl(project, var_name, value_str)
                    _log("cicd write {0} = {1}".format(var_name, value_str))

                elif action == "wait":
                    ms = int(step.get("ms", 100))
                    _time.sleep(ms / 1000.0)

                elif action == "read":
                    var_name = step.get("variable", "")
                    if not var_name:
                        raise Exception("read: variable name is required")
                    result = _helpers.read_variable_impl(project, var_name)
                    step_result["value"] = result
                    _log("cicd read {0} = {1}".format(var_name, result))

                    # Extract actual value from read result
                    raw_value = (
                        result.get("value", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    # Parse CODESYS format: "REAL#13.0", "INT#5", "BOOL#TRUE"
                    parsed = _parse_codesys_value(raw_value)
                    step_result["parsed"] = parsed

                    # Check expected value
                    expected = step.get("expected")
                    tolerance = float(step.get("tolerance", 0))
                    expected_min = step.get("expected_min")
                    expected_max = step.get("expected_max")

                    if expected is not None:
                        if isinstance(parsed, (int, float)) and isinstance(
                            expected, (int, float)
                        ):
                            if abs(float(parsed) - float(expected)) > tolerance:
                                raise Exception(
                                    "read {0}: expected {1}±{2}, got {3} (raw={4})".format(
                                        var_name, expected, tolerance, parsed, raw_value
                                    )
                                )
                        elif isinstance(parsed, bool) and isinstance(expected, bool):
                            if parsed != expected:
                                raise Exception(
                                    "read {0}: expected {1}, got {2}".format(
                                        var_name, expected, parsed
                                    )
                                )
                        elif str(parsed).lower() != str(expected).lower():
                            raise Exception(
                                "read {0}: expected {1}, got {2}".format(
                                    var_name, expected, parsed
                                )
                            )

                    if expected_min is not None and float(parsed) < float(expected_min):
                        raise Exception(
                            "read {0}: min {1}, got {2}".format(
                                var_name, expected_min, parsed
                            )
                        )
                    if expected_max is not None and float(parsed) > float(expected_max):
                        raise Exception(
                            "read {0}: max {1}, got {2}".format(
                                var_name, expected_max, parsed
                            )
                        )

                elif action == "assert":
                    var_name = step.get("variable", "")
                    if not var_name:
                        raise Exception("assert: variable name is required")
                    result = _helpers.read_variable_impl(project, var_name)
                    raw_value = (
                        result.get("value", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    parsed = _parse_codesys_value(raw_value)
                    expected = step.get("expected")
                    if expected is not None:
                        # Compare as native types
                        if isinstance(expected, bool) and isinstance(parsed, bool):
                            if parsed != expected:
                                raise Exception(
                                    "assert {0}: expected {1}, got {2}".format(
                                        var_name, expected, parsed
                                    )
                                )
                        elif str(parsed).lower() != str(expected).lower():
                            raise Exception(
                                "assert {0}: expected {1}, got {2}".format(
                                    var_name, expected, parsed
                                )
                            )

                else:
                    raise Exception("Unknown action: {0}".format(action))

                step_result["status"] = "PASS"

            except Exception as e:
                step_result["status"] = "FAIL"
                step_result["error"] = str(e)
                test_failed = True
                if not continue_on_fail:
                    test_result["steps"].append(step_result)
                    test_result["ms"] = int((_time.time() - test_start) * 1000)
                    test_result["status"] = "FAIL"
                    test_result["error"] = str(e)
                    break

            step_result["ms"] = int((_time.time() - step_start) * 1000)
            test_result["steps"].append(step_result)

        test_result["ms"] = int((_time.time() - test_start) * 1000)
        if test_failed and "error" not in test_result:
            test_result["status"] = "FAIL"
        results["tests"].append(test_result)

        if test_failed and not continue_on_fail and not plan_continue_on_fail:
            break

    overall_fail = any(t["status"] == "FAIL" for t in results["tests"])
    results["status"] = "FAIL" if overall_fail else "PASS"
    results["total_ms"] = int((_time.time() - start_all) * 1000)
    return results


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
