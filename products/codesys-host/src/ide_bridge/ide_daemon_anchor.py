# -*- coding: utf-8 -*-
"""
ide_daemon_anchor.py — process-wide anchor for the reverse-pipe daemon.

Every ``Tools -> Scripting -> Execute Script`` gets a fresh IronPython runtime
and therefore a fresh ``sys`` module: ``CommandHelper`` builds a new
``IScriptExecutor`` per run and disposes it afterwards, which shuts the runtime
down.  A daemon that keeps its state in ``sys._codesys_daemon_loop`` is
invisible to the next run of ``Project_daemon.py``, and that is how three
daemons ended up polling one pipe.

What does survive a script run inside the same CODESYS process is the
``AppDomain``: the lead verified live (SP22) that ``SetData``/``GetData`` keep
their value across two script runs.  This module keeps the daemon state there,
so a second run sees the first one's timer, generation and window.

The state is an ordinary dict with these keys (all optional until used):

  ``generation``   incremented on every start; a tick whose generation is not
                   the current one disposes itself and closes its window
  ``timer``        the live WinForms timer, or None
  ``pid``          the CODESYS process that owns it
  ``started_at``   ISO timestamp of the current generation
  ``stop``         True once a shutdown was requested
  plus everything the loop already kept (system, projects, dashboard, ...).

Outside CODESYS (CPython tests) the AppDomain is absent, so a plain module
dict is the fallback; ``set_appdomain_for_tests`` injects a fake domain.
"""
from __future__ import print_function

import os

#: AppDomain slot name.  Deliberately not a Python identifier: it must not
#: collide with anything CODESYS itself stores there.
ANCHOR_KEY = "cds-text-sync.daemon"

#: Named-mutex prefix.  The mutex is per pipe name, so it only keeps two
#: CODESYS processes from serving the same CLI pipe (one daemon per pipe).
MUTEX_PREFIX = "cds-text-sync-daemon-"

_FALLBACK_STATE = {}
_DOMAIN_OVERRIDE = None


def _default_state():
    return {
        "running": False,
        "started": False,
        "projects": None,
        "system": None,
        "generation": 0,
        "timer": None,
        "dashboard": None,
        "pid": None,
        "started_at": None,
        "stop": False,
        "command_count": 0,
        "last_command": None,
        "online_app": None,
        "online_target_app": None,
        "timeout_profile": None,
    }


def _appdomain():
    """The current AppDomain, or None when not running inside CODESYS."""
    if _DOMAIN_OVERRIDE is not None:
        return _DOMAIN_OVERRIDE
    try:
        import System

        return System.AppDomain.CurrentDomain
    except Exception:
        return None


def set_appdomain_for_tests(domain):
    """Inject a fake domain (``None`` restores the real lookup)."""
    global _DOMAIN_OVERRIDE
    _DOMAIN_OVERRIDE = domain


def reset_for_tests():
    """Forget the fake domain and the fallback state."""
    global _DOMAIN_OVERRIDE
    _DOMAIN_OVERRIDE = None
    _FALLBACK_STATE.clear()


def load_state():
    """The one daemon state for this CODESYS process.

    Returns the dict stored in the AppDomain, creating and storing it on the
    first call.  A domain call that fails, or answers with something that is
    not a dict (the offline CLR stub returns a dummy object), degrades to the
    module-level fallback instead of raising into the daemon start.
    """
    domain = _appdomain()
    if domain is None:
        return _FALLBACK_STATE

    try:
        state = domain.GetData(ANCHOR_KEY)
    except Exception:
        return _FALLBACK_STATE
    if isinstance(state, dict):
        return state

    # Absent, or a payload we did not put there (the offline CLR stub answers
    # with a dummy object): ours replaces it.
    state = _default_state()
    try:
        domain.SetData(ANCHOR_KEY, state)
    except Exception:
        return _FALLBACK_STATE
    return state


def next_generation(state):
    """Start a new generation and stamp it on the state."""
    try:
        generation = int(state.get("generation") or 0) + 1
    except (TypeError, ValueError):
        generation = 1
    state["generation"] = generation
    state["stop"] = False
    return generation


def is_current(state, generation):
    """True while ``generation`` is still the live one."""
    return state.get("generation") == generation and not state.get("stop")


def acquire_pipe_mutex(pipe_name):
    """Take the named mutex for ``pipe_name``.

    Returns ``(handle, error)``.  With the mutex free, ``handle`` is the live
    ``Mutex`` (the caller must keep the reference) and ``error`` is None.  With
    another process holding it, ``handle`` is None and ``error`` is a sentence
    naming the owner, to be shown in the IDE.

    A CLR that cannot do mutexes at all (offline tests, an exotic host) is not
    a reason to refuse to start: that returns ``(None, None)`` and the daemon
    runs unguarded, as it did before this module existed.
    """
    name = MUTEX_PREFIX + str(pipe_name)
    try:
        from System.Threading import Mutex
    except Exception:
        return None, None

    try:
        mutex = Mutex(False, name)
    except Exception:
        return None, None

    try:
        if mutex.WaitOne(0):
            return mutex, None
    except Exception:
        return None, None

    try:
        mutex.Close()
    except Exception:
        pass
    return None, _owner_sentence()


def release_mutex(handle):
    """Release and close a mutex taken by ``acquire_pipe_mutex``.  Safe twice."""
    if handle is None:
        return
    try:
        handle.ReleaseMutex()
    except Exception:
        pass
    try:
        handle.Close()
    except Exception:
        pass


def _owner_sentence():
    """Name the process that already owns the pipe, when the marker says so."""
    other = other_daemon_info()
    if other:
        return (
            "Daemon is already running in another CODESYS process (pid {0}"
            "{1}). Stop it there first.".format(
                other.get("pid", "?"),
                ", since " + str(other["started_at"]) if other.get("started_at") else "",
            )
        )
    return (
        "Daemon is already running in another CODESYS process on this pipe "
        "(pid unknown). Stop it there first."
    )


def other_daemon_info():
    """``{pid, started_at}`` of the process holding the pipe, or None.

    Read from the liveness marker, which is also how the CLI tells a live
    daemon from a stale one; a missing or partial marker simply answers None.
    """
    try:
        import json

        from ide_daemon_state import STATUS_FILE

        with open(STATUS_FILE, "r") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    info = {"pid": payload.get("pid")}
    started = payload.get("started_ts")
    if started:
        try:
            import time as _time

            info["started_at"] = _time.strftime(
                "%Y-%m-%d %H:%M:%S", _time.localtime(float(started))
            )
        except Exception:
            pass
    return info
