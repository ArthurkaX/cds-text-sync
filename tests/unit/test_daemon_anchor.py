# -*- coding: utf-8 -*-
"""
test_daemon_anchor.py — the daemon's process-wide anchor.

Every Execute Script gets a fresh IronPython runtime, so a daemon that keeps
its state in ``sys`` is invisible to the next run of Project_daemon.py: that is
how three daemons ended up polling one pipe.  The anchor keeps the state in the
AppDomain instead (verified live to survive a script restart), and the named
mutex extends the same "one daemon" rule to a second CODESYS process.

These tests drive the anchor through a fake AppDomain and a fake mutex; the
loop-level behaviour (confirm before stopping, refusal on a busy mutex) is
pinned in test_timer_daemon.py, next to the timer harness it needs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parent.parent.parent
_IDE_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_IDE_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_IDE_BRIDGE))

sys.modules.pop("ide_daemon_anchor", None)
import ide_daemon_anchor as anchor  # noqa: E402

import ide_daemon_state  # noqa: E402


class FakeDomain:
    """The two AppDomain members the anchor uses."""

    def __init__(self):
        self.data = {}

    def GetData(self, key):
        return self.data.get(key)

    def SetData(self, key, value):
        self.data[key] = value


class _Dummy:
    """What the offline CLR stub hands back: callable, not a dict."""

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self


class FakeMutex:
    """A named mutex whose ownership the test decides."""

    def __init__(self, busy):
        self.busy = busy
        self.released = 0
        self.closed = 0

    def WaitOne(self, timeout):
        return not self.busy

    def ReleaseMutex(self):
        self.released += 1

    def Close(self):
        self.closed += 1


def test_state_survives_a_second_script_run(monkeypatch):
    """The whole point: run two, the second sees the first one's state."""
    domain = FakeDomain()
    anchor.set_appdomain_for_tests(domain)
    try:
        first = anchor.load_state()
        first["timer"] = "the-first-timer"

        second = anchor.load_state()

        assert second is first
        assert second["timer"] == "the-first-timer"
    finally:
        anchor.reset_for_tests()


def test_state_carries_the_keys_the_loop_keeps(monkeypatch):
    domain = FakeDomain()
    anchor.set_appdomain_for_tests(domain)
    try:
        state = anchor.load_state()
        for key in ("running", "timer", "pid", "started_at", "stop", "generation"):
            assert key in state
        assert state["generation"] == 0
    finally:
        anchor.reset_for_tests()


def test_a_non_dict_domain_payload_is_replaced(monkeypatch):
    """The offline CLR stub answers with a dummy object, not a dict."""
    domain = FakeDomain()
    domain.SetData(anchor.ANCHOR_KEY, _Dummy())
    anchor.set_appdomain_for_tests(domain)
    try:
        state = anchor.load_state()
        assert isinstance(state, dict)
        assert domain.GetData(anchor.ANCHOR_KEY) is state
    finally:
        anchor.reset_for_tests()


def test_without_a_domain_the_fallback_dict_is_used(monkeypatch):
    anchor.set_appdomain_for_tests(None)
    monkeypatch.setattr(anchor, "_appdomain", lambda: None)
    try:
        state = anchor.load_state()
        assert state is anchor.load_state()
        assert isinstance(state, dict)
    finally:
        anchor.reset_for_tests()


def test_each_start_bumps_the_generation():
    state = {}
    assert anchor.next_generation(state) == 1
    assert anchor.next_generation(state) == 2
    assert state["generation"] == 2


def test_generation_is_current_until_the_next_one_or_a_stop():
    state = {}
    generation = anchor.next_generation(state)
    assert anchor.is_current(state, generation) is True

    anchor.next_generation(state)
    assert anchor.is_current(state, generation) is False

    state["stop"] = True
    assert anchor.is_current(state, state["generation"]) is False


def test_a_broken_generation_field_does_not_raise():
    state = {"generation": "not a number"}
    assert anchor.next_generation(state) == 1


def test_a_free_mutex_is_taken_and_kept():
    created = {}

    class _Threading(ModuleType):
        def __getattr__(self, name):
            def _factory(initially_owned, name_):
                created["name"] = name_
                return FakeMutex(busy=False)

            return _factory

    saved = sys.modules.get("System.Threading")
    sys.modules["System.Threading"] = _Threading("System.Threading")
    try:
        handle, error = anchor.acquire_pipe_mutex("cds-cli-test")
        assert error is None
        assert isinstance(handle, FakeMutex)
        assert created["name"] == anchor.MUTEX_PREFIX + "cds-cli-test"
    finally:
        if saved is None:
            sys.modules.pop("System.Threading", None)
        else:
            sys.modules["System.Threading"] = saved


def test_a_busy_mutex_refuses_and_names_the_owner(monkeypatch, tmp_path):
    class _Threading(ModuleType):
        def __getattr__(self, name):
            def _factory(initially_owned, name_):
                return FakeMutex(busy=True)

            return _factory

    status = tmp_path / "cds-daemon-status.json"
    status.write_text('{"pid": 4242, "state": "idle", "started_ts": 1000}')
    monkeypatch.setattr(ide_daemon_state, "STATUS_FILE", str(status))

    saved = sys.modules.get("System.Threading")
    sys.modules["System.Threading"] = _Threading("System.Threading")
    try:
        handle, error = anchor.acquire_pipe_mutex("cds-cli-test")
    finally:
        if saved is None:
            sys.modules.pop("System.Threading", None)
        else:
            sys.modules["System.Threading"] = saved

    assert handle is None
    assert "already running" in error
    assert "4242" in error


def test_a_missing_clr_does_not_block_the_daemon():
    """No mutex support at all degrades to the old unguarded start."""
    handle, error = anchor.acquire_pipe_mutex("cds-cli-test")
    assert handle is None
    assert error is None


def test_release_is_safe_twice_and_with_none():
    anchor.release_mutex(None)
    mutex = FakeMutex(busy=False)
    anchor.release_mutex(mutex)
    anchor.release_mutex(mutex)
    assert mutex.released == 2
    assert mutex.closed == 2
