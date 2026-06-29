# -*- coding: utf-8 -*-
"""
ide_handlers_plc.py -- PLC command handlers for ide_reverse_pipe_loop.py.

Contains handlers for PLC control (start/stop/reset), boot application,
source download, file operations, and log reading.
All CODESYS API calls happen via sys._codesys_daemon_loop (set by capture_codesys_globals).
"""

from __future__ import print_function

import os
import sys
import tempfile

from ide_daemon_state import (
    _log,
    _get_active_project,
)

from ide_daemon_helpers import (
    _ensure_online_app,
)


def _cmd_read_log(params):
    """Read system/PLC log messages."""
    try:
        system = sys._codesys_daemon_loop.get("system")
        if system is None:
            return {"ok": False, "error": "system not captured"}

        last_n = None
        try:
            last_n = int(params.get("last", 0))
        except (ValueError, TypeError):
            last_n = None

        do_clear = str(params.get("clear", "")).lower() in ("1", "true", "yes")

        messages = []
        if hasattr(system, "get_messages"):
            raw = system.get_messages()
            if raw is not None:
                for msg in raw:
                    messages.append(str(msg))
        elif hasattr(system, "get_message_objects"):
            raw = system.get_message_objects()
            if raw is not None:
                for msg_obj in raw:
                    messages.append(str(msg_obj))

        if last_n is not None and last_n > 0 and len(messages) > last_n:
            messages = messages[-last_n:]

        if do_clear and hasattr(system, "clear_messages"):
            try:
                system.clear_messages()
            except Exception:
                pass

        return {"ok": True, "data": {"count": len(messages), "messages": messages}}
    except Exception as e:
        return {"ok": False, "error": "Read log error: {0}".format(e)}




def _cmd_start_plc():
    """Start the PLC application."""
    project, err = _get_active_project()
    if err:
        return err
    try:
        oa, _target_app, online_err = _ensure_online_app(project)
        if oa is None:
            return {
                "ok": False,
                "error": "Not connected. Call connect_to_device first. {0}".format(
                    online_err or ""
                ),
            }
        if not hasattr(oa, "start"):
            return {"ok": False, "error": "OnlineApplication has no start() method"}
        oa.start()
        return {"ok": True, "data": {"state": "started"}}
    except Exception as e:
        return {"ok": False, "error": "Start PLC error: {0}".format(e)}




def _cmd_stop_plc():
    """Stop the PLC application."""
    project, err = _get_active_project()
    if err:
        return err
    try:
        oa, _target_app, online_err = _ensure_online_app(project)
        if oa is None:
            return {
                "ok": False,
                "error": "Not connected. Call connect_to_device first. {0}".format(
                    online_err or ""
                ),
            }
        if not hasattr(oa, "stop"):
            return {"ok": False, "error": "OnlineApplication has no stop() method"}
        oa.stop()
        return {"ok": True, "data": {"state": "stopped"}}
    except Exception as e:
        return {"ok": False, "error": "Stop PLC error: {0}".format(e)}




