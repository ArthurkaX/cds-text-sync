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

from codesys_utils import project_file_path

# Imported before cts_shared: it puts shared/src on sys.path, so this module can
# be imported cold without depending on an earlier bridge module having done it.
import ide_runtime_common as _common  # noqa: F401 - the import is the sys.path work

from cts_shared import wire

# ── Configuration ──────────────────────────────────────────────────────────

PIPE_NAME = "cds-cli-" + os.environ.get("USERNAME", "default")

# Kept in step with cds_text_sync.__version__; the daemon no longer versions separately.
VERSION = "3.4.0"

# The wire format -- framing, size cap, handshake shape -- lives in cts_shared.wire,
# shared with the CLI. Re-exported here because the bridge's older callers import
# it from this module.
PROTOCOL = wire.PROTOCOL

POLL_INTERVAL = 0.2  # seconds between poll attempts

#: Connect timeout for the daemon's pipe poll. Where a timeout of 20 ms used to
#: sit, 0 is the right value: in .NET, ``Connect(0)`` is one immediate,
#: non-blocking attempt that throws TimeoutException when no server is
#: listening -- only ``Timeout.Infinite`` (-1) waits forever, and the documented
#: ArgumentOutOfRangeException covers negative values other than Infinite. A
#: tick must never wait: it runs on the IDE's UI thread.
CONNECT_TIMEOUT_MS = 0

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


#: Liveness marker for a client that timed out waiting for the single-threaded
#: command loop.  Written next to the log (same TEMP), so a CLI that had to
#: give up can tell "the daemon is not running at all" from "the daemon is
#: alive but busy with a long command", instead of printing one guess for both.
STATUS_FILE = os.path.join(
    os.environ.get("TEMP", "C:\\Temp"), "cds-daemon-status.json"
)


def write_daemon_status(state, method="", started_ts=None):
    """Best-effort liveness marker; never raises into the command loop.

    ``state`` is ``"idle"`` or ``"busy"``; when busy, ``method`` and
    ``started_ts`` (epoch) name the command being run.  A reader that catches a
    partial file treats it as absent, so a plain write is safe enough.
    """
    try:
        payload = {
            "pid": os.getpid(),
            "state": state,
            "method": method,
            "started_ts": started_ts,
            "updated": time.time(),
        }
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(payload))
        try:
            os.remove(STATUS_FILE)
        except OSError:
            pass
        os.rename(tmp, STATUS_FILE)
    except Exception:
        pass


def clear_daemon_status():
    """Remove the liveness marker when the loop stops running.

    Its absence is how a CLI tells "the daemon is not running" from a marker
    that is simply stale.
    """
    try:
        os.remove(STATUS_FILE)
    except Exception:
        pass


def _read_text_utf8(path):
    """Read UTF-8 text as unicode for IronPython/.NET text APIs."""
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


# ── Message I/O ────────────────────────────────────────────────────────────

MAX_MESSAGE_SIZE = wire.MAX_MESSAGE_SIZE


def _read_json_from_pipe(pipe):
    """Read a length-prefixed JSON message from pipe (byte-mode).

    The header parse and the body decode come from cts_shared.wire, so this
    side accepts -- and refuses -- exactly the frames the CLI produces.
    """
    try:
        if hasattr(pipe, "read_msg"):
            return pipe.read_msg()
        if hasattr(pipe, "read"):
            raw_len = pipe.read(wire.HEADER_SIZE)
            if not raw_len or len(raw_len) < wire.HEADER_SIZE:
                return None
            msg_len = wire.parse_header(raw_len)
            if msg_len <= 0:
                return None
            body = pipe.read(msg_len)
            if not body or len(body) < msg_len:
                return None
            return wire.decode_body(body)

        import System

        # Read 4-byte length header as one chunk
        hdr = System.Array.CreateInstance(System.Byte, 4)
        total = 0
        while total < 4:
            n = pipe.Read(hdr, total, 4 - total)
            if n == 0:
                return None
            total += n
        msg_len = wire.parse_header(bytes(bytearray(hdr)))
        if msg_len <= 0:
            # parse_header already logged nothing; a zero-length frame is a
            # valid empty message on the CLI side, and here means a malformed
            # header the loop should ignore.
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
        return wire.decode_body(raw_bytes)
    except wire.WireError as e:
        _log("Invalid message length: {0}".format(e))
        return None
    except Exception as e:
        if "timed out" in str(e).lower():
            # The pipe read timeout fired: a client connected and sent nothing.
            # That is an ordinary end of a connection, not an error to log --
            # the tick must return so the IDE's message loop stays alive.
            return None
        _log("Read error: {0}".format(e))
        return None


