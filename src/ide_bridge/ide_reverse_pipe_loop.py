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
import clr
import sys
import os
import io
import json
import time
import tempfile
import traceback

# Add ide_bridge dir to path
_LOOP_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOOP_DIR not in sys.path:
    sys.path.insert(0, _LOOP_DIR)

import ide_online_helpers as _helpers
import ide_runtime_common as _common

clr.AddReference("System.IO.Pipes")
clr.AddReference("System.IO")

from System.IO.Pipes import NamedPipeClientStream, PipeDirection

# ── Configuration ──────────────────────────────────────────────────────────

PIPE_NAME = "cds-cli-" + os.environ.get("USERNAME", "default")

VERSION = "2.6.0"

POLL_INTERVAL = 0.2  # seconds between poll attempts
CONNECT_TIMEOUT_MS = 20  # ms to wait for pipe connection (short = non-blocking)

LOG_FILE = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "cds-daemon-debug.log")


def _now():
    return time.strftime("%H:%M:%S")


def _log(msg):
    line = "[rpdaemon {0}] {1}".format(_now(), msg)
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _read_text_utf8(path):
    """Read UTF-8 text as unicode for IronPython/.NET text APIs."""
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


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


# ── Pipe protocol helpers ──────────────────────────────────────────────────

# Maximum single message size the daemon will accept from the CLI.
# Raised to 32 MiB so large application_tree / sync_export_text responses
# no longer trip the 1 MiB hard cap.
MAX_MESSAGE_SIZE = 32 * 1024 * 1024


def _read_json_from_pipe(pipe):
    """Read a length-prefixed JSON message from pipe (byte-mode)."""
    try:
        import System

        # Read 4-byte length header as one chunk
        hdr = System.Array.CreateInstance(System.Byte, 4)
        total = 0
        while total < 4:
            n = pipe.Read(hdr, total, 4 - total)
            if n == 0:
                return None
            total += n
        msg_len = hdr[0] | (hdr[1] << 8) | (hdr[2] << 16) | (hdr[3] << 24)
        if msg_len <= 0 or msg_len > MAX_MESSAGE_SIZE:
            _log("Invalid message length: {0}".format(msg_len))
            return None
        # Read body in chunks
        buf = System.Array.CreateInstance(System.Byte, msg_len)
        total = 0
        while total < msg_len:
            n = pipe.Read(buf, total, msg_len - total)
            if n == 0:
                return None
            total += n
        # Convert .NET byte[] to Python str via bytearray
        raw_bytes = bytes(bytearray(buf))
        return json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        _log("Read error: {0}".format(e))
        return None


def _write_json_to_pipe(pipe, data):
    """Write a length-prefixed JSON message to pipe (byte-mode)."""
    try:
        import System

        msg_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        n = len(msg_bytes)
        # Write header (4 bytes, little-endian) — 4 single-byte calls are fine
        pipe.WriteByte(n & 0xFF)
        pipe.WriteByte((n >> 8) & 0xFF)
        pipe.WriteByte((n >> 16) & 0xFF)
        pipe.WriteByte((n >> 24) & 0xFF)
        # Write body as array — one syscall instead of N
        arr = System.Array[System.Byte](list(bytearray(msg_bytes)))
        pipe.Write(arr, 0, len(arr))
        pipe.Flush()
        return True
    except Exception as e:
        _log("Write error: {0}".format(e))
        return False


# ── Command handler ────────────────────────────────────────────────────────


def _require_param(params, key, type_=str):
    """Validate and return a required parameter."""
    val = params.get(key)
    if val is None:
        raise ValueError("Parameter '{0}' is required".format(key))
    try:
        return type_(val)
    except (ValueError, TypeError):
        raise ValueError("Parameter '{0}' must be {1}".format(key, type_.__name__))


def _get_active_project():
    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return None, {"ok": False, "error": "projects not captured"}
    try:
        project = projects.primary
        if project is None:
            return None, {"ok": False, "error": "No active project"}
        return project, None
    except Exception as e:
        return None, {"ok": False, "error": "Project error: {0}".format(e)}


def _obj_name(obj):
    for attr in ("get_name", "Name", "Title"):
        try:
            n = getattr(obj, attr)
            if callable(n):
                n = n()
            if n:
                return str(n)
        except Exception:
            pass
    return ""


