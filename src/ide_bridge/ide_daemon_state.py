# -*- coding: utf-8 -*-
"""
ide_daemon_state.py — Shared daemon constants, helpers, and state accessors.

Contains configuration constants and helper functions used by the CODESYS
reverse-pipe daemon loop. All CODESYS global access is performed lazily
at call time through the singleton dict ``sys._codesys_daemon_loop``, which
is created by ide_reverse_pipe_loop.py at startup before any handler runs.
Do NOT initialize ``sys._codesys_daemon_loop`` here.
"""

from __future__ import print_function

import io
import json
import os
import sys
import time

# ── Configuration ──────────────────────────────────────────────────────────

PIPE_NAME = "cds-cli-" + os.environ.get("USERNAME", "default")

VERSION = "2.8.2"

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


# ── Message I/O ────────────────────────────────────────────────────────────

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


# ── Command helpers ────────────────────────────────────────────────────────


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


def _project_file_path(prj):
    """Best-effort filesystem path of a CODESYS project object, or "".

    IronPython attribute access is case-sensitive. The canonical ScriptEngine
    attribute is the lowercase ``path``; some builds instead expose one of the
    PascalCase variants. Try lowercase ``path`` FIRST — omitting it (as older
    call sites did) leaves relative sync-folder resolution unanchored on builds
    such as SP18, which then falls through to a misleading "Access denied".
    """
    for attr in ("path", "filename", "FileName", "FullName", "Path"):
        try:
            val = getattr(prj, attr)
            if val:
                return str(val)
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


# ── Path cache ─────────────────────────────────────────────────────────────

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
                project_file = _project_file_path(prj)
                if project_file:
                    result["project"] = project_file
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
