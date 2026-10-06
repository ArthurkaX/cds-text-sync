# -*- coding: utf-8 -*-
"""
test_live_plc_state.py — the PLC state must be answered live, not from cache.

Two live failures, one cause. ``cts status`` / ``cts ping`` kept reporting
``online: True / run`` minutes after the user did Online -> Logout, because
the snapshot read the daemon's cached wrapper. And an empty cache reported
``offline`` while the IDE *was* online, so two ``cts import --save`` slipped
through the "do not edit while online" rule. Both read the cache; neither
asked the IDE.

``ide_online_helpers.live_online_state`` builds a fresh wrapper (never logs in)
and reports ``online`` / ``known`` / ``source`` / ``age_s``. The edit guard
treats ``known is False`` as "possibly online" and refuses.
"""

from __future__ import print_function

import importlib
import os
import sys
from types import SimpleNamespace

import pytest

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

STATE_KEY = "_codesys_daemon_loop"


@pytest.fixture(autouse=True)
def _clean_state():
    saved = getattr(sys, STATE_KEY, None)
    if hasattr(sys, STATE_KEY):
        delattr(sys, STATE_KEY)
    yield
    if saved is None:
        if hasattr(sys, STATE_KEY):
            delattr(sys, STATE_KEY)
    else:
        setattr(sys, STATE_KEY, saved)


@pytest.fixture
def helpers():
    module = importlib.import_module("ide_online_helpers")
    module._LIVE_MEMO.update(
        {"at": 0.0, "online": None, "known": False, "owner": None,
         "adopted": False, "pid": 0, "project_id": None}
    )
    return module


class _Wrapper(object):
    def __init__(self, connected=None, app_state=None):
        if connected is not None:
            self.is_connected = connected
        if app_state is not None:
            self.application_state = app_state


def _project(app):
    return SimpleNamespace(active_application=app)


def _install_scriptengine(monkeypatch, wrapper):
    monkeypatch.setitem(
        sys.modules,
        "scriptengine",
        SimpleNamespace(
            online=SimpleNamespace(create_online_application=lambda app: wrapper)
        ),
    )


# ── the logout case: a stale cache must not survive a live probe ────────────


def test_a_stale_cache_is_dropped_when_the_ide_logged_out(helpers, monkeypatch):
    stale = _Wrapper(connected=True, app_state="run")
    app = object()
    sys._codesys_daemon_loop = {
        "online_app": stale,
        "online_target_app": app,
        "projects": SimpleNamespace(primary=_project(app)),
    }
    # The IDE is really offline now: a fresh wrapper says so.
    _install_scriptengine(monkeypatch, _Wrapper(connected=False))

    state = helpers.live_online_state(_project(app))

    assert state["online"] is False
    assert state["known"] is True
    assert state["source"] == "live"
    assert sys._codesys_daemon_loop["online_app"] is None


# ── the slipped-through case: a UI session the daemon never cached ─────────


def test_a_ui_session_is_found_live_and_reported_as_adopted(helpers, monkeypatch):
    sys._codesys_daemon_loop = {"projects": SimpleNamespace(primary=_project(object()))}
    app = object()
    _install_scriptengine(monkeypatch, _Wrapper(connected=True, app_state="run"))

    state = helpers.live_online_state(_project(app))

    assert state["online"] is True
    assert state["known"] is True
    assert state["adopted"] is True
    assert state["owner"] == "ide"
    assert sys._codesys_daemon_loop["online_app"] is not None


def test_a_session_this_daemon_logged_in_is_owned_by_cts(helpers):
    sys._codesys_daemon_loop = {}
    helpers.cache_online_app(_Wrapper(connected=True), object(), owner="cts")
    assert helpers.session_owner() == "cts"


def test_clearing_the_cache_forgets_the_owner(helpers):
    sys._codesys_daemon_loop = {}
    helpers.cache_online_app(_Wrapper(connected=True), object(), owner="cts")
    helpers.clear_cached_online_app()
    assert helpers.session_owner() is None


# ── unknown must stay unknown ──────────────────────────────────────────────


def test_unknown_when_no_wrapper_can_be_built(helpers, monkeypatch):
    # An application exists (so it could be online) but the ScriptEngine
    # cannot build a wrapper for it: that is unknown, not offline.
    app = object()
    sys._codesys_daemon_loop = {}
    monkeypatch.setattr(helpers, "get_active_application", lambda project: app)
    monkeypatch.setitem(sys.modules, "scriptengine", SimpleNamespace())

    state = helpers.live_online_state(object())

    assert state["online"] is None
    assert state["known"] is False
    assert state["source"] == "unknown"
    assert state["age_s"] is None


