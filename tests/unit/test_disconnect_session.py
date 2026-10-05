# -*- coding: utf-8 -*-
"""
test_disconnect_session.py — ``cts disconnect`` must end the real IDE session.

Live, the daemon adopted the session the IDE was already running and then
``cts disconnect`` answered ``{"state": "disconnected", "was_connected": true}``
three times while the IDE stayed online: the import that followed was refused by
the edit guard and ``cts app-state`` still showed ``online``. The command was
reporting the wrapper it cleared, not the session the PLC still had.

The fix is the same predicate the guard uses (``live_online_session``) to check
the state *after* the logout. The reply is the truth: ``online_after`` is always
present, and a session that survived the logout makes the command fail with a
message that finally tells the user to log out in CODESYS itself.
"""

from __future__ import print_function

import dis
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


class _OnlineApp(object):
    """A cached wrapper that stays online until ``logout`` flips the switch."""

    is_connected = True

    def __init__(self, logout_works=True, logout_raises=False):
        self.logout_calls = 0
        self.live = True
        self._logout_works = logout_works
        self._logout_raises = logout_raises

    def logout(self):
        self.logout_calls += 1
        if self._logout_raises:
            raise RuntimeError("logout refused")
        if self._logout_works:
            self.live = False


def _install(monkeypatch, helpers, app):
    """A live session that survives the logout exactly when the app says so."""
    monkeypatch.setattr(
        helpers, "live_online_session",
        lambda project: app if app.live else None,
    )


# ── the helper: the reply follows a real re-check ──────────────────────────


def test_logout_ends_the_session_and_the_reply_says_offline(helpers, monkeypatch):
    app = _OnlineApp(logout_works=True)
    _install(monkeypatch, helpers, app)

    result = helpers.disconnect_from_device_impl(object())

    assert app.logout_calls == 1
    assert result["state"] == "disconnected"
    assert result["was_connected"] is True
    assert result["online_after"] is False
    assert "warning" not in result


def test_a_logout_that_did_not_end_it_is_reported_not_hidden(helpers, monkeypatch):
    """The live bug: the wrapper was cleared, the IDE session was not."""
    app = _OnlineApp(logout_works=False)
    _install(monkeypatch, helpers, app)

    result = helpers.disconnect_from_device_impl(object())

    assert app.logout_calls == 1
    assert result["state"] == "still_online"
    assert result["online_after"] is True
    assert "Online -> Logout" in result["warning"]


def test_a_refused_logout_is_reported_alongside_a_live_session(helpers, monkeypatch):
    app = _OnlineApp(logout_raises=True, logout_works=False)
    _install(monkeypatch, helpers, app)

    result = helpers.disconnect_from_device_impl(object())

    assert result["logout_error"] == "logout refused"
    assert result["online_after"] is True


def test_nothing_to_disconnect_is_not_a_logout(helpers, monkeypatch):
    monkeypatch.setattr(helpers, "live_online_session", lambda project: None)

    result = helpers.disconnect_from_device_impl(object())

    assert result["was_connected"] is False
    assert result["online_after"] is False
    assert "already offline" in result["note"]


def test_the_cache_is_cleared_before_the_re_check(helpers, monkeypatch):
    """`online_after` must be asked of the IDE, not of the wrapper just cleared."""
    sys._codesys_daemon_loop = {
        "online_app": object(), "online_target_app": object(),
    }
    seen = {}

    def _live(project):
        seen["cache"] = sys._codesys_daemon_loop.get("online_app")
        return None

    monkeypatch.setattr(helpers, "live_online_session", _live)
    helpers.disconnect_from_device_impl(object())

    assert seen["cache"] is None


def test_disconnect_uses_the_guards_predicate(helpers):
    """One predicate, so "edits allowed" and "session gone" cannot disagree."""
    reached = set()
    todo = [helpers.disconnect_from_device_impl.__code__]
    while todo:
        code = todo.pop()
        for instruction in dis.get_instructions(code):
            if instruction.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                reached.add(instruction.argval)
        todo.extend(c for c in code.co_consts if hasattr(c, "co_code"))
    assert "live_online_session" in reached


# ── the command: a surviving session fails loudly ──────────────────────────


def _handler_module():
    return importlib.import_module("ide_handlers_project")


def test_the_command_fails_when_the_ide_is_still_online(monkeypatch):
    handlers = _handler_module()
    monkeypatch.setattr(handlers, "_invalidate_device_cache", lambda: None)
    monkeypatch.setattr(handlers, "_get_active_project", lambda: (object(), None))
    monkeypatch.setattr(
        handlers._helpers, "disconnect_from_device_impl",
        lambda project: {"state": "still_online", "online_after": True,
                         "warning": "Log out in CODESYS."},
    )

    response = handlers._cmd_disconnect_from_device()

    assert response["ok"] is False
    assert response["error"] == "Log out in CODESYS."
    assert response["data"]["online_after"] is True


def test_the_command_succeeds_when_the_session_is_really_gone(monkeypatch):
    handlers = _handler_module()
    monkeypatch.setattr(handlers, "_invalidate_device_cache", lambda: None)
    monkeypatch.setattr(handlers, "_get_active_project", lambda: (object(), None))
    monkeypatch.setattr(
        handlers._helpers, "disconnect_from_device_impl",
        lambda project: {"state": "disconnected", "online_after": False},
    )

    response = handlers._cmd_disconnect_from_device()

    assert response["ok"] is True
    assert response["data"]["online_after"] is False