def _write_json_to_pipe(pipe, data, raise_on_error=False):
    """Write a length-prefixed JSON message to pipe (byte-mode).

    Returns False when the write failed. A failure usually means the peer is
    gone: a CLI that timed out, was killed or was interrupted stops reading.
    The caller is the one that knows what was being written and how long the
    command took, so it can pass ``raise_on_error=True`` and name the reason
    in a single line of its own instead of getting a bare ``False`` plus the
    generic line below.

    **The daemon's pipe is not flushed.** ``PipeStream.Flush`` is a deliberate
    no-op in .NET -- its own source says calling ``FlushFileBuffers`` there
    "would deadlock if the other end of the pipe is no longer interested in
    reading" -- and ``Write`` already puts byte-mode data on the wire. Asking
    for one only made the code look like it drained something; the call that
    really drains is ``WaitForPipeDrain`` (``FlushFileBuffers``), which this
    file never makes. The ``flush`` below is on the other branch, for a
    Python-style stream that may buffer, where a fake or wrapper can need it.
    """
    try:
        if hasattr(pipe, "write_msg"):
            return pipe.write_msg(data)
        if hasattr(pipe, "write"):
            msg_bytes = wire.encode_body(data)
            pipe.write(wire.encode_header(len(msg_bytes)))
            pipe.write(msg_bytes)
            if hasattr(pipe, "flush"):
                pipe.flush()
            return True

        import System

        msg_bytes = wire.encode_body(data)
        n = len(msg_bytes)
        # Write header (4 bytes, little-endian) — 4 single-byte calls are fine
        pipe.WriteByte(n & 0xFF)
        pipe.WriteByte((n >> 8) & 0xFF)
        pipe.WriteByte((n >> 16) & 0xFF)
        pipe.WriteByte((n >> 24) & 0xFF)
        # Write body as array — one syscall instead of N
        arr = System.Array[System.Byte](list(bytearray(msg_bytes)))
        pipe.Write(arr, 0, len(arr))
        return True
    except Exception as e:
        if raise_on_error:
            raise
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
    pid = os.getpid()
    ide_id = "ide-{0}".format(pid)
    no_proj_err = wire.error_response(
        (
            "No project is open in this IDE ({0}). "
            "Open one with: cts --target {0} project open --path <path>"
        ).format(ide_id),
        code="no_project",
    )
    if not hasattr(sys, "_codesys_daemon_loop"):
        return None, no_proj_err
    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return None, no_proj_err
    try:
        project = getattr(projects, "primary", None)
        if project is None:
            return None, no_proj_err
        return project, None
    except Exception as e:
        return None, {"ok": False, "error": "Project error: {0}".format(e)}


def _project_sync_folder(prj):
    """Extract configured cds-sync-folder property from a project object, or None."""
    if prj is None:
        return None
    try:
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is not None:
            props = getattr(proj_info, "values", proj_info)
            if hasattr(props, "__getitem__"):
                sf = ""
                if hasattr(props, "__contains__") and "cds-sync-folder" in props:
                    sf = props["cds-sync-folder"]
                elif hasattr(props, "get"):
                    sf = props.get("cds-sync-folder", "")
                if sf:
                    return str(sf)
    except Exception:
        pass
    return None


def _instance_info():
    """Return current instance descriptor: {"id": "ide-<pid>", "project": PROJECT | None}."""
    pid = os.getpid()
    instance_id = "ide-{0}".format(pid)
    project_dict = None
    try:
        if hasattr(sys, "_codesys_daemon_loop"):
            projects = sys._codesys_daemon_loop.get("projects")
            if projects is not None:
                prj = getattr(projects, "primary", None)
                if prj is not None:
                    path = _project_file_path(prj) or ""
                    name = None
                    if path:
                        base = path.replace("\\", "/").split("/")[-1]
                        name = os.path.splitext(base)[0]
                    if not name:
                        name = _obj_name(prj) or None
                    sf = _project_sync_folder(prj)
                    project_dict = {
                        "name": name,
                        "path": path,
                        "sync_folder": sf,
                    }
    except Exception as e:
        _log("Error retrieving instance info: {0}".format(e))
        project_dict = None

    return {
        "id": instance_id,
        "project": project_dict,
    }


def _hello_info():
    """Return full HELLO descriptor for protocol v2 handshake."""
    info = _instance_info()
    config = _load_daemon_config()
    return wire.build_hello(
        info["id"],
        os.getpid(),
        VERSION,
        int(config.get("poll_ms", 200)),
        info.get("project"),
    )