def _json_safe(value):
    try:
        string_types = (basestring,)
        text_type = unicode
    except NameError:
        string_types = (str,)
        text_type = str
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, string_types):
        return text_type(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[text_type(key)] = _json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return text_type(value)


def _get_project_info_object(project):
    try:
        if hasattr(project, "get_project_info"):
            return project.get_project_info()
    except Exception:
        pass
    try:
        if hasattr(project, "project_info"):
            return project.project_info
    except Exception:
        pass
    return None


def _read_project_info_attr(proj_info, names):
    for name in names:
        try:
            if hasattr(proj_info, name):
                value = getattr(proj_info, name)
                if callable(value):
                    value = value()
                if value is not None:
                    return _json_safe(value)
        except Exception:
            pass
    return None


def _project_info_summary(proj_info):
    fields = [
        ("Company", ["Company", "company", "get_company"]),
        ("Title", ["Title", "title", "get_title"]),
        ("Version", ["Version", "version", "get_version"]),
        ("Author", ["Author", "author", "get_author"]),
        ("Description", ["Description", "description", "get_description"]),
        (
            "DefaultNamespace",
            [
                "DefaultNamespace",
                "DefaultNameSpace",
                "defaultNamespace",
                "default_namespace",
                "defaultnamespace",
                "get_default_namespace",
            ],
        ),
        ("URL", ["URL", "Url", "url", "get_url"]),
    ]
    summary = {}
    for key, names in fields:
        value = _read_project_info_attr(proj_info, names)
        if value is not None:
            summary[key] = value
    return summary


def _mapping_to_dict(values):
    result = {}
    if values is None:
        return result

    try:
        for key, value in values.items():
            result[_json_safe(key)] = _json_safe(value)
        return result
    except Exception:
        pass

    keys = None
    for attr in ("keys", "Keys"):
        try:
            keys = getattr(values, attr)
            if callable(keys):
                keys = keys()
            if keys is not None:
                break
        except Exception:
            keys = None
    if keys is not None:
        try:
            for key in keys:
                try:
                    result[_json_safe(key)] = _json_safe(values[key])
                except Exception:
                    pass
            return result
        except Exception:
            pass

    try:
        for item in values:
            try:
                if hasattr(item, "Key") and hasattr(item, "Value"):
                    result[_json_safe(item.Key)] = _json_safe(item.Value)
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    result[_json_safe(item[0])] = _json_safe(item[1])
                else:
                    result[_json_safe(item)] = _json_safe(values[item])
            except Exception:
                pass
    except Exception:
        pass
    return result


def _project_info_properties(proj_info):
    try:
        values = getattr(proj_info, "values", None)
    except Exception:
        values = None
    if values is None:
        values = proj_info
    return _mapping_to_dict(values)


_path_cache = {}
_MAX_PATH_CACHE = 5000


def _build_path(obj):
    obj_id = id(obj)
    cached = _path_cache.get(obj_id)
    if cached is not None:
        return cached
    parts = []
    current = obj
    for _ in range(30):
        try:
            name = _obj_name(current)
            if name:
                parts.insert(0, name)
            parent = getattr(current, "parent", None)
            if parent is None:
                break
            current = parent
        except Exception:
            break
    result = "/".join(parts)
    if len(_path_cache) < _MAX_PATH_CACHE:
        _path_cache[obj_id] = result
    return result


# ── Cache invalidation ─────────────────────────────────────────────────────


def _clear_path_cache():
    """Clear the _build_path cache (call when project structure changes)."""
    _path_cache.clear()


# ── Daemon config (security + poll) ───────────────────────────────────────

_DEFAULT_CONFIG = {
    "poll_ms": 200,
    "deny": [  # blocked by default (uncheck in Settings window to allow)
        "reset_plc",
        "reset_plc --kind origin",
        "create_boot_app",
        "plc_upload",
        "source_download",
        "delete_pou",
    ],
}


def _load_daemon_config():
    """Load daemon config from project property 'cds-daemon-config'.

    Returns a dict with poll_ms and deny list.
    Merges with defaults so missing keys are filled in.
    """
    config = dict(_DEFAULT_CONFIG)
    try:
        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return config
        prj = projects.primary
        if prj is None:
            return config
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is None:
            return config
        props = getattr(proj_info, "values", proj_info)
        if hasattr(props, "__getitem__"):
            raw = ""
            try:
                if "cds-daemon-config" in props:
                    raw = str(props["cds-daemon-config"])
            except Exception:
                try:
                    raw = str(props.get("cds-daemon-config", ""))
                except Exception:
                    pass
            if raw:
                import json as _json

                try:
                    loaded = _json.loads(raw)
                    if isinstance(loaded, dict):
                        # Merge: user values override defaults
                        for k, v in loaded.items():
                            config[k] = v
                except Exception:
                    pass
    except Exception:
        pass
    return config


def _save_daemon_config(config):
    """Save daemon config to project property 'cds-daemon-config'.

    Args:
        config: dict with poll_ms, deny keys
    """
    import json as _json

    raw = _json.dumps(config, ensure_ascii=False)
    try:
        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return False
        prj = projects.primary
        if prj is None:
            return False
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is None:
            return False
        props = getattr(proj_info, "values", proj_info)
        if hasattr(props, "__setitem__"):
            props["cds-daemon-config"] = raw
            return True
        return False
    except Exception:
        return False


def _check_permission(method):
    """Check if a command is allowed by daemon config.

    Returns:
        (allowed, reason) tuple. allowed=True means OK.
    """
    config = _load_daemon_config()
    deny_list = config.get("deny", [])
    if method in deny_list:
        return False, "Forbidden by daemon settings (deny list includes '{0}')".format(
            method
        )
    # Also check if any pattern matches (e.g. "reset_plc" matches "reset_plc --kind origin")
    for denied in deny_list:
        if method.startswith(denied):
            return (
                False,
                "Forbidden by daemon settings (pattern '{0}' matches '{1}')".format(
                    denied, method
                ),
            )
    return True, ""


def _get_status_info():
    """Build the detailed daemon status dict for the 'status' handler."""
    result = {
        "pid": os.getpid(),
        "started_at": sys._codesys_daemon_loop.get("started_at"),
        "projects_captured": sys._codesys_daemon_loop.get("projects") is not None,
        "system_captured": sys._codesys_daemon_loop.get("system") is not None,
        "command_count": sys._codesys_daemon_loop.get("command_count", 0),
    }
    # Add sync folder info if available
    try:
        projects = sys._codesys_daemon_loop.get("projects")
        if projects is not None:
            prj = projects.primary
            if prj is not None:
                proj_info = None
                if hasattr(prj, "get_project_info"):
                    proj_info = prj.get_project_info()
                elif hasattr(prj, "project_info"):
                    proj_info = prj.project_info
                if proj_info is not None:
                    props = getattr(proj_info, "values", proj_info)
                    if hasattr(props, "__getitem__"):
                        sf = ""
                        if (
                            hasattr(props, "__contains__")
                            and "cds-sync-folder" in props
                        ):
                            sf = props["cds-sync-folder"]
                        elif hasattr(props, "get"):
                            sf = props.get("cds-sync-folder", "")
                        if sf:
                            result["sync_folder"] = str(sf)
                # Project filename
                for attr in ["filename", "FileName", "FullName", "Path"]:
                    try:
                        val = getattr(prj, attr)
                        if val:
                            result["project"] = str(val)
                            break
                    except Exception:
                        pass
    except Exception:
        pass
    return result


def _read_online_attr(online_app, attr):
    try:
        if hasattr(online_app, attr):
            value = getattr(online_app, attr)
            if callable(value):
                value = value()
            return _json_safe(value)
    except Exception as e:
        return {"error": str(e)}
    return None


def _bool_or_none(value):
    if value is None or isinstance(value, dict):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "run", "running", "online"):
        return True
    if text in ("false", "0", "no", "stop", "stopped", "offline", "disconnected"):
        return False
    return None


def _get_plc_status_snapshot():
    """Return cached PLC/online state without initiating a new login."""
    state = sys._codesys_daemon_loop
    online_app = state.get("online_app")
    target_app = state.get("online_target_app")
    result = {
        "known": online_app is not None,
        "connected": False,
        "online": None,
        "running": None,
        "application_state": "",
        "application": "",
        "path": "",
    }
    if target_app is not None:
        result["application"] = _obj_name(target_app)
        result["path"] = _build_path(target_app)
    if online_app is None:
        return result

    is_connected = _read_online_attr(online_app, "is_connected")
    is_online = _read_online_attr(online_app, "is_online")
    is_running = _read_online_attr(online_app, "is_running")
    app_state = _read_online_attr(online_app, "application_state")

    if isinstance(is_connected, dict):
        result["connection_error"] = is_connected.get("error", "")
        state["online_app"] = None
        state["online_target_app"] = None
        result["known"] = False
        return result

    connected = _bool_or_none(is_connected)
    result["online"] = _bool_or_none(is_online)
    result["running"] = _bool_or_none(is_running)
    if app_state is not None and not isinstance(app_state, dict):
        result["application_state"] = str(app_state)
        state_running = _bool_or_none(app_state)
        if result["running"] is None and state_running is not None:
            result["running"] = state_running
        if connected is None:
            connected = True
    elif isinstance(app_state, dict):
        result["application_state_error"] = app_state.get("error", "")
    result["connected"] = bool(connected)
    if result["online"] is None:
        result["online"] = result["connected"]
    return result


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


