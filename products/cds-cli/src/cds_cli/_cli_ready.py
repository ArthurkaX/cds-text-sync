# -*- coding: utf-8 -*-
"""
_cli_ready.py — wait until the PLC application is really running.

``cts download`` is finished when the download is finished, not when the
application is running: the runtime needs another moment, and a read issued
straight after the download raced that (a live run read a variable 2 s after the
download, while the program only started working 2 s after that).

The waiting is done *here*, in the client, as separate short requests with the
IDE idle in between. It must not be folded into the daemon's download handler:
that handler runs on the IDE's single UI thread, so a wait inside it freezes
CODESYS for as long as it waits.

Readiness means: the application is in run, and — when ``--var`` was given —
that variable's value changed between two reads, which is what proves the task
is actually cycling rather than merely labelled "run".
"""

from __future__ import annotations

import time

#: How long to wait before reporting "not ready" when nothing else is asked.
DEFAULT_READY_TIMEOUT_S = 30.0

#: Between two readiness polls. The IDE is idle between them, which is the
#: point: each poll is its own short command.
POLL_INTERVAL_S = 0.5

#: Timeout for one readiness request. Short on purpose: a stuck poll is retried
#: within the overall budget instead of holding the wait on one call.
STATUS_REQUEST_TIMEOUT_S = 10.0
READ_REQUEST_TIMEOUT_S = 20.0

_RUN_STATES = frozenset(["run", "running"])


def application_running(plc):
    """Whether a status/ping ``plc`` block says the application is in run.

    ``running`` is the daemon's own boolean when it could read one; the
    ``application_state`` string is the fallback for the wrappers that expose
    only that. An unreadable block is not "running": readiness is never
    assumed.
    """
    if not isinstance(plc, dict):
        return False
    if plc.get("running") is True:
        return True
    state = str(plc.get("application_state", "") or "").strip().lower()
    return state in _RUN_STATES


def _state_text(plc):
    """A short human phrase for what the PLC says right now."""
    if not isinstance(plc, dict):
        return "unknown"
    state = str(plc.get("application_state", "") or "").strip()
    if state:
        return state
    if plc.get("online") is False:
        return "offline"
    if plc.get("online") is True:
        return "online, state unreadable"
    return "unknown"


def _read_value(send, name):
    """Read one variable for the readiness check; ``None`` when unreadable."""
    try:
        response = send("read_variable", {"name": name})
    except Exception:
        return None
    if not isinstance(response, dict) or not response.get("ok"):
        return None
    data = response.get("data", {})
    if not isinstance(data, dict):
        return None
    return data.get("value")


def _sleep(seconds):
    """Module-level so tests can swap the wait out (looked up at call time)."""
    time.sleep(seconds)


def _clock():
    return time.monotonic()


def wait_for_ready(
    send,
    timeout=None,
    ready_var="",
    poll_interval=POLL_INTERVAL_S,
    sleep=None,
    clock=None,
):
    """Poll the daemon until the application is ready, or the budget runs out.

    ``send(method, params)`` is one short daemon request (``status`` /
    ``read_variable``); the caller supplies it so tests can drive a fake daemon.
    Returns a payload with ``ready``, ``ready_after_s`` and, when the wait
    failed, a ``reason`` naming what was actually seen.
    """
    if sleep is None:
        sleep = _sleep
    if clock is None:
        clock = _clock
    if timeout is None:
        timeout = DEFAULT_READY_TIMEOUT_S
    started = clock()
    checks = 0
    running = False
    last_state = "unknown"
    previous_value = None
    saw_value = False
    last_error = None

    while True:
        checks += 1
        try:
            response = send("status", {})
            ok = isinstance(response, dict) and response.get("ok")
            data = response.get("data", {}) if isinstance(response, dict) else {}
            plc = data.get("plc", {}) if isinstance(data, dict) else {}
            running = bool(ok) and application_running(plc)
            last_state = _state_text(plc) if ok else "the daemon did not answer"
            last_error = None if ok else _error_of(response)
        except Exception as error:  # a busy daemon is retried, not fatal
            running = False
            last_error = str(error)
            last_state = "the daemon is unreachable"

        if running:
            if not ready_var:
                return _ready(clock() - started, checks)
            value = _read_value(send, ready_var)
            if value is not None:
                if saw_value and value != previous_value:
                    return _ready(
                        clock() - started,
                        checks,
                        ready_var=ready_var,
                        value=value,
                    )
                previous_value = value
                saw_value = True

        elapsed = clock() - started
        if elapsed >= timeout:
            return _not_ready(
                elapsed,
                checks,
                timeout=timeout,
                ready_var=ready_var,
                running=running,
                last_state=last_state,
                previous_value=previous_value,
                saw_value=saw_value,
                last_error=last_error,
            )
        sleep(min(poll_interval, max(0.0, timeout - elapsed)))


def _error_of(response):
    if isinstance(response, dict) and response.get("error"):
        return str(response.get("error"))
    return "the daemon returned an error"


def _ready(elapsed, checks, ready_var="", value=None):
    payload = {
        "ready": True,
        "ready_after_s": round(elapsed, 2),
        "checks": checks,
    }
    if ready_var:
        payload["ready_var"] = ready_var
        payload["value"] = value
    return payload


def _not_ready(
    elapsed,
    checks,
    timeout,
    ready_var,
    running,
    last_state,
    previous_value,
    saw_value,
    last_error,
):
    if not running:
        reason = (
            "the application did not reach run within {0:g}s "
            "(last application state: {1})".format(timeout, last_state)
        )
    elif ready_var and not saw_value:
        reason = (
            "the application is running, but {0} could not be read within {1:g}s"
            .format(ready_var, timeout)
        )
    else:
        reason = (
            "the application is running, but {0} did not change within {1:g}s "
            "(last value: {2!r}); it may be constant, or the task may not be "
            "cycling".format(ready_var, timeout, previous_value)
        )
    if last_error:
        reason = "{0}; last daemon error: {1}".format(reason, last_error)
    payload = {
        "ready": False,
        "ready_after_s": round(elapsed, 2),
        "checks": checks,
        "reason": reason,
    }
    if ready_var:
        payload["ready_var"] = ready_var
    return payload