def _obj_name(obj):
    for attr in ("get_name", "Name", "Title"):
        try:
            # Pass a default: a missing attribute is the normal case here (an
            # IScriptProject has neither Name nor Title), and letting getattr
            # raise makes the ScriptEngine tracer print a traceback per miss —
            # six figures of Script Messages for one project walk. The
            # try/except stays for .NET properties that raise something other
            # than AttributeError.
            n = getattr(obj, attr, None)
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
    return project_file_path(prj)


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

_CONFIG_MISSING = "missing"
_CONFIG_OK = "ok"
_CONFIG_INVALID = "invalid"

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

#: Where the daemon keeps its settings, and how durable that is.  Reported by
#: ``cts permissions`` so the answer to "where do these live, and will they
#: survive?" is not a guess: the property is part of the .project, so it is
#: saved *with the project* by the IDE, and an edit made while the IDE is
#: online changes only memory until the project is saved.
CONFIG_STORAGE = (
    "the CODESYS project - Project Information, property 'cds-daemon-config'"
)
CONFIG_PERSISTENCE = (
    "Saved with the .project file, so it travels with the project and survives "
    "a restart -- once the project is saved in the IDE. The IDE must be "
    "offline to change it; while online the edit is refused."
)

#: The refusal for an edit that must not touch the project while online.
ONLINE_SAVE_REFUSAL = (
    "The IDE is online with the PLC, and the daemon settings live inside the "
    "project: editing it while online would change only the in-memory project "
    "and would be lost when the IDE is closed without saving. Run "
    "`cts disconnect`, change the settings, then save the project."
)


def daemon_config_online_refusal():
    """The refusal message when the config may not be saved now, else ``None``.

    Returns a string (the reason) rather than a response dict: the only caller
    is the Settings window, which shows it in a message box.
    """
    try:
        projects = sys._codesys_daemon_loop.get("projects")
        prj = projects.primary if projects is not None else None
        if prj is None:
            return None
        from ide_online_guard import project_is_online

        if project_is_online(prj):
            return ONLINE_SAVE_REFUSAL
    except Exception:
        return None
    return None


def _read_daemon_config():
    """Read 'cds-daemon-config' and say whether the stored value was usable.

    Returns ``(config, status)`` where status is one of:

    ``_CONFIG_MISSING``  nothing stored (no project/property, or an empty
                         value): the defaults are the config, not an error.
    ``_CONFIG_OK``       the stored JSON parsed and was merged over defaults.
    ``_CONFIG_INVALID``  something is stored but could not be read or parsed.
                         The merged defaults are NOT the user's config -- they
                         do not carry the user's deny list -- so callers that
                         enforce permissions must fail closed.

    Returns a dict with poll_ms and deny list.
    """
    # Copy the deny list too: callers (and the Settings window) mutate it, and
    # a shared list would leak edits into the module-level default.
    config = dict(_DEFAULT_CONFIG)
    config["deny"] = list(_DEFAULT_CONFIG.get("deny", []))
    try:
        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return config, _CONFIG_MISSING
        prj = projects.primary
        if prj is None:
            return config, _CONFIG_MISSING
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is None:
            return config, _CONFIG_MISSING
        props = getattr(proj_info, "values", proj_info)
        if not hasattr(props, "__getitem__"):
            return config, _CONFIG_MISSING
        raw = ""
        try:
            if "cds-daemon-config" in props:
                raw = str(props["cds-daemon-config"])
        except Exception:
            try:
                raw = str(props.get("cds-daemon-config", ""))
            except Exception as exc:
                _log("daemon config unreadable: {0}".format(exc))
                return config, _CONFIG_INVALID
        if not raw:
            return config, _CONFIG_MISSING
        try:
            loaded = json.loads(raw)
        except Exception as exc:
            _log(
                "daemon config is not valid JSON ({0}); permissions fail "
                "closed until it is fixed".format(exc)
            )
            return config, _CONFIG_INVALID
        if not isinstance(loaded, dict):
            _log(
                "daemon config is not a JSON object; permissions fail closed "
                "until it is fixed"
            )
            return config, _CONFIG_INVALID
        # Merge: user values override defaults
        for k, v in loaded.items():
            config[k] = v
        return config, _CONFIG_OK
    except Exception as exc:
        _log(
            "daemon config read failed: {0}; permissions fail closed until it "
            "can be read".format(exc)
        )
        return config, _CONFIG_INVALID


def _load_daemon_config():
    """Load daemon config for display (poll interval, permissions listing)."""
    return _read_daemon_config()[0]