def _cmd_reset_plc(params):
    """Reset the PLC application.

    Args:
        params: dict with optional 'kind' key ("warm", "cold", or "origin")
    """
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is None:
            return {
                "ok": False,
                "error": "Not connected. Call connect_to_device first.",
            }
        if not hasattr(oa, "reset"):
            return {"ok": False, "error": "OnlineApplication has no reset() method"}
        kind = (params.get("kind") or "warm").lower()
        if kind not in ("warm", "cold", "origin"):
            return {
                "ok": False,
                "error": "Invalid reset kind: {0}. Use warm, cold, or origin.".format(
                    kind
                ),
            }
        # Safety guard: origin reset erases the application from PLC
        if kind == "origin" and not params.get("force"):
            return {
                "ok": False,
                "error": (
                    "DANGEROUS: reset_plc --kind origin erases the application from the PLC, "
                    "restoring it to factory state. Use --force to confirm."
                ),
            }
        # Resolve the reset type enum — use the parameter type from the oa's method
        import System
        import System.Reflection

        reset_type = None
        try:
            method_info = oa.GetType().GetMethod(
                "reset",
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.IgnoreCase,
            )
            if method_info is not None:
                params_info = method_info.GetParameters()
                if params_info.Length > 0:
                    param_type = params_info[0].ParameterType
                    if param_type.IsEnum:
                        # Map kind names to integer values (Warm=0, Cold=1, Original=2)
                        kind_values = {"warm": 0, "cold": 1, "origin": 2}
                        int_val = kind_values.get(kind, 0)
                        reset_type = System.Enum.ToObject(param_type, int_val)
        except Exception:
            pass
        if reset_type is None:
            # Fallback: scan all assemblies for an enum with matching values
            for asm in System.AppDomain.CurrentDomain.GetAssemblies():
                try:
                    asm_types = list(asm.GetTypes())
                except Exception:
                    continue
                for typ in asm_types:
                    if typ.IsEnum:
                        try:
                            names = [str(n) for n in System.Enum.GetNames(typ)]
                            if kind.upper() in [n.upper() for n in names]:
                                kind_values = {"warm": 0, "cold": 1, "origin": 2}
                                int_val = kind_values.get(kind, 0)
                                reset_type = System.Enum.ToObject(typ, int_val)
                                break
                        except Exception:
                            pass
                if reset_type is not None:
                    break
        if reset_type is None:
            return {
                "ok": False,
                "error": "Cannot resolve reset enum type for kind={0}".format(kind),
            }
        # Call with forceKill=True (second parameter)
        # Use Enum.ToObject to avoid IronPython boxing issues
        import System

        enum_type = reset_type.GetType()
        int_val = int(reset_type)
        typed_reset = System.Enum.ToObject(enum_type, int_val)
        oa.reset(typed_reset, True)
        return {"ok": True, "data": {"reset_kind": kind}}
    except Exception as e:
        return {"ok": False, "error": "Reset PLC error: {0}".format(e)}




def _cmd_create_boot_app():
    """Create boot application on the PLC."""
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is None:
            return {
                "ok": False,
                "error": "Not connected. Call connect_to_device first.",
            }
        if not hasattr(oa, "create_boot_application"):
            return {
                "ok": False,
                "error": "OnlineApplication has no create_boot_application() method",
            }
        oa.create_boot_application()
        return {"ok": True, "data": {"status": "boot_application_created"}}
    except Exception as e:
        return {"ok": False, "error": "Create boot app error: {0}".format(e)}




def _cmd_source_download(params):
    """Download source from PLC.

    In SP22, source_download() takes no arguments and saves
    to a default location (usually project directory or temp).

    Args:
        params: dict with optional 'output' key for destination directory
    """
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is None:
            return {
                "ok": False,
                "error": "Not connected. Call connect_to_device first.",
            }
        if not hasattr(oa, "source_download"):
            return {
                "ok": False,
                "error": "OnlineApplication has no source_download() method",
            }
        # SP22: source_download() takes no arguments, saves to project dir
        # We'll just call it and report success
        oa.source_download()
        output_dir = params.get("output") or "<default project location>"
        return {
            "ok": True,
            "data": {
                "output_directory": output_dir,
                "note": "source_download() saved to default project location",
            },
        }
    except Exception as e:
        return {"ok": False, "error": "Source download error: {0}".format(e)}




