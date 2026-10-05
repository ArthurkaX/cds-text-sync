# -*- coding: utf-8 -*-
"""
test_app_state_cache.py — `cts app-state` must not cache a handle it is not using.

Live, `cts app-state` against an unreachable PLC (ping: "Destination host
unreachable") reported ``application_state: "none"`` -- yet the context block
that followed said ``online: true`` and every edit was refused. The handler
built a ScriptEngine handle with ``create_online_application`` and cached it
unconditionally; ``create_online_application`` builds a handle, it does not log
in. The status snapshot then read the handle's missing ``is_connected`` as
``true`` by default.

The handler now caches only a handle that is really logged in, with the same
predicate the guard uses, so a blind probe leaves the cache empty and the
context reports ``null`` rather than a false ``true``.
"""

from __future__ import print_function

import importlib
import os
import sys

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
def _clean_daemon_state():
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
    return importlib.import_module("ide_online_helpers")


class _Wrapper(object):
    """A ScriptEngine online application stand-in."""

    def __init__(self, connected=None, app_state=""):
        if connected is not None:
            self.is_connected = connected
        self.application_state = app_state


def _install_state(monkeypatch, helpers, wrapper, app):
    """The handler's world: a project, one application, one created handle."""
    sys._codesys_daemon_loop = {
        "projects": type("P", (), {"primary": type("Pr", (), {"active_application": app})()}),
    }
    monkeypatch.setitem(
        sys.modules,
        "scriptengine",
        type("se", (), {"online": type("o", (), {
            "create_online_application": staticmethod(lambda a: wrapper),
        })}),
    )
    return importlib.import_module("ide_handlers_project")


# ── the helper ─────────────────────────────────────────────────────────────


def test_cache_if_live_refuses_an_unlogged_handle(helpers):
    sys._codesys_daemon_loop = {}
    assert helpers.cache_if_live(_Wrapper(), object()) is False
    assert sys._codesys_daemon_loop.get("online_app") is None


def test_cache_if_live_keeps_a_logged_in_handle(helpers):
    sys._codesys_daemon_loop = {}
    app = object()
    wrapper = _Wrapper(connected=True)
    assert helpers.cache_if_live(wrapper, app) is True
    assert sys._codesys_daemon_loop["online_app"] is wrapper
    assert sys._codesys_daemon_loop["online_target_app"] is app


def test_cache_if_live_accepts_a_run_state_without_flags(helpers):
    """Some SP22 wrappers expose only application_state -- the guard's rule."""
    sys._codesys_daemon_loop = {}
    assert helpers.cache_if_live(_Wrapper(app_state="run"), object()) is True


# ── the handler: an unreachable PLC must not poison the cache ───────────────


def test_app_state_does_not_cache_a_dead_handle(monkeypatch, helpers):
    app = object()
    handlers = _install_state(monkeypatch, helpers, _Wrapper(app_state="none"), app)

    response = handlers._cmd_application_state()

    assert response["ok"] is True
    assert sys._codesys_daemon_loop.get("online_app") is None


def test_app_state_caches_a_live_handle(monkeypatch, helpers):
    app = object()
    handlers = _install_state(monkeypatch, helpers, _Wrapper(connected=True), app)

    handlers._cmd_application_state()

    assert sys._codesys_daemon_loop.get("online_app") is not None


def test_the_status_snapshot_stays_unknown_after_a_blind_app_state(
    monkeypatch, helpers
):
    """The live bug: app-state alone must not make the snapshot online."""
    app = object()
    handlers = _install_state(monkeypatch, helpers, _Wrapper(app_state="none"), app)
    handlers._cmd_application_state()

    import ide_daemon_state

    assert ide_daemon_state._get_plc_status_snapshot()["online"] is None
