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
    _online_app_if_connected,
    _require_online_app,
    _require_online_device,
)

from ide_path_guards import host_path_error, plc_path_error, plc_root_path

import ide_plc_files as plc_files


def _plc_path_refusal(params, name):
    """A refusal when a PLC-path parameter is really an MSYS-rewritten host path."""
    return plc_path_error(name, params.get(name, ""))


def _local_scratch_file(suffix):
    """A concrete local path to download a PLC file into.

    ``tempfile.mktemp`` only *names* a file: the path it returns need not
    exist, and the PLC download was handed one the device API rejected with
    "Value cannot be null. Parameter name: path."  ``mkstemp`` creates the
    file and returns a path that exists in a writable directory, so the call
    never receives an empty or imaginary destination.
    """
    handle, path = tempfile.mkstemp(prefix="cds-plc-", suffix=suffix)
    os.close(handle)
    return path


def _discard_empty(path):
    """Remove a destination a failed download left behind empty.

    A path the CLI then reads or stats would otherwise look like a download
    that produced an empty file, instead of one that failed.
    """
    try:
        if os.path.exists(path) and os.path.getsize(path) == 0:
            os.remove(path)
    except Exception:
        pass


def _plc_suffix(path):
    """A plausible local suffix for a downloaded PLC file."""
    return os.path.splitext(path)[1] or ".bin"

# Imported for its side effect: puts shared/src on sys.path so this module can be
# imported cold, without depending on some earlier bridge module having done it.
import ide_runtime_common  # noqa: F401

from cts_shared.coerce import as_bool


def _cmd_read_log(params):
    """Read IDE messages of one category.

    The category matters: ``get_message_objects`` does not guard a GUID the
    message storage does not know -- ``GetCategory`` returns null for it and
    the call throws "Value cannot be null. Parameter name: category" (the
    no-argument form of the old code hit the same guard from the other side).
    So the category is resolved against ``get_message_categories()`` first and
    an unknown one is an error that lists what is available, never a crash.
    """
    try:
        system = sys._codesys_daemon_loop.get("system")
        if system is None:
            return {"ok": False, "error": "system not captured"}

        last_n = None
        try:
            last_n = int(params.get("last", 0))
        except (ValueError, TypeError):
            last_n = None

        do_clear = as_bool(params.get("clear", ""))

        requested = str(params.get("category") or "").strip()
        available = _message_categories(system)
        if requested:
            chosen = _match_message_category(requested, available)
            if chosen is None:
                return {
                    "ok": False,
                    "error": (
                        "Unknown message category '{0}'. Available categories: "
                        "{1}"
                    ).format(requested, _describe_categories(available)),
                }
        else:
            # Default: the compiler's own messages.  Resolve it against the
            # IDE list when it is there so the description is real, and fall
            # back to the constant when the list is empty (an early tick).
            chosen = _match_message_category(BUILD_CATEGORY_GUID, available) or {
                "guid": BUILD_CATEGORY_GUID,
                "description": "Build",
            }

        messages = _read_message_texts(system, chosen["guid"])

        if last_n is not None and last_n > 0 and len(messages) > last_n:
            messages = messages[-last_n:]

        if do_clear and hasattr(system, "clear_messages"):
            try:
                system.clear_messages(_as_guid(chosen["guid"]))
            except Exception as error:
                _log("Could not clear message category {0}: {1}".format(
                    chosen["guid"], error
                ))

        return {
            "ok": True,
            "data": {
                "category": chosen,
                "count": len(messages),
                "messages": messages,
                "available_categories": available,
            },
        }
    except Exception as e:
        return {"ok": False, "error": "Read log error: {0}".format(e)}


#: The compiler's message category (``Build``).  Kept as a constant because it
#: is the sensible default even when the IDE category list is unavailable.
BUILD_CATEGORY_GUID = "97F48D64-A2A3-4856-B640-75C046E37EA9"


def _norm_guid(text):
    return str(text or "").strip().strip("{}").lower()


def _message_categories(system):
    """``[{guid, description}]`` of the categories the message storage knows.

    Empty when the IDE cannot answer: an empty list must not stop the default
    category from working, it only means an unknown category cannot be
    resolved or described.
    """
    getter = getattr(system, "get_message_categories", None)
    if getter is None:
        return []
    try:
        raw = getter()
    except Exception as error:
        _log("Could not list message categories: {0}".format(error))
        return []
    categories = []
    for guid in raw or []:
        text = str(guid)
        try:
            description = str(system.get_message_category_description(guid))
        except Exception:
            description = ""
        categories.append({"guid": text, "description": description})
    return categories