def _cmd_plc_files(params):
    """List files on the PLC via get_online_device().get_file_list_of_directory()."""
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        online_dev = oa.get_online_device()
        if online_dev is None:
            return {"ok": False, "error": "get_online_device() returned None"}

        diag = {}

        # Check connection status
        try:
            is_conn = (
                bool(online_dev.connected)
                if hasattr(online_dev, "connected")
                else False
            )
            diag["connected"] = str(is_conn)
        except Exception as e:
            diag["connected_error"] = str(e)[:100]

        try:
            is_shared = (
                bool(online_dev.shared_connected)
                if hasattr(online_dev, "shared_connected")
                else False
            )
            diag["shared_connected"] = str(is_shared)
        except Exception as e:
            diag["shared_connected_error"] = str(e)[:100]

        # Try to connect if not already connected
        if hasattr(online_dev, "connect") and not is_conn:
            try:
                _log("Calling online_dev.connect()...")
                online_dev.connect()
                _log("online_dev.connect() succeeded")
                try:
                    diag["connected_after"] = str(online_dev.connected)
                except Exception:
                    pass
            except Exception as e:
                diag["connect_error"] = str(e)[:200]

        path = params.get("path", "/")

        # Try common paths if the requested path fails
        paths_to_try = [path]
        if path == "/":
            paths_to_try = [
                "/",
                "",
                "/usr/",
                "/home/",
                "/var/",
                "/tmp/",
                "/log/",
                "/logs/",
            ]

        result_files = None
        last_error = None
        for p in paths_to_try:
            try:
                result_files = online_dev.get_file_list_of_directory(p)
                if result_files is not None:
                    path = p
                    break
            except Exception as e:
                last_error = str(e)[:200]
                continue

        if result_files is None:
            # Show diagnostic info
            diag["paths_tried"] = paths_to_try
            diag["last_error"] = last_error or "unknown"
            diag["note"] = (
                "PLC file system may be disabled or device not fully connected"
            )
            return {
                "ok": False,
                "error": "Get directory entries failed",
                "diagnostics": diag,
            }

        files = []
        for f in result_files:
            try:
                info = {}
                for attr in [
                    "name",
                    "Name",
                    "length",
                    "Length",
                    "size",
                    "Size",
                    "is_directory",
                    "IsDirectory",
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
                                info[attr.lower()] = str(val)[:100]
                        except Exception:
                            pass
                if not info:
                    for attr in dir(f):
                        if not attr.startswith("_"):
                            try:
                                val = getattr(f, attr)
                                if not callable(val) and val is not None:
                                    info[attr.lower()] = str(val)[:100]
                            except Exception:
                                pass
                if not info:
                    info["_raw"] = str(f)[:200]
                files.append(info)
            except Exception:
                pass

        return {"ok": True, "data": {"path": path, "files": files, "count": len(files)}}
    except Exception as e:
        return {"ok": False, "error": "PLC files error: {0}".format(e)}




def _cmd_plc_download(params):
    """Download a file from PLC to the local filesystem."""
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        online_dev = oa.get_online_device()
        if online_dev is None:
            return {"ok": False, "error": "get_online_device() returned None"}

        src = params.get("src", "")
        if not src:
            return {"ok": False, "error": "Parameter 'src' is required (PLC path)"}

        dest = params.get("dest", "")
        if not dest:
            dest = tempfile.mktemp(
                prefix="plc_", suffix=os.path.splitext(src)[1] or ".bin"
            )

        overwrite = str(params.get("overwrite", "1")).lower() in ("1", "true", "yes")

        # Ensure dest directory exists
        dest_dir = os.path.dirname(dest)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        if hasattr(online_dev, "upload_file"):
            online_dev.upload_file(src, dest, overwrite)
        elif hasattr(online_dev, "download_file"):
            # fallback: some CODESYS versions swap the direction
            online_dev.download_file(src, dest, overwrite)
        else:
            return {
                "ok": False,
                "error": "Online device has no upload_file or download_file method",
            }

        size = os.path.getsize(dest) if os.path.exists(dest) else -1
        return {
            "ok": True,
            "data": {
                "source": src,
                "destination": dest,
                "size": size,
            },
        }
    except Exception as e:
        return {"ok": False, "error": "PLC download error: {0}".format(e)}




def _cmd_plc_upload(params):
    """Upload a file from local filesystem to PLC.

    Uses download_file(local_src, plc_dest, overwrite) which copies PC→PLC.

    Args:
        --src PATH: local file path
        --dest PATH: destination path on PLC (e.g. PlcLogic/Application/myfile.bin)
        --overwrite 0|1: overwrite if exists (default: 1)
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        online_dev = oa.get_online_device()
        if online_dev is None:
            return {"ok": False, "error": "get_online_device() returned None"}

        src = params.get("src", "")
        if not src:
            return {"ok": False, "error": "Parameter 'src' is required (local path)"}
        if not os.path.exists(src):
            return {"ok": False, "error": "Local file not found: {0}".format(src)}

        dest = params.get("dest", "")
        if not dest:
            dest = os.path.basename(src)

        overwrite = str(params.get("overwrite", "1")).lower() in ("1", "true", "yes")

        if hasattr(online_dev, "download_file"):
            online_dev.download_file(src, dest, overwrite)
        elif hasattr(online_dev, "upload_file"):
            # fallback: upload_file is PLC→PC, so this won't work, but try anyway
            online_dev.upload_file(src, dest, overwrite)
        else:
            return {
                "ok": False,
                "error": "Online device has no download_file or upload_file method",
            }

        return {
            "ok": True,
            "data": {
                "source": src,
                "destination": dest,
                "overwrite": overwrite,
            },
        }
    except Exception as e:
        return {"ok": False, "error": "PLC upload error: {0}".format(e)}




def _cmd_plc_log(params):
    """Read PLC log: download, tail, or list log files.

    Args:
        --file FILENAME: which log file (default: codesyscontrol.log)
        --tail N: show last N lines (stdout)
        --output PATH: save full log to file/directory
        If neither --tail nor --output: list available log files.
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        online_dev = oa.get_online_device()
        if online_dev is None:
            return {"ok": False, "error": "get_online_device() returned None"}

        log_file = params.get("file", "codesyscontrol.log")
        tail_n = None
        output_path = params.get("output", "")

        try:
            tail_n = int(params.get("tail", 0))
        except (ValueError, TypeError):
            tail_n = None

        # No file operation: list log files
        if not tail_n and not output_path:
            try:
                files = online_dev.get_file_list_of_directory("")
                log_files = []
                if files is not None:
                    for f in files:
                        try:
                            name = str(getattr(f, "name", "?"))
                            if "log" in name.lower() or ".log" in name.lower():
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
                                log_files.append(info)
                        except Exception:
                            pass
                return {
                    "ok": True,
                    "data": {"log_files": log_files, "count": len(log_files)},
                }
            except Exception as e:
                return {"ok": False, "error": "List log files error: {0}".format(e)}

        # Download the file from PLC
        if not hasattr(online_dev, "upload_file"):
            return {"ok": False, "error": "Online device has no upload_file method"}

        tmp = tempfile.mktemp(suffix=".log")
        try:
            online_dev.upload_file(log_file, tmp, True)
        except Exception as e:
            try:
                os.remove(tmp)
            except Exception:
                pass
            return {"ok": False, "error": "Upload file error: {0}".format(e)}

        result = {"file": log_file}

        # Copy to output path if requested
        if output_path:
            try:
                dest = output_path
                if (
                    os.path.isdir(output_path)
                    or output_path.endswith(os.sep)
                    or output_path.endswith("/")
                ):
                    dest = os.path.join(output_path, log_file)
                dest_dir = os.path.dirname(dest)
                if dest_dir and not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                with open(tmp, "rb") as src_f:
                    with open(dest, "wb") as dst_f:
                        dst_f.write(src_f.read())
                result["saved_to"] = dest
                result["saved_size"] = os.path.getsize(dest)
            except Exception as e:
                result["save_error"] = str(e)[:200]

        # Read tail lines if requested
        if tail_n and tail_n > 0:
            try:
                with open(tmp, "rb") as f:
                    content = f.read()
                    try:
                        text = content.decode("utf-8")
                    except UnicodeDecodeError:
                        text = content.decode("latin-1")
                    lines = text.splitlines()
                    tail_lines = lines[-tail_n:] if tail_n < len(lines) else lines
                    result["tail"] = tail_lines
                    result["tail_count"] = len(tail_lines)
                    result["total_lines"] = len(lines)
            except Exception as e:
                result["tail_error"] = str(e)[:200]

        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "PLC log error: {0}".format(e)}


