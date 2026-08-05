# -*- coding: utf-8 -*-
"""
test_online_session_guard.py — Reading PLC data must never open a session itself.

Building an online session means ``create_online_application`` followed by
``_ensure_logged_in``, which walks a list of candidates calling
``online_app.login()`` on each. Every candidate has to fail before the call
returns, and the single-threaded daemon loop serves nothing meanwhile — no
timeout inside the IDE cuts it short. Measured live at ~145 s against a project
with compile errors, after which the read failed anyway; commands issued during
that window time out, so the daemon looks dead rather than busy.

So the data plane (read/write of variables) may only *use* a session that
already exists. Opening one is what ``connect_to_device`` is for, where the user
asked for it and the wait is the point.
"""

from __future__ import annotations

import dis
import importlib.util
import sys
from pathlib import Path

import pytest

BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)
STATE_KEY = "_codesys_daemon_loop"

# Variable read/write. These run on every `cts read` / `cts write` and must not
# be able to open a session. connect_to_device_impl and download_impl are
# deliberately absent: connecting is their whole purpose.
DATA_PLANE = [
    "read_variable_impl",
    "write_variable_impl",
    "read_variables_impl",
    "write_variables_impl",
]


@pytest.fixture(scope="module")
def helpers():
    """Import ide_online_helpers under CPython (its module level is stdlib-only)."""
    spec = importlib.util.spec_from_file_location(
        "ide_online_helpers", BRIDGE_DIR / "ide_online_helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_daemon_state():
    """Keep the fake daemon state out of the real sys namespace between tests."""
    saved = getattr(sys, STATE_KEY, None)
    if hasattr(sys, STATE_KEY):
        delattr(sys, STATE_KEY)
    yield
    if saved is None:
        if hasattr(sys, STATE_KEY):
            delattr(sys, STATE_KEY)
    else:
        setattr(sys, STATE_KEY, saved)


def _global_names(func):
    """Every global the function can reach, including nested closures."""
    names = set()
    todo = [func.__code__]
    while todo:
        code = todo.pop()
        for instruction in dis.get_instructions(code):
            if instruction.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                names.add(instruction.argval)
        todo.extend(c for c in code.co_consts if hasattr(c, "co_code"))
    return names


# ---------------------------------------------------------------------------
# Static guard — the important one. It survives refactors of the runtime code.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", DATA_PLANE)
def test_data_plane_never_opens_a_session(helpers, name):
    reached = _global_names(getattr(helpers, name))
    assert "ensure_online_connection" not in reached, (
        "{0} can open an online session. Creating one blocks the daemon loop "
        "for as long as the login candidates take to fail — ~145 s measured. "
        "Use require_online_session instead.".format(name)
    )


@pytest.mark.parametrize("name", DATA_PLANE)
def test_data_plane_requires_an_existing_session(helpers, name):
    assert "require_online_session" in _global_names(getattr(helpers, name))


def test_connect_may_still_open_a_session(helpers):
    """The guard must not have been applied so widely that connecting broke."""
    assert "ensure_online_connection" in _global_names(
        helpers.connect_to_device_impl
    )


# ---------------------------------------------------------------------------
# Behaviour of the guard itself
# ---------------------------------------------------------------------------


def test_refuses_when_daemon_state_is_absent(helpers):
    with pytest.raises(RuntimeError) as excinfo:
        helpers.require_online_session(project=object())
    assert "cts connect" in str(excinfo.value)


def test_refuses_when_no_session_is_cached(helpers):
    setattr(sys, STATE_KEY, {"online_app": None, "online_target_app": None})
    with pytest.raises(RuntimeError) as excinfo:
        helpers.require_online_session(project=object())
    assert "cts connect" in str(excinfo.value)


def test_returns_the_cached_session(helpers):
    class _OnlineApp:
        is_connected = True

    online_app = _OnlineApp()
    setattr(
        sys,
        STATE_KEY,
        {"online_app": online_app, "online_target_app": object()},
    )
    assert helpers.require_online_session(project=object()) is online_app


def test_refuses_when_the_cached_session_went_stale(helpers):
    """A dead session must be refused, not handed out and used."""

    class _DeadApp:
        @property
        def is_connected(self):
            raise RuntimeError("underlying online application is gone")

    setattr(
        sys,
        STATE_KEY,
        {"online_app": _DeadApp(), "online_target_app": object()},
    )
    with pytest.raises(RuntimeError) as excinfo:
        helpers.require_online_session(project=object())
    assert "cts connect" in str(excinfo.value)
