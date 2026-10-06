# -*- coding: utf-8 -*-
"""
ide_reverse_pipe_loop.py — CODESYS-side reverse pipe daemon.

This module runs inside CODESYS as a service loop driven by a WinForms Timer
(the method the 1.x daemon used).  It connects to a CLI-created named pipe
server, reads one command, executes it in the main script context, and writes
back the result.

Architecture (reverse pipe):
  1. CLI creates \named pipecds-cli-<user> as server, writes command, waits
  2. CODESYS timer tick tries to connect as client (one poll per tick)
  3. If a pipe exists: read command, execute CODESYS API, write response, close
  4. If no pipe exists: the tick does nothing and returns

Why a timer and not a ``while`` loop: a loop *inside the running script* holds
the IDE in "Executing script ... Click here to CANCEL" for the daemon's whole
lifetime.  A download's progress never painted, the PLC's stop/start was
invisible, and the window looked hung.  The timer script creates the timer and
returns, so the IDE's own message loop drives the ticks and owns the UI between
them.  CODESYS ScriptEngine is single-threaded, so the command *being executed*
still runs on the UI thread; what is gone is the permanent "executing script"
state around it, not the execution itself.

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
    PROTOCOL,
    CONNECT_TIMEOUT_MS,
    _log,
    wire,
    _read_json_from_pipe,
    _write_json_to_pipe,
    _load_daemon_config,
    _check_permission,
    _get_active_project,
    _get_status_info,
    _get_plc_status_snapshot,
    _instance_info,
    _hello_info,
    write_daemon_status,
    clear_daemon_status,
)

from ide_daemon_helpers import (
    _get_sync_folder,
)
import ide_response_context
import ide_time
from ide_last_result import _cmd_last_result, record_last_result
from ide_timeout_profile import count_st_blocks, make_timeout_profile
from ide_online_helpers import adopt_existing_online_session, remember_script_online_handle

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
    _cmd_generate_docs,
    _cmd_update_pou,
    _cmd_delete_pou,
)

from ide_handlers_cicd import _cmd_cicd

from ide_handlers_snapshooter import _cmd_snapshooter

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
    return wire.ok_response({"message": "Daemon stopping..."})


def _handle_ping(params):
    return wire.ok_response(
        {
            "status": "pong",
            "mode": "reverse_pipe",
            "pid": os.getpid(),
            "plc": _get_plc_status_snapshot(),
            "timeout_profile": sys._codesys_daemon_loop.get("timeout_profile"),
        }
    )


def _handle_status(params):
    result = _get_status_info()
    result["running"] = sys._codesys_daemon_loop.get("running", False)
    result["mode"] = "reverse_pipe"
    result["plc"] = _get_plc_status_snapshot()
    result["timeout_profile"] = sys._codesys_daemon_loop.get("timeout_profile")
    return wire.ok_response(result)


def _handle_timeout_profile(params):
    """Return startup-sized timeouts without probing the PLC session.

    Not folded into ``wire.ok_response``: that treats a None payload as "no
    data key", while this must keep ``"data": null`` when the profile has not
    been computed, so the response stays byte-identical to the old one.
    """
    return {"ok": True, "data": sys._codesys_daemon_loop.get("timeout_profile", {})}


import command_registry as _registry

_ALIASES = _registry.ALIASES
_NO_PERMISSION = _registry.NO_PERMISSION

_DISPATCH = {}
for _command_name, (_mode, _handler_name) in _registry.DISPATCH_SPECS.items():
    _handler = globals()[_handler_name]
    _DISPATCH[_command_name] = _noarg(_handler) if _mode == "noarg" else _handler


def handle_command(method, params, request_id=None):
    """Dispatch a command. All CODESYS API calls happen here, in the main loop."""
    suffix = " [{0}]".format(request_id) if request_id else ""
    _log("Command: {0}{1}".format(method, suffix))
    method = _ALIASES.get(method, method)
    if method not in _NO_PERMISSION:
        allowed, reason = _check_permission(method)
        if not allowed:
            return wire.error_response(reason)
    handler = _DISPATCH.get(method)
    if handler is None:
        return wire.error_response("Unknown method: {0}".format(method))
    try:
        return handler(params)
    except Exception as e:
        _log("Command error: {0}\n{1}".format(e, traceback.format_exc()))
        return wire.error_response("{0}: {1}".format(type(e).__name__, e))





# ── Timer-driven service loop ─────────────────────────────────────────────


def _poll_interval_ms():
    """Tick interval in milliseconds, from the daemon config (default 200)."""
    state = sys._codesys_daemon_loop
    config = state.get("config")
    if not config:
        try:
            config = _load_daemon_config()
        except Exception:
            config = {}
        state["config"] = config
    try:
        return int(config.get("poll_ms", 200))
    except Exception:
        return 200


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


def _close_connection(pipe):
    """Drop one pipe instance at once; a close that fails is not fatal.

    Both spellings are accepted: the .NET stream has ``Close``, and the fakes
    the offline tests drive the loop with expose the lowercase one.
    """
    if pipe is None:
        return
    close = getattr(pipe, "Close", None) or getattr(pipe, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        pass


def _deliver_response(pipe, method, request_id, response, command_seconds=0.0):
    """Write the reply; when the client has gone, end the connection here.

    A CLI that timed out, was killed or was Ctrl+C'd stops reading, so the
    write fails with Errno 232 ("Pipe is broken"). That is a normal end of a
    connection, not an error to wait out: one line naming the command, this
    instance dropped at once, and the loop goes straight to the next client --
    the outcome survives in ``record_last_result`` for ``cts last-result``.
    The line carries both timings, which tell the two possible causes apart on
    a live IDE (see the note on the log line below). True = delivered.
    """
    started = time.time()
    failure = None
    delivered = False
    try:
        # The helper returns False as well as raising; both mean the same thing
        # here, and both must end the connection rather than be recorded as a
        # delivered reply.
        delivered = _write_json_to_pipe(pipe, response, raise_on_error=True)
    except Exception as exc:
        failure = exc
    if delivered:
        return True

    _close_connection(pipe)
    _log(
        "client left before the reply was written ({0}{1}): command ran "
        "{2:.1f}s, write failed after {3:.1f}s: {4}".format(
            method,
            " [{0}]".format(request_id) if request_id else "",
            command_seconds,
            time.time() - started,
            failure if failure is not None else "the write reported failure",
        )
    )
    return False


def _serve_connection(pipe, dash=None):
    """Serve a single connected pipe connection.

    Handles protocol v2 handshake:
      H1 (ping+hello) -> reply H2 (hello) -> C (command) or R (release)
    Or legacy direct command execution.
    Attaches 'instance' metadata to all command responses.

    Returns True if daemon stop was requested, False otherwise.
    """
    # Logged here on purpose: it is the line whose *absence* of a successor in
    # the daemon log proves the loop is stuck in the first read of a
    # connection that never sent anything, as opposed to never connecting.
    _log("Client connected; waiting for the first message")
    first_msg = _read_json_from_pipe(pipe)
    if first_msg is None:
        return False

    cmd_to_run = None

    # Check for protocol v2 handshake: ping with params.hello
    params = first_msg.get("params")
    if first_msg.get("method") == wire.HELLO_METHOD and wire.is_hello_message(first_msg):
        # Send H2
        h2 = wire.hello_reply(_hello_info())
        if not _write_json_to_pipe(pipe, h2):
            # Same outcome as a lost reply, same one-line report and the same
            # immediate drop: the probe is answered into a pipe nobody reads.
            _log("client left before the hello reply was written")
            _close_connection(pipe)
            return False

        # Read next message (C command, R release, or EOF)
        next_msg = _read_json_from_pipe(pipe)
        if next_msg is None or next_msg.get("release"):
            # Released or disconnected: return to poll loop silently
            return False

        cmd_to_run = next_msg
    else:
        # Legacy cts or direct command
        cmd_to_run = first_msg

    method = cmd_to_run.get("method", "")
    params = cmd_to_run.get("params", {})
    # Optional: an older CLI sends none, and then nothing changes for it. When
    # it is present it is echoed back and logged, so a command the CLI gave up
    # on can be matched to what the daemon actually did.
    request_id = cmd_to_run.get(wire.REQUEST_ID_KEY)

    sys._codesys_daemon_loop["command_count"] = (
        sys._codesys_daemon_loop.get("command_count", 0) + 1
    )
    sys._codesys_daemon_loop["last_command"] = method

    # Log to UI
    if dash is not None:
        try:
            dash.log_command(_dashboard_command_label(method, params))
            dash.set_command_count(sys._codesys_daemon_loop["command_count"])
        except Exception:
            pass

    # Execute command in main script context
    command_started = time.time()
    # Mark the loop busy before the handler runs: while a long command is in
    # flight the CLI's own timeout can fire, and this is what its message reads
    # to say "alive but busy with <method> for Ns" instead of "not running".
    # The marker stays busy through the reply write too -- a write blocked on a
    # gone reader is exactly the state the CLI must not mistake for idle.
    write_daemon_status("busy", method, command_started)
    try:
        response = handle_command(method, params, request_id=request_id)
        command_seconds = time.time() - command_started

        # Attach instance and the "where am I" context (computed after command
        # execution; cached state only, never a new PLC/IDE call).
        ide_response_context.attach_response_metadata(response, request_id)

        if dash is not None:
            _dashboard_log_response(dash, method, response)

        # Write the response back. On a failed write the connection is dropped
        # here and now -- the client is gone, and this instance must not be held
        # while the result is recorded and the next client waits.
        delivered = _deliver_response(
            pipe, method, request_id, response, command_seconds
        )

        # Record the outcome. On a failed write -- the CLI gave up on a long
        # command and closed its end -- this file is the only place the result
        # still exists; for the sync commands it is recorded even when the write
        # worked, so the result of the last import can always be looked up
        # afterwards.
        record_last_result(method, response, request_id, write_failed=not delivered)

        # Canonical name: the protocol's legacy "stop" alias must still stop the
        # daemon, while `cts stop` (stop_plc) must not. handle_command has
        # already resolved the alias for dispatch; this repeats it for the
        # shutdown test.
        return _registry.canonical_name(method) == "stop_daemon"
    finally:
        write_daemon_status("idle")


#: Re-entrancy latch.  A WinForms timer fires again while its handler is still
#: running, and ``Application.DoEvents`` in a UI handler (the dashboard's Run
#: Tests button) can also let a timer message through.  A nested tick must do
#: nothing at all: the outer tick is on this thread's stack, holding the same
#: daemon state, and serving a second client from inside it would re-enter the
#: CODESYS API.
_TICK_BUSY_KEY = "tick_busy"


def _make_timer():
    """Create the WinForms timer.  Split out so tests can inject a fake."""
    from System.Windows.Forms import Timer

    return Timer()


def _dispose_timer(timer):
    """Stop, unhook and dispose one timer.  Safe twice, and with ``None``."""
    if timer is None:
        return
    try:
        timer.Stop()
    except Exception:
        pass
    try:
        timer.Tick -= _on_tick
    except Exception:
        pass
    try:
        timer.Dispose()
    except Exception:
        pass


def _log_startup():
    """One-time startup: capture the IDE context, report, show the dashboard.

    Split from the timer so a failure here leaves ``started`` False and the
    launcher can say the daemon did not start, instead of claiming a timer that
    never ticked.  Returns the dashboard form, or ``None``.
    """
    capture_codesys_globals()

    # The supported operating order is IDE Online/Login first, daemon second.
    # Capture that existing session now; this creates only a wrapper and never
    # calls login or changes the PLC connection.
    try:
        project, _error = _get_active_project()
        # Built now, while the start script still runs: from a timer tick
        # CODESYS refuses to create one ("Stack empty").
        try:
            if remember_script_online_handle(project) is not None:
                _log("Kept an online wrapper for the timer ticks")
        except Exception as error:
            _log("Could not build the online wrapper: {0}".format(error))
        online_app, _target_app = adopt_existing_online_session(project)
        if online_app is not None:
            _log("Adopted existing IDE online session")
    except Exception as error:
        _log("Could not adopt existing IDE online session: {0}".format(error))

    _log(
        "cds-text-sync v{0} started  pipe={1}  id=ide-{2}  protocol={3}".format(
            VERSION, PIPE_NAME, os.getpid(), PROTOCOL
        )
    )

    # Warn if sync folder not configured
    sf, _sf_err = _get_sync_folder()
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

    # Show UI dashboard (WinForms window).  Both the form and the timer live in
    # the IDE's own message loop once this script returns -- that loop is what
    # pumps them, and why nothing here may block.
    dash = None
    if _ui is not None:
        try:
            dash = _ui.show_daemon_ui()
            # Push startup messages to dashboard
            if dash is not None:
                dash.log_command("Daemon v{0} started".format(VERSION))
                dash.log_command("Waiting for CLI...")
                if sf is None:
                    dash.log_command("[WARN] Sync folder not set")
                else:
                    dash.log_command("Sync folder: {0}".format(os.path.basename(sf)))
        except Exception:
            dash = None
    return dash


def _ensure_timer():
    """Create, hook and start the service timer.  There is never more than one."""
    state = sys._codesys_daemon_loop
    stale = state.get("timer")
    if stale is not None:
        # Belt for the same braces as the toggle in run_loop(): two live timers
        # would poll the same pipe twice and fight over one connection.
        state["timer"] = None
        _dispose_timer(stale)

    timer = _make_timer()
    timer.Interval = _poll_interval_ms()
    timer.Tick += _on_tick
    state["timer"] = timer
    state["running"] = True
    state["started"] = True
    state["started_at"] = ide_time.iso_utc()
    state["started_ts"] = time.time()
    state["_shutdown_done"] = False
    # From here the marker exists and says "idle", so a CLI that timed out on a
    # later command knows the daemon was up and simply did not take the request.
    write_daemon_status("idle")
    timer.Start()
    _log(
        "Daemon timer started  interval={0} ms  pipe={1}  id=ide-{2}".format(
            timer.Interval, PIPE_NAME, os.getpid()
        )
    )


def start_daemon():
    """Start the timer daemon and return at once.

    Returning is the whole point: the IDE's message loop drives the ticks, so
    nothing here may block, or the script would hold the UI exactly as the old
    ``while`` loop did.
    """
    if clr is None:
        raise RuntimeError("The reverse-pipe loop must run inside CODESYS.")
    sys._codesys_daemon_loop["dashboard"] = _log_startup()
    _ensure_timer()


def stop_daemon():
    """Stop the service timer and tear the daemon down.  Idempotent."""
    state = sys._codesys_daemon_loop
    _log("stop_daemon requested")
    state["running"] = False
    timer = state.get("timer")
    state["timer"] = None
    _dispose_timer(timer)
    _request_shutdown()


def run_loop():
    """Entry point: start the daemon, or stop it if it is already running.

    Running Project_daemon.py again is the start/stop toggle the 1.x daemon
    had: with a live timer the second run stops it.  Returns as soon as the
    timer is armed -- see ``start_daemon``.
    """
    if sys._codesys_daemon_loop.get("timer") is not None:
        stop_daemon()
        return
    start_daemon()


def _request_shutdown():
    """Tear the daemon down once, whoever asked: Stop, stop_daemon, a tick."""
    state = sys._codesys_daemon_loop
    state["running"] = False
    if state.get("_shutdown_done"):
        return
    state["_shutdown_done"] = True
    _log("Reverse Pipe Daemon loop ended.")
    clear_daemon_status()
    dash = state.get("dashboard")
    state["dashboard"] = None
    if dash is not None and _ui is not None:
        try:
            dash.close_window()
        except Exception:
            pass


def _log_pipe_poll_error(error):
    """One line for a real pipe failure; a missing CLI is the normal case."""
    text = str(error)
    if (
        "timed out" in text.lower()
        or "Could not connect" in text
        or "not found" in text.lower()
    ):
        return
    _log("Pipe poll error: {0}".format(error))


#: A CLI writes its first message immediately after it connects. A client that
#: connects and then sends nothing would otherwise hold this tick -- and with it
#: the IDE's UI thread -- forever, so the read gives up instead.
READ_TIMEOUT_MS = 5000


def _apply_read_timeout(pipe):
    """Bound the first read of a connection; not every stream accepts one."""
    try:
        pipe.ReadTimeout = READ_TIMEOUT_MS
    except Exception:
        pass


def _service_one_client():
    """Poll once: connect only if a CLI is already waiting, else return at once.

    Returns True when the daemon was asked to stop.
    """
    pipe = None
    try:
        pipe = NamedPipeClientStream(".", PIPE_NAME, PipeDirection.InOut)
        # 0 = one immediate attempt, no waiting (see CONNECT_TIMEOUT_MS): a tick
        # must never block the IDE's UI thread. Only -1 waits forever.
        pipe.Connect(CONNECT_TIMEOUT_MS)
    except Exception as error:
        _log_pipe_poll_error(error)
        _close_connection(pipe)
        return False
    try:
        _apply_read_timeout(pipe)
        return _serve_connection(pipe, sys._codesys_daemon_loop.get("dashboard"))
    except Exception as error:
        _log("Pipe serve error: {0}".format(error))
        return False
    finally:
        _close_connection(pipe)


def _refresh_instance_line(dash):
    """Update the dashboard's target line at most once a second."""
    state = sys._codesys_daemon_loop
    now = time.time()
    if now - state.get("_instance_refresh_ts", 0.0) < 1.0:
        return
    state["_instance_refresh_ts"] = now
    if dash is None:
        return
    try:
        current = _instance_info()
    except Exception:
        return
    if current == state.get("_instance_seen"):
        return
    state["_instance_seen"] = current
    setter = getattr(dash, "set_instance", None)
    if setter is None:
        return
    try:
        setter(current)
    except Exception:
        pass