def _cmd_project_info():
    project, err = _get_active_project()
    if err:
        return err
    try:
        info = {
            "name": _obj_name(project),
            "captured_at": sys._codesys_daemon_loop.get("started_at", ""),
            "daemon_pid": os.getpid(),
            "mode": "reverse_pipe",
        }
        for attr in ["filename", "FileName", "FullName", "Path"]:
            try:
                val = getattr(project, attr)
                if val:
                    info["filename"] = str(val)
                    break
            except Exception:
                pass
        try:
            children = project.get_children(recursive=True)
            info["object_count"] = len(list(children))
        except Exception:
            info["object_count"] = -1
        # Read Project Information dialog data: Summary tab + Properties tab.
        try:
            proj_info = _get_project_info_object(project)
            if proj_info is not None:
                summary = _project_info_summary(proj_info)
                properties = _project_info_properties(proj_info)
                info["summary"] = summary
                info["properties"] = properties
                sf = properties.get("cds-sync-folder", "")
                if sf:
                    info["sync_folder"] = str(sf)
        except Exception:
            pass
        return {"ok": True, "data": info}
    except Exception as e:
        return {"ok": False, "error": "Project info error: {0}".format(e)}


def _cmd_project_tree(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        depth = params.get("depth", 0)
        tree = _build_tree(project, depth=depth, current_depth=0)
        return {"ok": True, "data": tree}
    except Exception as e:
        return {"ok": False, "error": "Project tree error: {0}".format(e)}


MAX_TREE_DEPTH = 50  # safety guard against cycles


def _build_tree(obj, depth=0, current_depth=0):
    if current_depth > MAX_TREE_DEPTH:
        return {"name": _obj_name(obj), "_truncated": True}
    node = {"name": _obj_name(obj)}
    try:
        guid = obj.Guid
        if guid:
            node["guid"] = str(guid)
    except Exception:
        pass
    if depth > 0 and current_depth >= depth:
        return node
    try:
        children = obj.get_children()
        child_list = []
        for child in children:
            child_list.append(
                _build_tree(child, depth=depth, current_depth=current_depth + 1)
            )
        if child_list:
            node["children"] = child_list
    except Exception:
        pass
    return node


def _cmd_application_state():
    try:
        import scriptengine as se

        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return {"ok": False, "error": "projects not captured"}
        prj = projects.primary
        app = prj.active_application
        if app is None:
            return {
                "ok": True,
                "data": {
                    "application_state": "unknown",
                    "note": "No active application",
                },
            }
        oa = se.online.create_online_application(app)
        if oa is None:
            return {"ok": True, "data": {"application_state": "disconnected"}}
        # Cache the online app
        sys._codesys_daemon_loop["online_app"] = oa
        sys._codesys_daemon_loop["online_target_app"] = app
        info = {}
        for attr in ["application_state", "is_connected", "is_running", "is_online"]:
            if hasattr(oa, attr):
                try:
                    val = getattr(oa, attr)
                    if callable(val):
                        info[attr] = str(val())
                    else:
                        info[attr] = str(val)
                except Exception:
                    pass
        return {"ok": True, "data": info}
    except Exception as e:
        _log("app_state ERROR: {0}".format(e))
        return {"ok": False, "error": "Application state error: {0}".format(e)}


def _cmd_connect_to_device(params):
    _invalidate_device_cache()
    project, err = _get_active_project()
    if err:
        return err
    try:
        ip_address = params.get("ipAddress", params.get("ip", ""))
        gateway_name = params.get("gatewayName", params.get("gateway", "Gateway-1"))
        result = _helpers.connect_to_device_impl(project, ip_address, gateway_name)
        return {"ok": True, "data": result}
    except Exception as e:
        return {
            "ok": False,
            "error": "Connect error: {0}\n{1}".format(e, traceback.format_exc()),
        }


def _cmd_disconnect_from_device():
    _invalidate_device_cache()
    project, err = _get_active_project()
    if err:
        return err
    try:
        result = _helpers.disconnect_from_device_impl(project)
        return {"ok": True, "data": result}
    except Exception as e:
        _log("Disconnect warning: {0}".format(e))
        return {"ok": True, "data": {"state": "disconnected", "warning": str(e)}}


def _cmd_download(params):
    """Force a full download of the active application to the PLC.

    Needed after adding new objects (GVL/DUT/POU): connect_to_device only does
    an online-change login and never pushes a full download, so the PLC keeps
    running the old code. params: {"start": true|false} (default true).
    """
    _invalidate_device_cache()
    project, err = _get_active_project()
    if err:
        return err
    try:
        start = params.get("start", True)
        result = _helpers.download_impl(project, start=start)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Download error: {0}".format(e)}


def _cmd_read_variable(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        variable_name = _require_param(params, "name", str)
        result = _helpers.read_variable_impl(project, variable_name)
        return {"ok": True, "data": result}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": "Read variable error: {0}".format(e)}


def _cmd_write_variable(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        variable_name = _require_param(params, "name", str)
        value = _require_param(params, "value")
        result = _helpers.write_variable_impl(project, variable_name, value)
        return {"ok": True, "data": result}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": "Write variable error: {0}".format(e)}


def _cmd_read_variables(params):
    """Batch-read a list of expressions. params: {"names": [...]}"""
    project, err = _get_active_project()
    if err:
        return err
    try:
        names = params.get("names", [])
        if not isinstance(names, list):
            return {"ok": False, "error": "'names' must be a list"}
        result = _helpers.read_variables_impl(project, names)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Read variables error: {0}".format(e)}


def _cmd_write_variables(params):
    """Batch-write a list of {name, value}. params: {"items": [...], "raw_value": bool}.
    raw_value: when True, skip normalize_write_value (bare enum members for
    qualified-only types where TYPE#member is double-prefixed by CODESYS).
    """
    project, err = _get_active_project()
    if err:
        return err
    try:
        items = params.get("items", [])
        if not isinstance(items, list):
            return {"ok": False, "error": "'items' must be a list"}
        raw_value = bool(params.get("raw_value", False))
        result = _helpers.write_variables_impl(project, items, raw_value=raw_value)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Write variables error: {0}".format(e)}


def _cmd_export(params):
    project, err = _get_active_project()
    if err:
        return err
    out_path = params.get("output", "")
    if not out_path:
        out_path = os.path.join(
            os.environ.get("TEMP", "C:\\Temp"),
            "cds-snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S")),
        )
    try:
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
            from ide_online_helpers import atomic_write

            with open(tmp_path, "rb") as f:
                content = f.read()
            atomic_write(out_path, content)
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
        return {"ok": True, "data": {"path": out_path, "size": size}}
    except Exception as e:
        return {"ok": False, "error": "Export error: {0}".format(e)}


def _cmd_build(params):
    """Build the active application using app.build().

    Collects build messages via system.get_messages().
    Supports --output PATH and --stdout flags.
    """
    project, err = _get_active_project()
    if err:
        return err
    try:
        import time
        import traceback

        # Get system from daemon state
        daemon_state = getattr(sys, "_codesys_daemon_loop", {})
        system_obj = daemon_state.get("system")
        if system_obj is None:
            return {
                "ok": False,
                "error": "System object not available in daemon state.",
            }

        # Find the active application (not the project)
        from System import Guid

        BUILD_CATEGORY_GUID = "97F48D64-A2A3-4856-B640-75C046E37EA9"

        app = None
        try:
            app = project.active_application
        except Exception:
            pass
        if app is None:
            for child in project.get_children(True):
                if hasattr(child, "is_application"):
                    try:
                        if child.is_application:
                            app = child
                            break
                    except Exception:
                        pass
        if app is None:
            return {"ok": False, "error": "No active application found to build."}

        app_name = "?"
        try:
            app_name = app.get_name()
        except Exception:
            pass

        # Clear build messages before build
        try:
            category_guid = Guid(BUILD_CATEGORY_GUID)
            system_obj.clear_messages(category_guid)
        except Exception:
            try:
                system_obj.clear_messages(BUILD_CATEGORY_GUID)
            except Exception:
                pass

        # Build
        start = time.time()
        try:
            app.build()
        except Exception as e:
            return {"ok": False, "error": "Build exception: {0}".format(e)}
        elapsed = time.time() - start

        # Collect messages
        messages = []
        error_count = 0
        warning_count = 0
        try:
            msg_objects = system_obj.get_message_objects(BUILD_CATEGORY_GUID)
            for msg in msg_objects:
                try:
                    msg_text = str(getattr(msg, "text", ""))
                    if "Build started" in msg_text or "Compile complete" in msg_text:
                        continue
                    severity = str(getattr(msg, "severity", ""))
                    if "Error" in severity:
                        error_count += 1
                    if "Warning" in severity:
                        warning_count += 1
                    obj_ref = None
                    obj_name = ""
                    try:
                        obj_ref = getattr(msg, "object", None)
                        if obj_ref:
                            obj_name = str(obj_ref.get_name())
                    except Exception:
                        pass
                    msg_id = ""
                    try:
                        prefix = str(getattr(msg, "prefix", ""))
                        number = int(getattr(msg, "number", 0))
                        if number > 0:
                            msg_id = "{0}{1:04d}".format(prefix, number)
                        else:
                            msg_id = prefix
                    except Exception:
                        pass
                    messages.append(
                        {
                            "severity": severity,
                            "code": msg_id,
                            "text": msg_text,
                            "object": obj_name,
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass

        result = {
            "ok": error_count == 0,
            "data": {
                "application": app_name,
                "errors": error_count,
                "warnings": warning_count,
                "elapsed_seconds": round(elapsed, 3),
                "messages": messages,
            },
        }

        # Write output file if requested
        output_path = params.get("output") if isinstance(params, dict) else None
        if output_path:
            try:
                with open(output_path, "wb") as f:
                    f.write(
                        json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")
                    )
                result["data"]["output_file"] = output_path
            except Exception as e:
                result["data"]["output_error"] = str(e)

        return result
    except Exception as e:
        _log("Build error: {0}\n{1}".format(e, traceback.format_exc()))
        return {"ok": False, "error": "Build error: {0}".format(e)}


_DEVICE_CACHE_TTL = 30  # seconds


def _get_device_objects(project):
    """Get project children with TTL cache."""
    cache = sys._codesys_daemon_loop.get("device_cache")
    cache_ts = sys._codesys_daemon_loop.get("device_cache_ts", 0)
    now = time.time()
    if cache is not None and (now - cache_ts) < _DEVICE_CACHE_TTL:
        return cache
    objs = list(project.get_children(recursive=True))
    sys._codesys_daemon_loop["device_cache"] = objs
    sys._codesys_daemon_loop["device_cache_ts"] = now
    return objs


def _invalidate_device_cache():
    """Force invalidate the device cache."""
    sys._codesys_daemon_loop["device_cache_ts"] = 0


def _find_object_in_project(project, obj_name, app_name=None):
    """Find a named object in the project tree.

    Returns (target, obj_type) or (None, None) if not found.
    If app_name is given, only matches objects under that application.
    """
    for child in _get_device_objects(project):
        try:
            cname = str(_common.object_name(child))
        except Exception as e:
            _log("Object search: failed to read object name: {0}".format(e))
            continue

        if cname != obj_name:
            continue

        if app_name:
            parent = child
            found_in_app = False
            while hasattr(parent, "parent"):
                try:
                    parent = parent.parent
                    pname = str(_common.object_name(parent))
                except Exception as e:
                    _log(
                        "Object search: failed to inspect parent chain for '{0}': {1}".format(
                            obj_name, e
                        )
                    )
                    break
                if pname == app_name:
                    found_in_app = True
                    break
            if not found_in_app:
                continue

        try:
            obj_type = str(child.get_type())
        except Exception:
            obj_type = "Unknown"
        return child, obj_type

    return None, None


def _active_application_name(project):
    try:
        app = _helpers.get_active_application(project)
        if app is not None:
            return str(_common.object_name(app))
    except Exception:
        pass
    return ""


def _read_text_member(obj, attr_name):
    try:
        member = getattr(obj, attr_name, None)
        if member is None:
            return None
        if hasattr(member, "text"):
            text = member.text
            if callable(text):
                text = text()
            return _json_safe(text)
        return _json_safe(str(member))
    except Exception:
        return None


def _find_object_by_selector(project, params):
    guid = str(params.get("guid", "") or "").lower()
    path = str(params.get("path", "") or "").replace("\\", "/").strip("/")
    name = str(params.get("name", "") or "")

    for child in _get_device_objects(project):
        try:
            child_name = str(_common.object_name(child))
        except Exception:
            child_name = ""
        try:
            child_guid = str(getattr(child, "Guid", "")).lower()
        except Exception:
            child_guid = ""
        try:
            child_path = _build_path(child).replace("\\", "/").strip("/")
        except Exception:
            child_path = ""

        if guid and child_guid == guid:
            return child
        if path and child_path == path:
            return child
        if name and child_name == name:
            return child

    return None


def _cmd_read_object(params):
    project, err = _get_active_project()
    if err:
        return err
    if not (params.get("path") or params.get("name") or params.get("guid")):
        return {"ok": False, "error": "read_object requires path, name, or guid"}

    try:
        target = _find_object_by_selector(project, params)
        if target is None:
            return {"ok": False, "error": "Object not found"}

        try:
            obj_type = str(target.get_type())
        except Exception:
            obj_type = "Unknown"

        data = {
            "name": _obj_name(target),
            "path": _build_path(target),
            "type": obj_type,
        }
        try:
            data["guid"] = str(target.Guid)
        except Exception:
            pass

        decl = _read_text_member(target, "textual_declaration")
        impl = _read_text_member(target, "textual_implementation")
        if decl is not None:
            data["declaration"] = decl
        if impl is not None:
            data["implementation"] = impl

        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": "Read object error: {0}".format(e)}


def _ensure_online_app(project):
    try:
        online_app, target_app = _helpers.ensure_online_connection(project)
        if online_app is not None:
            sys._codesys_daemon_loop["online_app"] = online_app
            sys._codesys_daemon_loop["online_target_app"] = target_app
        return online_app, target_app, None
    except Exception as e:
        return None, None, str(e)


def _cmd_device_status(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        device_filter = (params.get("device") or "").lower()
        status_list = []

        app = _helpers.get_active_application(project)
        if app is not None:
            try:
                name = _obj_name(app)
            except Exception:
                name = "Application"
            entry = {
                "name": name,
                "path": _build_path(app),
                "connected": "false",
            }
            online_app, _target_app, online_err = _ensure_online_app(project)
            if online_app is not None:
                entry["connected"] = "true"
                try:
                    entry["application_state"] = str(online_app.application_state)
                except Exception as e:
                    entry["application_state_error"] = str(e)
            elif online_err:
                entry["connection_error"] = online_err
            if not device_filter or device_filter in name.lower():
                status_list.append(entry)
        return {"ok": True, "data": {"devices": status_list}}
    except Exception as e:
        return {"ok": False, "error": "Device status error: {0}".format(e)}


def _cmd_test_online(params):
    import scriptengine as se

    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return {"ok": False, "error": "projects not captured"}
    tb = []
    try:
        tb.append("se imported OK")
        prj = projects.primary
        tb.append("project: " + str(prj)[:80])
        app = prj.active_application
        tb.append("app: " + str(app)[:80])
        if app is None:
            return {"ok": True, "data": {"state": "no app", "log": tb}}
        oa = se.online.create_online_application(app)
        tb.append("oa: " + str(oa)[:80])
        if oa is not None:
            state = str(oa.application_state)
            tb.append("state: " + state)
        return {"ok": True, "data": {"state": str(oa) if oa else "None", "log": tb}}
    except Exception as e:
        _log("test_online EXCEPTION: " + str(e))
        tb.append("ERROR: " + str(e))
        tb.append(traceback.format_exc())
        return {"ok": False, "error": str(e), "log": tb}


def _cmd_explore_api():
    """Explore available APIs for log/event/diagnostic access."""
    import scriptengine as se

    result = {}
    try:
        prj = sys._codesys_daemon_loop.get("projects")
        if prj is None:
            return {"ok": False, "error": "projects not captured"}
        prj = prj.primary
        app = prj.active_application
        oa = se.online.create_online_application(app)

        # 1. OnlineApplication methods
        result["oa_methods"] = [m for m in dir(oa) if not m.startswith("_")]

        # 2. se.online module
        result["se_online_methods"] = [
            m for m in dir(se.online) if not m.startswith("_")
        ]

        # 3. Device objects with log/event/message/diagnostic methods
        log_keywords = [
            "log",
            "event",
            "message",
            "diagnos",
            "error",
            "status",
            "trace",
            "info",
        ]
        devices = []
        for child in prj.get_children(True):
            name = ""
            try:
                name = str(child.get_name())
            except Exception:
                pass
            methods = [
                m for m in dir(child) if any(k in m.lower() for k in log_keywords)
            ]
            if methods:
                devices.append({"name": name, "log_methods": methods})
        result["devices_with_log_api"] = devices[:20]

        # 4. System log methods
        try:
            import __main__

            system = getattr(__main__, "system", None)
            if system:
                sys_methods = [
                    m for m in dir(system) if any(k in m.lower() for k in log_keywords)
                ]
                if sys_methods:
                    result["system_log_methods"] = sys_methods
        except Exception:
            pass

        # 5. se.online module deeper
        online_attrs = {}
        for attr in dir(se.online):
            if not attr.startswith("_"):
                try:
                    val = getattr(se.online, attr)
                    online_attrs[attr] = str(type(val).__name__)
                except Exception:
                    pass
        result["se_online_attrs"] = online_attrs

        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Explore error: {0}".format(e)}


def _cmd_help():
    """List all available commands."""
    help_text = {
        "ping": "Check daemon liveness and cached PLC state",
        "status": "Get daemon, project, sync-folder, and cached PLC state",
        "stop": "Stop the daemon",
        "application_state": "Get PLC application state (run/stop)",
        "project_info": "Get project information",
        "project_tree": "Get project object tree [--depth N]",
        "read_object": "Read one project object [--path PATH | --name NAME | --guid GUID]",
        "connect_to_device": "Connect to PLC [--ip IP] [--gatewayName NAME] — best practice: connect in CODESYS UI before starting daemon. If not, user must approve the connection dialog in CODESYS within ~2 minutes or the command times out.",
        "disconnect_from_device": "Disconnect from PLC",
        "download": "Force a FULL download of the active app to the PLC (login with force-download; needed after adding new GVL/DUT/POU). [--start 0|1, default 1]",
        "read_variable": "Read a PLC variable --name VAR",
        "write_variable": "Write a PLC variable --name VAR --value VAL",
        "device_status": "Get device status",
        "export": "Export project snapshot [--output PATH]",
        "build": "Build the active application [--output PATH]",
        "test_online": "Test online connection helpers",
        "explore": "Explore available APIs",
        "help": "Show this help",
        "read_log": "Read system/PLC log messages [--last N] [--clear]",
        "start_plc": "Start the PLC application",
        "stop_plc": "Stop the PLC application",
        "reset_plc": "Reset PLC [--kind warm|cold|origin]",
        "create_boot_app": "Create boot application on PLC",
        "source_download": "Download source from PLC [--output DIR]",
        "update_pou": "Edge case: update ONE object's text from .st [--name NAME] [--app APP] --st_path PATH. Prefer sync_import_text for the normal disk->IDE flow",
        "delete_pou": "Delete POU/Function/FunctionBlock [--name NAME] [--app APP]",
        "probe": "Probe OnlineApplication for variable/symbol APIs",
        "read_variables": 'Batch-read expressions {"names": [...]} -> per-item value/read_ok/read_error',
        "write_variables": 'Batch-write {"items": [{name,value}]} -> per-item written/write_error',
        "application_tree": "Walk the application OBJECT tree [--depth N] [--values] [--pattern FILTER] [--flat] [--output PATH]",
        "plc_files": "List files on PLC [--path /]",
        "plc_download": "Download file from PLC --src PATH [--dest PATH]",
        "plc_upload": "Upload file to PLC --src PATH --dest PLC_PATH [--overwrite 0|1]",
        "export_csv": "Export PLC variable tree as CSV [--output PATH] [--values]",
        "export_st": "Export project POU source code as .st files [--output DIR]",
        "app_crc": "Get Application CRC and metadata from PLC",
        "app_history": "Log CRC to .dump/app_history.json [--read to just view history]",
        "sync": "Show sync folder info and .dump state",
        "sync_export": "Export Native XML snapshot to .dump/ [--output PATH]",
        "sync_import": "Low-level: import a raw .dump/ XML snapshot back into project [--input PATH]. For text edits use sync_import_text instead",
        "sync_compare": "Compare project tree against .dump/ snapshot [--against PATH]",
        "sync_export_text": "IDE->disk: export Native XML and OVERWRITE project-view/ .st files with the IDE state",
        "sync_import_text": "disk->IDE (preferred): build IMPORT.xml from project-view/ and apply to project. Disk wins on conflicts; requires offline (disconnect first)",
        "sync_compare_text": "Compare project against project-view/ (diff report)",
        "cicd": "Run CI/CD test plan --file path [--timeout N]",
        "permissions": "Show daemon security config (read-only)",
        "plc_log": "Read PLC log [--file codesyscontrol.log] [--tail N] [--output DIR]",
        "app_info": "Get detailed info about application on PLC",
        "compare": "Compare IDE project CRC with PLC Application.crc",
    }
    return {"ok": True, "data": help_text}


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


def _cmd_probe_oa(params):
    """Probe OnlineApplication for variable/symbol-related APIs."""
    import scriptengine as se
    import System
    import System.Reflection

    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    result = {}

    # 1. All public methods of oa
    all_methods = []
    for m in dir(oa):
        if not m.startswith("_"):
            try:
                thing = getattr(oa, m)
                kind = "method" if callable(thing) else "property"
                all_methods.append({"name": m, "type": kind, "str": str(thing)[:120]})
            except Exception as e:
                all_methods.append({"name": m, "error": str(e)[:80]})
    result["all_methods"] = all_methods

    # 2. .NET reflection: get methods by signature
    try:
        net_methods = []
        for m in oa.GetType().GetMethods(
            System.Reflection.BindingFlags.Instance
            | System.Reflection.BindingFlags.Public
        ):
            try:
                p = [str(p.ParameterType.Name) for p in m.GetParameters()]
                net_methods.append(
                    {
                        "name": m.Name,
                        "params": p,
                        "return": str(m.ReturnType.Name),
                    }
                )
            except Exception:
                pass
        result["net_methods"] = net_methods
    except Exception as e:
        result["net_reflection_error"] = str(e)

    # 3. Explore get_online_device() return value
    online_dev = None
    if hasattr(oa, "get_online_device"):
        try:
            online_dev = oa.get_online_device()
            if online_dev is not None:
                dev_methods = []
                for m in dir(online_dev):
                    if not m.startswith("_"):
                        try:
                            thing = getattr(online_dev, m)
                            kind = "method" if callable(thing) else "property"
                            dev_methods.append(
                                {"name": m, "type": kind, "str": str(thing)[:120]}
                            )
                        except Exception:
                            pass
                result["online_device_methods"] = dev_methods
                # Try to get its type info
                try:
                    dev_net_methods = []
                    for m in online_dev.GetType().GetMethods(
                        System.Reflection.BindingFlags.Instance
                        | System.Reflection.BindingFlags.Public
                    ):
                        try:
                            p = [str(p.ParameterType.Name) for p in m.GetParameters()]
                            dev_net_methods.append(
                                {
                                    "name": m.Name,
                                    "params": p,
                                    "return": str(m.ReturnType.Name),
                                }
                            )
                        except Exception:
                            pass
                    result["online_device_net_methods"] = dev_net_methods
                except Exception as e:
                    result["online_device_net_error"] = str(e)
        except Exception as e:
            result["get_online_device_error"] = str(e)

    # 4. Explore oa.application (the Application object inside CODESYS)
    app_obj = None
    if hasattr(oa, "application"):
        try:
            app_obj = oa.application
            if app_obj is not None:
                app_methods = []
                for m in dir(app_obj):
                    if not m.startswith("_"):
                        try:
                            thing = getattr(app_obj, m)
                            kind = "method" if callable(thing) else "property"
                            app_methods.append(
                                {"name": m, "type": kind, "str": str(thing)[:180]}
                            )
                        except Exception:
                            pass
                result["oa_application_methods"] = app_methods
                # Try get_children on the application
                try:
                    children = list(app_obj.get_children(True))
                    result["oa_app_children_count"] = len(children)
                    child_names = []
                    for c in children[:30]:
                        try:
                            child_names.append(c.get_name())
                        except Exception:
                            pass
                    result["oa_app_children_names"] = child_names
                except Exception as e:
                    result["oa_app_children_error"] = str(e)[:200]
        except Exception as e:
            result["oa_application_error"] = str(e)[:200]

    # 5. Try to call candidate methods for symbol enumeration
    candidates = [
        "all_variables",
        "variables",
        "symbols",
        "symbol",
        "plc_variables",
        "tags",
        "signals",
        "list_variables",
        "get_all_variables",
        "value_names",
        "variable_names",
        "symbol_names",
    ]
    for name in candidates:
        if hasattr(oa, name):
            try:
                thing = getattr(oa, name)
                if callable(thing):
                    val = thing()
                else:
                    val = thing
                result["try_oa_" + name] = str(val)[:300]
            except Exception as e:
                result["try_oa_" + name + "_error"] = str(e)[:200]

    # Also try on online_device and application
    if online_dev is not None:
        for name in candidates:
            if hasattr(online_dev, name):
                try:
                    thing = getattr(online_dev, name)
                    if callable(thing):
                        val = thing()
                    else:
                        val = thing
                    result["try_dev_" + name] = str(val)[:300]
                except Exception as e:
                    result["try_dev_" + name + "_error"] = str(e)[:200]

    if app_obj is not None:
        for name in candidates:
            if hasattr(app_obj, name):
                try:
                    thing = getattr(app_obj, name)
                    if callable(thing):
                        val = thing()
                    else:
                        val = thing
                    result["try_app_" + name] = str(val)[:300]
                except Exception as e:
                    result["try_app_" + name + "_error"] = str(e)[:200]

    return {"ok": True, "data": result}


def _cmd_application_tree(params):
    """Build the application OBJECT tree by walking Application children.

    Walks oa.application.get_children(), builds object paths, and optionally
    reads current values. For declared PLC variables use the variable-map /
    variable-snapshot tools instead.

    Args:
        params:
            --depth N: max recursion depth (default 10)
            --pattern FILTER: filter by name/path substring
            --values: try to read current values
            --flat: return flat list instead of tree
            --output PATH: write JSON to file (recommended for large projects)
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        read_values = str(params.get("values", "")).lower() in ("1", "true", "yes")
        pattern = params.get("pattern", "").lower()
        is_flat = str(params.get("flat", "")).lower() in ("1", "true", "yes")
        output_path = params.get("output", "")
        max_depth = 10
        try:
            max_depth = int(params.get("depth", 10))
        except (ValueError, TypeError):
            pass

        app_obj = getattr(oa, "application", None)
        if app_obj is None:
            return {"ok": False, "error": "oa.application not available"}

        _seen = set()

        def _walk(obj, prefix="", depth=0):
            """Recursively walk application children, building path."""
            if depth > max_depth:
                return None

            name = _obj_name(obj)
            if not name:
                return None

            # Build full path
            full_path = prefix + "." + name if prefix else name

            # Dedup
            obj_id = id(obj)
            if obj_id in _seen:
                return None
            _seen.add(obj_id)

            node = {"name": name, "path": full_path}

            # Try to read value
            if read_values:
                for candidate in [full_path, "Application." + full_path]:
                    try:
                        val = oa.read_value(candidate)
                        if val is not None:
                            str_val = str(val)
                            if (
                                "Invalid expression" in str_val
                                or "invalid expression" in str_val.lower()
                            ):
                                node["value_error"] = (
                                    "Invalid expression (not exported to online)"
                                )
                            else:
                                node["value"] = str_val
                            break
                    except Exception:
                        pass

            try:
                children = list(obj.get_children())
                if children:
                    child_list = []
                    for child in children:
                        child_node = _walk(child, full_path, depth + 1)
                        if child_node is not None:
                            child_list.append(child_node)
                    if child_list:
                        node["children"] = child_list
            except Exception:
                pass

            return node

        tree = _walk(app_obj)
        if tree is None:
            return {"ok": False, "error": "Empty variable tree"}

        if is_flat:
            # Flatten tree to list
            def _flatten(node, result=None):
                if result is None:
                    result = []
                entry = {"name": node["name"], "path": node["path"]}
                if "value" in node:
                    entry["value"] = node["value"]
                if pattern:
                    if (
                        pattern in node["path"].lower()
                        or pattern in node["name"].lower()
                    ):
                        result.append(entry)
                else:
                    result.append(entry)
                for child in node.get("children", []):
                    _flatten(child, result)
                return result

            flat_list = _flatten(tree)

            if output_path:
                # Write full JSON to file, return summary via pipe
                import json as _json

                export = {
                    "count": len(flat_list),
                    "variables": flat_list,
                    "mode": "flat",
                }
                try:
                    dir_name = os.path.dirname(output_path)
                    if dir_name and not os.path.exists(dir_name):
                        os.makedirs(dir_name)
                    with open(output_path, "wb") as f:
                        f.write(
                            _json.dumps(export, indent=2, ensure_ascii=False).encode(
                                "utf-8"
                            )
                        )
                    return {
                        "ok": True,
                        "data": {
                            "count": len(flat_list),
                            "output": output_path,
                            "mode": "flat",
                            "note": "Full list written to file. Use --pattern to search.",
                        },
                    }
                except Exception as e:
                    return {
                        "ok": False,
                        "error": "Write output file error: {0}".format(e),
                    }

            return {
                "ok": True,
                "data": {
                    "count": len(flat_list),
                    "variables": flat_list,
                    "mode": "flat",
                },
            }

        else:
            # Tree mode: filter if pattern given
            def _filter_tree(node):
                """Keep only nodes matching pattern."""
                children = node.get("children", [])
                filtered_children = []
                for child in children:
                    fc = _filter_tree(child)
                    if fc is not None:
                        filtered_children.append(fc)
                name_match = (
                    not pattern
                    or pattern in node["name"].lower()
                    or pattern in node.get("path", "").lower()
                )
                if name_match or filtered_children:
                    result = {"name": node["name"], "path": node["path"]}
                    if "value" in node:
                        result["value"] = node["value"]
                    if filtered_children:
                        result["children"] = filtered_children
                    return result
                return None

            filtered = _filter_tree(tree) if pattern else tree
            if filtered is None:
                return {
                    "ok": True,
                    "data": {"mode": "tree", "note": "No matches for pattern"},
                }

            if output_path:
                import json as _json

                export = filtered
                export["mode"] = "tree"
                try:
                    dir_name = os.path.dirname(output_path)
                    if dir_name and not os.path.exists(dir_name):
                        os.makedirs(dir_name)
                    with open(output_path, "wb") as f:
                        f.write(
                            _json.dumps(export, indent=2, ensure_ascii=False).encode(
                                "utf-8"
                            )
                        )
                    return {
                        "ok": True,
                        "data": {
                            "output": output_path,
                            "mode": "tree",
                            "note": "Variable tree written to file.",
                        },
                    }
                except Exception as e:
                    return {
                        "ok": False,
                        "error": "Write output file error: {0}".format(e),
                    }

            return {"ok": True, "data": filtered}

    except Exception as e:
        return {"ok": False, "error": "Variable tree error: {0}".format(e)}


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


def _cmd_export_csv(params):
    """Export PLC variable tree as CSV.

    Args:
        --output PATH: save CSV to file (default: return as text)
        --values: include current values (requires connection)
        --pattern FILTER: filter by name
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        read_values = str(params.get("values", "")).lower() in ("1", "true", "yes")
        pattern = params.get("pattern", "").lower()
        output_path = params.get("output", "")

        app_obj = getattr(oa, "application", None)
        if app_obj is None:
            return {"ok": False, "error": "oa.application not available"}

        _seen = set()
        rows = []

        def _walk(obj, prefix="", depth=0):
            if depth > 20:
                return
            name = _obj_name(obj)
            if not name:
                return
            full_path = prefix + "." + name if prefix else name
            obj_id = id(obj)
            if obj_id in _seen:
                return
            _seen.add(obj_id)

            val_str = ""
            if read_values:
                for candidate in [full_path, "Application." + full_path]:
                    try:
                        val = oa.read_value(candidate)
                        if val is not None:
                            sv = str(val)
                            if (
                                "Invalid expression" not in sv
                                and "invalid expression" not in sv.lower()
                            ):
                                val_str = sv
                            break
                    except Exception:
                        pass

            if not pattern or pattern in full_path.lower() or pattern in name.lower():
                rows.append((full_path, val_str))

            try:
                for child in list(obj.get_children()):
                    _walk(child, full_path, depth + 1)
            except Exception:
                pass

        _walk(app_obj)

        # Build CSV content
        # Build CSV content without StringIO
        lines = []
        lines.append("Path,Value")
        for path, val in rows:
            path_esc = (
                '"' + path.replace('"', '""') + '"'
                if "," in path or '"' in path
                else path
            )
            val_esc = (
                '"' + val.replace('"', '""') + '"' if "," in val or '"' in val else val
            )
            lines.append(path_esc + "," + val_esc)
        csv_text = "\r\n".join(lines) + "\r\n"

        if output_path:
            out_dir = os.path.dirname(output_path)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir)
            with open(output_path, "wb") as f:
                f.write(csv_text.encode("utf-8"))
            return {
                "ok": True,
                "data": {"path": output_path, "rows": len(rows), "saved": True},
            }
        else:
            return {"ok": True, "data": {"csv": csv_text, "rows": len(rows)}}
    except Exception as e:
        return {"ok": False, "error": "Export CSV error: {0}".format(e)}


def _cmd_export_st(params):
    """Export project POUs as .st source files.

    Walks the project tree looking for POU-like objects
    (Program, FunctionBlock, Function, GVL, DUT) and
    exports their source code to .st files.

    Args:
        --output DIR: destination directory (default: .dump/st/)
    """
    project, err = _get_active_project()
    if err:
        return err

    try:
        # Determine output directory
        out_dir = params.get("output", "")
        if not out_dir:
            sync_dir, _ = _get_sync_folder()
            if sync_dir:
                out_dir = os.path.join(sync_dir, ".dump", "st")
            else:
                out_dir = os.path.join(
                    os.environ.get("TEMP", "C:\\Temp"), "cds-st-export"
                )
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        exported = []
        errors = []

        def _walk_export(obj, folder=""):
            """Recursively walk project and export POU-like objects."""
            name = _obj_name(obj)
            if not name:
                return

            # Check if this is a POU-like object (has code to export)
            obj_type = str(type(obj).__name__)
            is_pou = False
            for t in [
                "Program",
                "FunctionBlock",
                "Function",
                "Gvl",
                "Dut",
                "POU",
                "IecTask",
                "Action",
                "Method",
                "Property",
                "GlobalVariableList",
                "IoConfig",
                "Device",
            ]:
                if t.lower() in obj_type.lower():
                    is_pou = True
                    break

            if is_pou:
                # Try to export via export_native on just this object
                safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
                subfolder = folder
                if subfolder:
                    obj_dir = os.path.join(out_dir, subfolder)
                else:
                    obj_dir = out_dir
                if not os.path.exists(obj_dir):
                    os.makedirs(obj_dir)

                st_path = os.path.join(obj_dir, safe_name + ".st")
                xml_path = os.path.join(obj_dir, safe_name + ".xml")

                try:
                    # Try save to file first (some objects support this)
                    if hasattr(obj, "save"):
                        obj.save(st_path)
                        if os.path.exists(st_path):
                            size = os.path.getsize(st_path)
                            exported.append(
                                {
                                    "name": name,
                                    "path": st_path,
                                    "size": size,
                                    "type": obj_type,
                                }
                            )
                            return

                    if hasattr(obj, "export_native"):
                        obj.export_native(st_path)
                        if os.path.exists(st_path):
                            size = os.path.getsize(st_path)
                            exported.append(
                                {
                                    "name": name,
                                    "path": st_path,
                                    "size": size,
                                    "type": obj_type,
                                }
                            )
                            return

                    # Fallback: use project.export_native with just this object
                    if hasattr(project, "export_native"):
                        project.export_native([obj], xml_path, recursive=False)
                        if os.path.exists(xml_path):
                            size = os.path.getsize(xml_path)
                            exported.append(
                                {
                                    "name": name,
                                    "path": xml_path,
                                    "size": size,
                                    "type": obj_type + " (xml)",
                                }
                            )
                            return

                    errors.append(
                        "No export method for: {0} ({1})".format(name, obj_type)
                    )
                except Exception as e:
                    errors.append(
                        "Export failed for {0}: {1}".format(name, str(e)[:100])
                    )

            # Recurse into children
            try:
                for child in list(obj.get_children()):
                    child_name = _obj_name(child) or ""
                    child_folder = folder + "/" + child_name if folder else child_name
                    _walk_export(child, child_folder)
            except Exception:
                pass

        _walk_export(project)

        return {
            "ok": True,
            "data": {
                "output_directory": out_dir,
                "exported_count": len(exported),
                "exported": exported[:50],  # first 50
                "error_count": len(errors),
                "errors": errors[:20],  # first 20 errors
            },
        }
    except Exception as e:
        return {"ok": False, "error": "Export ST error: {0}".format(e)}


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


# ── Sync folder helpers ────────────────────────────────────────────────────


def _get_sync_folder():
    """Get the sync folder path from project properties.

    Returns:
        (path, error) tuple. path is None if not configured.
    """
    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return None, "projects not captured"
    try:
        prj = projects.primary
        if prj is None:
            return None, "No active project"
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is None:
            return None, "Project info not available"
        props = getattr(proj_info, "values", proj_info)
        base_dir = ""
        if hasattr(props, "__getitem__"):
            try:
                if "cds-sync-folder" in props:
                    base_dir = props["cds-sync-folder"]
            except Exception:
                try:
                    base_dir = props.get("cds-sync-folder", "")
                except Exception:
                    pass
        if not base_dir:
            return (
                None,
                "Sync folder not configured. Set 'cds-sync-folder' project property (Tools → Project_directory.py)",
            )
        base_dir = str(base_dir).strip()
        # Resolve relative paths
        is_relative = (
            base_dir == "." or base_dir.startswith("./") or base_dir.startswith(".\\")
        )
        if is_relative:
            project_path = ""
            for attr in ["filename", "FileName", "FullName", "Path"]:
                try:
                    val = getattr(prj, attr)
                    if val:
                        project_path = str(val)
                        break
                except Exception:
                    pass
            if project_path:
                project_dir = os.path.dirname(project_path)
                base_dir = os.path.normpath(
                    os.path.join(
                        project_dir, base_dir.replace("/", os.sep).replace("\\", os.sep)
                    )
                )
        return base_dir, None
    except Exception as e:
        return None, str(e)


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


def _active_app_online_state():
    """Best-effort detection of whether the active application has a live
    online session. Returns (is_online, state_str). Never raises -- on any
    failure returns (False, "") so callers can proceed.
    """
    try:
        import scriptengine as se

        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return (False, "")
        app = projects.primary.active_application
        if app is None:
            return (False, "")
        oa = se.online.create_online_application(app)
        if oa is None:
            return (False, "disconnected")
        state = ""
        if hasattr(oa, "application_state"):
            try:
                state = str(oa.application_state)
            except Exception:
                state = ""
        online = False
        for attr in ("is_connected", "is_online"):
            if hasattr(oa, attr):
                try:
                    val = getattr(oa, attr)
                    if callable(val):
                        val = val()
                    if val:
                        online = True
                except Exception:
                    pass
        # Fall back to the state string when the booleans are unavailable.
        if not online and state and state.lower() not in ("none", "disconnected", ""):
            online = True
        return (online, state)
    except Exception:
        return (False, "")


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

        updated_text = []
        if os.path.exists(compare_report_path):
            updated_text = _apply_modified_st_objects(project, compare_report_path)
            if updated_text:
                _log("Updated text objects: {0}".format(", ".join(updated_text)))

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

        return {
            "ok": True,
            "data": {
                "path": patch_path,
                "size": os.path.getsize(patch_path),
                "created_text_objects": [e["name"] for e in text_creates],
                "updated_text_objects": updated_text,
            },
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
    """Remove CreateTextObjects elements from the XML root."""
    import copy

    filtered = copy.deepcopy(root)
    for child in list(filtered):
        local_tag = str(child.tag).rsplit("}", 1)[-1]
        if local_tag == "CreateTextObjects":
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
                "error": "No .test/ directory found at {0}".format(test_dir),
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
