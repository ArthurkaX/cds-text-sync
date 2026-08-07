# -*- coding: utf-8 -*-
"""
ide_handlers_crc.py -- CRC / APP-INFO command handlers for ide_reverse_pipe_loop.py.

Contains handlers for application CRC, app info, app history, CRC comparison,
and daemon security permissions.
All CODESYS API calls happen via sys._codesys_daemon_loop (set by capture_codesys_globals).
"""

from __future__ import print_function

import os
import sys
import tempfile
import time

from ide_daemon_state import (
    _log,
    _get_active_project,
    _load_daemon_config,
    _project_file_path,
)

from ide_daemon_helpers import (
    _ensure_online_app,
    _get_sync_folder,
)


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
                except Exception as error:
                    _log("Could not inspect PLC CRC directory: {0}".format(error))

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
                    except Exception as error:
                        _log("Could not decode PLC CRC value: {0}".format(error))
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
                except Exception as error:
                    _log("Could not remove temporary PLC CRC file: {0}".format(error))

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
            except Exception as error:
                _log("Could not remove temporary CRC comparison file: {0}".format(error))
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
                    val = _project_file_path(prj)
                    if val:
                        project_dir = os.path.dirname(val)
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