def _heartbeat_idle():
    """Refresh the idle liveness marker at most once a second.

    The marker's timestamp is how a CLI tells "the daemon is alive and idle"
    from a marker left behind by a daemon that exited: without a periodic
    refresh it only moved when a command ran.
    """
    state = sys._codesys_daemon_loop
    now = time.time()
    if now - state.get("_heartbeat_ts", 0.0) < 1.0:
        return
    state["_heartbeat_ts"] = now
    write_daemon_status("idle")


def _on_tick(sender, args):
    """One timer tick: serve at most one client, then re-arm the timer.

    The timer is stopped first and restarted in ``finally``: a WinForms timer
    keeps firing while its handler runs, and a nested tick must do nothing.
    ``tick_busy`` is the second guard for the same job.  A tick that raises is
    logged and the timer is re-armed -- one bad command must not kill the
    daemon.
    """
    state = sys._codesys_daemon_loop
    timer = state.get("timer")
    if timer is None:
        return
    if state.get(_TICK_BUSY_KEY) or state.get("ui_busy"):
        return
    state[_TICK_BUSY_KEY] = True
    try:
        try:
            timer.Stop()
        except Exception:
            pass
        if not state.get("running"):
            # Stop was requested between ticks (Stop button, window close).
            _request_shutdown()
        else:
            try:
                if _service_one_client():
                    _request_shutdown()
            except Exception as error:
                _log(
                    "Daemon tick error: {0}\n{1}".format(error, traceback.format_exc())
                )
            try:
                _refresh_instance_line(state.get("dashboard"))
                _heartbeat_idle()
            except Exception as error:
                _log("Daemon tick upkeep error: {0}".format(error))
    finally:
        state[_TICK_BUSY_KEY] = False
        if state.get("timer") is timer:
            if state.get("running"):
                try:
                    # Re-read poll_ms: the Settings window can change it while
                    # the daemon runs, and the timer is the only clock there is.
                    timer.Interval = _poll_interval_ms()
                    timer.Start()
                except Exception as error:
                    _log("Could not re-arm the daemon timer: {0}".format(error))
            else:
                # Shut down: drop the timer so a later run starts a fresh one.
                state["timer"] = None
                _dispose_timer(timer)


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__" or __name__ == "__builtin__":
    run_loop()
else:
    # Called from codesys_daemon_launcher.py via exec()
    # Check if globals suggest we're inside CODESYS
    if globals().get("projects") is not None or globals().get("system") is not None:
        run_loop()
