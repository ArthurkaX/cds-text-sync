# -*- coding: utf-8 -*-
"""ide_response_context.py -- the compact "where am I" block on every response.

An agent that knows cts only from its help often cannot tell which project it
is talking to, or that the IDE is still logged in to the PLC and therefore
refusing edits. The refusal tells it, but only after it tried. This module
builds a small ``context`` block -- project, IDE id, PLC state, whether edits
are allowed -- and the reverse-pipe loop attaches it to every command response
next to the existing ``instance``.

Cheap by construction: it reads only the daemon's cached state (the same
snapshot ``cts ping`` reports) and never opens a session, logs in or touches
the PLC. When the state is not known, it says so -- ``online: null`` plus a
hint -- rather than waiting.

IronPython 2.7: no f-strings, no annotations, no pathlib.
"""

from __future__ import print_function

import collections
import sys
import time

from ide_daemon_state import _get_plc_status_snapshot, _instance_info, wire

_DAEMON_STATE_KEY = "_codesys_daemon_loop"

# First time this process saw the currently cached online wrapper; the age of
# a cached PLC view is the age of the handle it was read from. Keyed on the
# handle itself, so connect/disconnect/reconnect resets it while a long-lived
# session keeps accruing age -- which is the point of reporting it.
_seen_session = {"handle": None, "at": 0.0}


def _state():
    return getattr(sys, _DAEMON_STATE_KEY, None) or {}


def _project_block(instance_info):
    """``{name, path, sync_folder}`` or None, from the instance descriptor."""
    project = instance_info.get("project") if isinstance(instance_info, dict) else None
    if not isinstance(project, dict) or not project.get("name"):
        return None
    return project


def _plc_block(snapshot):
    """``{online, state, application}`` from the cached PLC snapshot."""
    online = snapshot.get("online")
    state = snapshot.get("application_state") or ""
    if not state:
        running = snapshot.get("running")
        if running is True:
            state = "run"
        elif running is False:
            state = "stop"
    return {
        "online": online,
        "state": state,
        "application": snapshot.get("application", "") or "",
    }


def _age_seconds(online_app, now):
    """Seconds the reported PLC view has been the daemon's view of things.

    With a cached wrapper it is the age of that handle (reset when the handle
    changes). With none, it is how long the daemon has run without a session --
    the age of "we do not know". None only when even the start time is unset.
    """
    if online_app is not None:
        if _seen_session["handle"] is not online_app:
            _seen_session["handle"] = online_app
            _seen_session["at"] = now
        return int(max(0.0, now - _seen_session["at"]))
    started = _state().get("started_ts")
    if started:
        return int(max(0.0, now - started))
    return None


def _edits_allowed(online):
    """Tri-state: True/False when the PLC state is known, else None.

    ``None`` is not "no": live, the daemon reported ``edits_allowed: true``
    with ``plc.online: null`` while an edit was refused, because the IDE was
    online and the daemon simply had no cached handle. "Unknown" is the honest
    answer, so an agent does not read permission into a blind spot.
    """
    if online is True:
        return False
    if online is False:
        return True
    return None


def _hint(project_name, online):
    """``(hint, hint_short)`` for the one thing worth saying, else (None, None)."""
    if not project_name:
        return (
            "No project is open in the IDE; project-scoped commands will fail.",
            "cts project-open",
        )
    if online is True:
        return (
            "The IDE is online with the PLC; project edits are refused. "
            "Run cts disconnect, then repeat the command.",
            "cts disconnect",
        )
    if online is None:
        return (
            "The daemon holds no cached PLC session; the IDE may still be "
            "online. An edit can still be refused.",
            "cts disconnect",
        )
    return None, None


def build_context(instance_info=None):
    """The context block for one response; see the module docstring."""
    state = _state()
    if instance_info is None:
        instance_info = _instance_info()
    snapshot = _get_plc_status_snapshot()
    project = _project_block(instance_info)
    project_name = project["name"] if project else None
    online = snapshot.get("online")
    hint, hint_short = _hint(project_name, online)

    context = collections.OrderedDict()
    context["project"] = project_name
    context["ide"] = instance_info.get("id") if isinstance(instance_info, dict) else None
    context["plc"] = _plc_block(snapshot)
    context["edits_allowed"] = _edits_allowed(online)
    if hint:
        context["hint"] = hint
        context["hint_short"] = hint_short
    context["age_s"] = _age_seconds(state.get("online_app"), time.time())
    return context


def attach_response_metadata(response, request_id=None):
    """Add ``instance``, ``context`` (and the request id) to a response.

    The one place the loop decorates an envelope, so ``context`` cannot drift
    from ``instance`` or be attached to only some commands. Non-dict responses
    are returned untouched. ``request_id`` is echoed only when the caller sent
    one, keeping the frame byte-identical for an older CLI.
    """
    if not isinstance(response, dict):
        return response
    instance = _instance_info()
    response["instance"] = instance
    response["context"] = build_context(instance)
    if request_id:
        response[wire.REQUEST_ID_KEY] = request_id
    return response


__all__ = ["build_context", "attach_response_metadata"]
