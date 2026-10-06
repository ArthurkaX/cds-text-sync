# -*- coding: utf-8 -*-
"""
test_cli_wait_ready.py — the client-side PLC readiness wait.

A download finishing is not the application running; the live run read a
variable 2 s after the download while the program started 2 s after that. The
wait lives in the client (separate short requests, IDE idle in between), never
inside the daemon -- a wait there blocks the IDE's single UI thread.

These tests drive ``wait_for_ready`` with a fake daemon, a fake clock and a fake
sleep, so the whole budget is exercised without real time passing.
"""

import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_cli import _cli_ready as ready


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSleep:
    """Sleeping advances the fake clock; no real time passes."""

    def __init__(self, clock):
        self.clock = clock
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)
        self.clock.advance(seconds)


def _drive(send, timeout=30.0, ready_var="", poll_interval=0.5):
    clock = FakeClock()
    sleeper = FakeSleep(clock)
    result = ready.wait_for_ready(
        send,
        timeout=timeout,
        ready_var=ready_var,
        poll_interval=poll_interval,
        sleep=sleeper,
        clock=clock,
    )
    return result, clock, sleeper


def _status(running=True, state="run", ok=True):
    return {
        "ok": ok,
        "data": {"plc": {"running": running, "application_state": state}},
        "error": None if ok else "boom",
    }


def test_ready_at_once_when_the_application_already_runs():
    calls = []

    def send(method, params):
        calls.append(method)
        return _status(running=True, state="run")

    result, _clock, _ = _drive(send)

    assert result["ready"] is True
    assert result["ready_after_s"] == 0.0
    assert result["checks"] == 1
    assert calls == ["status"]


def test_waits_until_the_application_reaches_run():
    states = [_status(False, "stop"), _status(False, "none"), _status(True, "run")]

    def send(method, params):
        return states.pop(0)

    result, _clock, _ = _drive(send, poll_interval=1.0)

    assert result["ready"] is True
    assert result["checks"] == 3
    assert result["ready_after_s"] == 2.0  # two polls slept one second each


def test_an_application_that_never_runs_reports_the_last_state():
    def send(method, params):
        return _status(False, "stop")

    result, _, _ = _drive(send, timeout=3.0, poll_interval=1.0)

    assert result["ready"] is False
    assert "did not reach run within 3s" in result["reason"]
    assert "stop" in result["reason"]


def test_the_ready_var_must_change_between_two_reads():
    reads = iter(["INT#1", "INT#1", "INT#2"])

    def send(method, params):
        if method == "read_variable":
            return {"ok": True, "data": {"value": next(reads)}}
        return _status(running=True)

    result, _, _ = _drive(send, ready_var="GVL_Bench.nHeartbeat", poll_interval=1.0)

    assert result["ready"] is True
    assert result["ready_var"] == "GVL_Bench.nHeartbeat"
    assert result["value"] == "INT#2"


def test_a_ready_var_that_never_changes_reports_the_value():
    def send(method, params):
        if method == "read_variable":
            return {"ok": True, "data": {"value": "INT#7"}}
        return _status(running=True)

    result, _, _ = _drive(
        send, timeout=3.0, ready_var="GVL_Bench.nHeartbeat", poll_interval=1.0
    )

    assert result["ready"] is False
    assert "did not change" in result["reason"]
    assert "INT#7" in result["reason"]


def test_a_ready_var_that_cannot_be_read_is_not_ready():
    def send(method, params):
        if method == "read_variable":
            return {"ok": False, "error": "not exported"}
        return _status(running=True)

    result, _, _ = _drive(send, timeout=2.0, ready_var="GVL_Bench.nHeartbeat")

    assert result["ready"] is False
    assert "could not be read" in result["reason"]


def test_a_daemon_error_is_retried_and_named_in_the_reason():
    calls = []

    def send(method, params):
        calls.append(method)
        raise RuntimeError("daemon busy with build")

    result, _, _ = _drive(send, timeout=2.0, poll_interval=1.0)

    assert result["ready"] is False
    assert len(calls) > 1  # retried, not fatal
    assert "daemon busy with build" in result["reason"]


def test_an_error_response_is_named_not_read_as_offline():
    def send(method, params):
        return {"ok": False, "error": "application state error: no device"}

    result, _, _ = _drive(send, timeout=1.0, poll_interval=1.0)

    assert result["ready"] is False
    assert "no device" in result["reason"]


def test_each_poll_is_its_own_request():
    """The IDE is idle between the polls; that is the whole point."""
    methods = []

    def send(method, params):
        methods.append(method)
        if method == "read_variable":
            return {"ok": True, "data": {"value": "1"}}
        return _status(running=True)

    _drive(send, timeout=2.0, ready_var="HB", poll_interval=1.0)

    assert methods == [
        "status",
        "read_variable",
        "status",
        "read_variable",
        "status",
        "read_variable",
    ]


@pytest.mark.parametrize(
    "plc,expected",
    [
        ({"running": True, "application_state": "stop"}, True),
        ({"running": False, "application_state": "run"}, True),
        ({"running": False, "application_state": "stop"}, False),
        ({"running": None, "application_state": "running"}, True),
        ({"running": None, "application_state": "none"}, False),
        ({"running": None, "application_state": ""}, False),
        (None, False),
        ({}, False),
    ],
)
def test_application_running_never_assumes(plc, expected):
    assert ready.application_running(plc) is expected


def test_the_readiness_requests_are_short(monkeypatch):
    """One stuck poll must not hold the whole budget in a single request."""
    from cds_cli import _cli_handlers_daemon as d

    timeouts = []

    def _fake_send(method, params=None, timeout=15):
        timeouts.append((method, timeout))
        return {"ok": True, "data": {"plc": {"running": True}}}

    monkeypatch.setattr(d, "send_command_reverse", _fake_send)

    result = d._wait_for_ready(
        type("A", (), {"ready_timeout": 30.0, "ready_var": ""})()
    )

    assert result["ready"] is True
    assert timeouts == [("status", ready.STATUS_REQUEST_TIMEOUT_S)]
    assert ready.STATUS_REQUEST_TIMEOUT_S <= 15


def test_download_readiness_does_not_inherit_the_command_timeout(monkeypatch):
    """--timeout bounds the download call, not the wait: a long download must
    not silently become a long readiness budget."""
    from cds_cli import _cli_handlers_daemon as d

    seen = {}

    def _fake_wait(send, timeout=None, ready_var=""):
        seen["timeout"] = timeout
        return {"ready": True, "ready_after_s": 0.0, "checks": 1}

    monkeypatch.setattr(d._cli_ready, "wait_for_ready", _fake_wait)

    d._wait_for_ready(
        type("A", (), {"ready_timeout": None, "timeout": 600.0, "ready_var": ""})()
    )

    assert seen["timeout"] is None  # -> defaults to 30s, not 600s