def test_no_active_application_is_a_definite_offline(helpers, monkeypatch):
    """Nothing to log in to -> offline, so an offline edit is not blocked."""
    sys._codesys_daemon_loop = {}
    monkeypatch.setattr(helpers, "get_active_application", lambda project: None)
    monkeypatch.setitem(sys.modules, "scriptengine", SimpleNamespace())

    state = helpers.live_online_state(object())

    assert state["online"] is False
    assert state["known"] is True


def test_an_unreadable_cached_handle_keeps_the_answer_unknown(helpers, monkeypatch):
    """A cached wrapper whose flags all raise might still be live: fail closed."""
    sys._codesys_daemon_loop = {"online_app": object(), "online_target_app": object()}
    monkeypatch.setattr(helpers, "get_active_application", lambda project: None)
    monkeypatch.setitem(sys.modules, "scriptengine", SimpleNamespace())

    state = helpers.live_online_state(object())

    assert state["online"] is None
    assert state["known"] is False


def test_probe_online_state_returns_the_live_pair(helpers, monkeypatch):
    app = object()
    sys._codesys_daemon_loop = {}
    _install_scriptengine(monkeypatch, _Wrapper(connected=True))
    assert helpers.probe_online_state(_project(app)) == (True, True)


# ── the short memo is used only when asked for ─────────────────────────────


def test_the_memo_answers_a_second_call_and_reports_it_as_cached(helpers, monkeypatch):
    app = object()
    proj = _project(app)
    sys._codesys_daemon_loop = {"projects": SimpleNamespace(primary=proj)}
    _install_scriptengine(monkeypatch, _Wrapper(connected=True))

    first = helpers.live_online_state(proj, max_age_s=5.0)
    second = helpers.live_online_state(proj, max_age_s=5.0)

    assert first["source"] == "live"
    assert second["source"] == "cached"
    assert isinstance(second["age_s"], int)


def test_a_zero_max_age_always_probes_live(helpers, monkeypatch):
    app = object()
    proj = _project(app)
    sys._codesys_daemon_loop = {"projects": SimpleNamespace(primary=proj)}
    _install_scriptengine(monkeypatch, _Wrapper(connected=True))

    helpers.live_online_state(proj, max_age_s=5.0)
    assert helpers.live_online_state(proj)["source"] == "live"


# ── the daemon snapshot carries the live answer and its provenance ─────────


def test_the_status_snapshot_reports_a_live_source(helpers, monkeypatch):
    import ide_daemon_state

    sys._codesys_daemon_loop = {"projects": SimpleNamespace(primary=None)}
    helpers.cache_online_app(_Wrapper(connected=True, app_state="run"), object(), owner="ide")

    snapshot = ide_daemon_state._get_plc_status_snapshot()

    assert snapshot["online"] is True
    assert snapshot["source"] == "live"
    assert isinstance(snapshot["age_s"], float)
    assert snapshot["owner"] == "ide"


# ── the CLI renders source and age in the [ctx] line ───────────────────────


def test_cli_renders_a_live_reading():
    from cds_cli._cli_io import _context_line

    line = _context_line({
        "project": "P", "ide": "ide-1", "edits_allowed": True,
        "plc": {"online": False, "state": "stop", "source": "live", "age_s": 0.2},
    })
    assert line == "[ctx] project=P ide=ide-1 plc=offline/stop (live, 0.2s) edits=allowed"


def test_cli_renders_a_cached_reading_with_age():
    from cds_cli._cli_io import _context_line

    line = _context_line({
        "project": "P", "ide": "ide-1", "edits_allowed": False,
        "plc": {"online": True, "state": "run", "source": "cached", "age_s": 140},
    })
    assert "plc=online/run (cached, 140s ago)" in line


def test_cli_says_when_a_session_was_adopted():
    from cds_cli._cli_io import _context_line

    line = _context_line({
        "project": "P", "ide": "ide-1", "edits_allowed": False,
        "plc": {"online": True, "state": "run", "source": "live", "age_s": 0.1,
                "owner": "ide", "adopted": True},
    })
    assert "adopted" in line
    assert "ide" in line


def test_cli_omits_the_suffix_when_the_daemon_sends_no_source():
    from cds_cli._cli_io import _context_line

    line = _context_line({
        "project": "P", "ide": "ide-1", "edits_allowed": True,
        "plc": {"online": False, "state": "stop"},
    })
    assert line == "[ctx] project=P ide=ide-1 plc=offline/stop edits=allowed"