def _match_message_category(requested, available):
    """The available category the request names, or None.

    Accepts a GUID (with or without braces, any case) or the description, so
    both ``--category 97F48D64-...`` and ``--category Build`` work.
    """
    key = _norm_guid(requested)
    wanted_description = str(requested).strip().lower()
    for entry in available:
        if _norm_guid(entry.get("guid")) == key:
            return entry
    for entry in available:
        if entry.get("description", "").strip().lower() == wanted_description:
            return entry
    return None


def _describe_categories(available):
    if not available:
        return "(the IDE listed none)"
    return ", ".join(
        "{0} ({1})".format(e.get("description") or "?", e.get("guid"))
        for e in available
    )


def _read_message_texts(system, guid_text):
    """Message texts of one category; the GUID is already known to be real."""
    raw = None
    if hasattr(system, "get_messages"):
        raw = system.get_messages(guid_text)
    if raw is None and hasattr(system, "get_message_objects"):
        raw = system.get_message_objects(guid_text)
    return [str(message) for message in (raw or [])]


def _as_guid(guid_text):
    """A System.Guid for the APIs that take one (clear_messages)."""
    import System

    return System.Guid(str(guid_text))




def _cmd_start_plc():
    """Start the PLC application."""
    project, err = _get_active_project()
    if err:
        return err
    try:
        oa, _target_app, online_err = _online_app_if_connected(project)
        if oa is None:
            return {
                "ok": False,
                "error": online_err or "Not connected. Run 'cts connect' first.",
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
        oa, _target_app, online_err = _online_app_if_connected(project)
        if oa is None:
            return {
                "ok": False,
                "error": online_err or "Not connected. Run 'cts connect' first.",
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
        oa, err = _require_online_app()
        if err:
            return err
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
        oa, err = _require_online_app()
        if err:
            return err
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
        oa, err = _require_online_app()
        if err:
            return err
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
    refusal = _plc_path_refusal(params, "path")
    if refusal is not None:
        return refusal
    path = plc_root_path(params.get("path", ""))
    try:
        _oa, online_dev, err = _require_online_device()
        if err:
            return err

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

        # Try common roots when the whole device was asked for.  The root is
        # the empty string; the POSIX spellings catch a runtime (a Linux CODESYS
        # Control, say) whose log and mount points sit under /var, /tmp or
        # /usr rather than under the application's PlcLogic tree.
        paths_to_try = [path]
        if not path:
            paths_to_try = ["", "/usr/", "/home/", "/var/", "/tmp/", "/log/", "/logs/"]

        files = None
        last_error = None
        for p in paths_to_try:
            entries, list_error = plc_files.list_directory(online_dev, p)
            if entries is not None:
                files = entries
                path = p
                break
            last_error = list_error

        if files is None:
            # Show diagnostic info
            diag["paths_tried"] = paths_to_try
            diag["last_error"] = last_error or "unknown"
            diag["note"] = (
                "PLC file system may be disabled or device not fully connected"
            )
            _log(
                "plc_files: {0} (paths tried: {1})".format(
                    diag["last_error"], paths_to_try
                )
            )
            return {
                "ok": False,
                "error": "Get directory entries failed",
                "diagnostics": diag,
            }

        return {"ok": True, "data": {"path": path, "files": files, "count": len(files)}}
    except Exception as e:
        _log("plc_files error: {0}".format(e))
        return {"ok": False, "error": "PLC files error: {0}".format(e)}




def _cmd_plc_download(params):
    """Download a file from PLC to the local filesystem.

    A file that is not on the device is answered before the read is attempted:
    the device API's own answer to a missing path ("Value cannot be null.
    Parameter name: path.") reads as a bug in the path handling, not as "that
    file is not there", and sent the reader hunting the wrong problem.
    """
    refusal = _plc_path_refusal(params, "src") or host_path_error(params, "dest")
    if refusal is not None:
        return refusal
    try:
        _oa, online_dev, err = _require_online_device()
        if err:
            return err

        src = params.get("src", "")
        if not src:
            return {"ok": False, "error": "Parameter 'src' is required (PLC path)"}

        dest = params.get("dest", "")
        if not dest:
            dest = _local_scratch_file(_plc_suffix(src))
        else:
            # Ensure dest directory exists
            dest_dir = os.path.dirname(dest)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir)

        present, entries, parent, lookup_error = plc_files.lookup(online_dev, src)
        if present is False:
            _log("plc_download: {0} not found on the PLC file system".format(src))
            return plc_files.missing_file_error(src, entries, parent)
        if present is None:
            # Could not list the directory: let the read itself report the
            # device's own failure rather than invent "not found".
            _log(
                "plc_download: could not list {0}: {1}".format(
                    parent or "the PLC root", lookup_error
                )
            )

        overwrite = as_bool(params.get("overwrite", "1"))

        try:
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
        except Exception as e:
            _discard_empty(dest)
            _log("plc_download: reading {0} failed: {1}".format(src, e))
            return {
                "ok": False,
                "error": "Reading {0} from the PLC failed: {1}".format(src, e),
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
        _log("plc_download error: {0}".format(e))
        return {"ok": False, "error": "PLC download error: {0}".format(e)}




def _cmd_plc_upload(params):
    """Upload a file from local filesystem to PLC.

    Uses download_file(local_src, plc_dest, overwrite) which copies PC→PLC.

    Args:
        --src PATH: local file path
        --dest PATH: destination path on PLC (e.g. PlcLogic/Application/myfile.bin)
        --overwrite 0|1: overwrite if exists (default: 1)
    """
    refusal = _plc_path_refusal(params, "dest") or host_path_error(params, "src")
    if refusal is not None:
        return refusal
    try:
        _oa, online_dev, err = _require_online_device()
        if err:
            return err

        src = params.get("src", "")
        if not src:
            return {"ok": False, "error": "Parameter 'src' is required (local path)"}
        if not os.path.exists(src):
            return {"ok": False, "error": "Local file not found: {0}".format(src)}

        dest = params.get("dest", "")
        if not dest:
            dest = os.path.basename(src)

        overwrite = as_bool(params.get("overwrite", "1"))

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
    refusal = _plc_path_refusal(params, "file") or host_path_error(params, "output")
    if refusal is not None:
        return refusal
    try:
        _oa, online_dev, err = _require_online_device()
        if err:
            return err

        # ``or``, not a ``get`` default: a client that sends ``file: null``
        # (or "") must fall back to the default, not hand the device API a
        # null path -- which is exactly the "Value cannot be null. Parameter
        # name: path." the upload reported.
        log_file = params.get("file") or "codesyscontrol.log"
        tail_n = None
        output_path = params.get("output", "")

        try:
            tail_n = int(params.get("tail", 0))
        except (ValueError, TypeError):
            tail_n = None

        # No file operation: list log files
        if not tail_n and not output_path:
            entries, list_error = plc_files.list_directory(online_dev, "")
            if entries is None:
                _log("plc_log: listing the log directory failed: {0}".format(list_error))
                return {"ok": False, "error": "List log files error: {0}".format(list_error)}

            log_files = []
            for entry in entries:
                name = entry.get("name", "")
                # A directory is not a log, however it is named.
                if entry.get("is_directory"):
                    continue
                if "log" in name.lower() or ".log" in name.lower():
                    log_files.append(entry)

            data = {"log_files": log_files, "count": len(log_files), "path": ""}
            if not log_files:
                data["note"] = (
                    "no log files in the PLC root; the runtime log may live "
                    "outside the file system the online device exposes"
                )
            return {"ok": True, "data": data}

        # Download the file from PLC
        if not hasattr(online_dev, "upload_file"):
            return {"ok": False, "error": "Online device has no upload_file method"}

        present, entries, parent, lookup_error = plc_files.lookup(online_dev, log_file)
        if present is False:
            _log("plc_log: {0} not found on the PLC file system".format(log_file))
            return plc_files.missing_file_error(log_file, entries, parent)
        if present is None:
            _log(
                "plc_log: could not list {0}: {1}".format(
                    parent or "the PLC root", lookup_error
                )
            )

        tmp = _local_scratch_file(".log")
        try:
            online_dev.upload_file(log_file, tmp, True)
        except Exception as e:
            _discard_empty(tmp)
            _log("plc_log: reading {0} failed: {1}".format(log_file, e))
            return {
                "ok": False,
                "error": "Reading {0} from the PLC failed: {1}".format(log_file, e),
            }

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
                _log("plc_log: saving the log to {0} failed: {1}".format(output_path, e))
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
                _log("plc_log: reading the tail failed: {0}".format(e))
                result["tail_error"] = str(e)[:200]

        return {"ok": True, "data": result}
    except Exception as e:
        _log("plc_log error: {0}".format(e))
        return {"ok": False, "error": "PLC log error: {0}".format(e)}