def _save_daemon_config(config):
    """Save daemon config to project property 'cds-daemon-config'.

    Args:
        config: dict with poll_ms, deny keys

    Returns True on success.  On failure returns False and logs why: the
    caller (the Settings window) shows the failure, and a silently lost
    deny-list edit is exactly the outcome to avoid.
    """
    refusal = daemon_config_online_refusal()
    if refusal is not None:
        _log("cannot save daemon config: the IDE is online; refusing to edit the project")
        return False
    raw = json.dumps(config, ensure_ascii=False)
    try:
        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            _log("cannot save daemon config: no project open")
            return False
        prj = projects.primary
        if prj is None:
            _log("cannot save daemon config: no primary project")
            return False
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is None:
            _log("cannot save daemon config: project info unavailable")
            return False
        props = getattr(proj_info, "values", proj_info)
        if not hasattr(props, "__setitem__"):
            _log("cannot save daemon config: project properties are read-only")
            return False
        props["cds-daemon-config"] = raw
        return True
    except Exception as exc:
        _log("cannot save daemon config: {0}".format(exc))
        return False


def _check_permission(method):
    """Check if a command is allowed by daemon config.

    Returns:
        (allowed, reason) tuple. allowed=True means OK.

    Fails closed: if a stored config exists but cannot be read, the user's
    deny list is unknown, so no permission-gated command is allowed.
    """
    config, status = _read_daemon_config()
    if status == _CONFIG_INVALID:
        return (
            False,
            "Daemon config is unreadable; refusing permission-gated commands "
            "until it is fixed (see the daemon log)",
        )
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
            prj = getattr(projects, "primary", None)
            if prj is not None:
                sf = _project_sync_folder(prj)
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


#: How long the live PLC answer in a status/context snapshot may be reused.
#: Short on purpose: the whole complaint was a status that lagged minutes
#: behind the IDE.  The edit guard does not use this memo at all.
_SNAPSHOT_MAX_AGE_S = 5.0


def _get_plc_status_snapshot():
    """The PLC/online state, answered live (with a short memo) not from cache.

    ``online`` now comes from ``ide_online_helpers.live_online_state``: a
    fresh wrapper written from the IDE's current session.  The old version read
    only the cached handle, so ``cts status`` and ``cts ping`` kept reporting
    "online / run" minutes after the user did Online -> Logout.  ``source`` and
    ``age_s`` say how fresh the answer is; ``owner`` names who opened the
    session when that is distinguishable.  Never logs in and never connects.
    """
    state = sys._codesys_daemon_loop
    result = {
        "known": False,
        "connected": False,
        "online": None,
        "running": None,
        "application_state": "",
        "application": "",
        "path": "",
        "source": "unknown",
        "age_s": None,
        "owner": None,
        "adopted": False,
    }

    # Live truth first: it may adopt a session the daemon had not cached, or
    # drop a stale one, and the detail reads below must see that outcome.
    try:
        import ide_online_helpers as _helpers

        projects = state.get("projects")
        project = getattr(projects, "primary", None) if projects is not None else None
        live = _helpers.live_online_state(project, max_age_s=_SNAPSHOT_MAX_AGE_S)
        result["online"] = live.get("online")
        result["known"] = bool(live.get("known"))
        result["source"] = live.get("source", "unknown")
        result["age_s"] = live.get("age_s")
        result["owner"] = live.get("owner")
        result["adopted"] = bool(live.get("adopted"))
    except Exception as exc:
        result["live_error"] = str(exc)

    online_app = state.get("online_app")
    target_app = state.get("online_target_app")
    if target_app is not None:
        result["application"] = _obj_name(target_app)
        result["path"] = _build_path(target_app)
    if online_app is None:
        return result

    is_connected = _read_online_attr(online_app, "is_connected")
    is_running = _read_online_attr(online_app, "is_running")
    app_state = _read_online_attr(online_app, "application_state")

    if isinstance(is_connected, dict):
        result["connection_error"] = is_connected.get("error", "")
        # Status is diagnostic only. CODESYS may transiently reject this
        # property while the existing wrapper remains usable for read/write;
        # never destroy a live session cache from an observation failure.
        result["connected"] = bool(result["online"])
        return result

    connected = _bool_or_none(is_connected)
    if connected is not None:
        result["connected"] = bool(connected)
    else:
        result["connected"] = bool(result["online"])
    result["running"] = _bool_or_none(is_running)
    if app_state is not None and not isinstance(app_state, dict):
        result["application_state"] = str(app_state)
        state_running = _bool_or_none(app_state)
        if result["running"] is None and state_running is not None:
            result["running"] = state_running
    elif isinstance(app_state, dict):
        result["application_state_error"] = app_state.get("error", "")
    return result
