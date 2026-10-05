# -*- coding: utf-8 -*-
"""Characterization grid for ``ReversePipeClient.send_command``.

``send_command`` picks a target IDE, exchanges a hello with every daemon that
connects to the pipe, sends the command over the chosen connection and turns
every failure mode into a specific exception or CLI error.  The real transport
is Win32 named pipes and the real clock is wall time, so the test suite that
covers it (``tests/unit/test_reverse_pipe_client.py``) is skipped off Windows
and cannot pin the routing matrix at all.

This grid replaces every boundary with a scripted fake -- the pipe listener,
the session lock, the frame read/write, the process listing, the decision
function and the clock -- so the whole contract is pinned on any platform:

* which target PID is chosen and what ``decide`` is told,
* the hello/release exchange, including duplicates and legacy daemons,
* which connection the command goes out on, and in what order relative to
  releasing the session lock,
* the returned dict, verbatim,
* every exception and its message, including the request id appended to a
  timeout,
* the module globals left behind (``_resolved_pid``, ``_last_ide_pid``,
  ``_last_instance``), and
* the cleanup the ``finally`` performs on every path.

The fakes are deliberately dumb: they only replay what a test scripts, so a
failure means ``send_command`` changed behaviour rather than a fake changing
its mind.  Known oddities are pinned as-is (see the tests that name them);
they are described in the task report, not fixed here.
"""

from __future__ import annotations

import os

import pytest

from cds_text_sync.engine import reverse_pipe_client as rpc
from cds_text_sync.engine.pipe_targets import LEGACY, Decision, Hello, TargetError
from cts_shared import wire


# Module globals ``send_command`` reads or writes.  Reset before every test so
# one case cannot leak a resolved pid into the next.
_STATE_GLOBALS = (
    "_configured_target",
    "_configured_expect_project",
    "_resolved_pid",
    "_last_instance",
    "_last_ide_pid",
)


def hello_reply(pid, protocol=2, project=None, instance_id=None):
    """An H2 hello envelope, as the daemon writes it."""
    return {
        "ok": True,
        "hello": {
            "protocol": protocol,
            "id": instance_id or "ide-{0}".format(pid),
            "pid": pid,
            "version": "3.3.0",
            "poll_ms": 200,
            "project": project,
        },
    }


def hello(pid, project=None, protocol=2):
    return Hello(
        protocol=protocol,
        id="ide-{0}".format(pid),
        pid=pid,
        version="3.3.0",
        poll_ms=200,
        project=project,
    )


class _Clock:
    """A clock that only moves when a fake says so."""

    def __init__(self, now=1000.0):
        self.now = now

    def advance(self, seconds):
        self.now += seconds


class _FakeTime:
    """Stand-in for the stdlib ``time`` module inside the client module."""

    def __init__(self, clock, on_sleep=None):
        self._clock = clock
        self._on_sleep = on_sleep

    def monotonic(self):
        return self._clock.now

    def sleep(self, seconds):
        if self._on_sleep is not None:
            self._on_sleep(seconds)
        self._clock.advance(seconds)

    def strftime(self, fmt):
        return "120000"


class _FakeRandom:
    def __init__(self, value=0.05):
        self.value = value
        self.calls = []

    def uniform(self, low, high):
        self.calls.append((low, high))
        return self.value


class _FakeLock:
    def __init__(self, harness):
        self.harness = harness
        self.held = False

    def acquire(self, timeout_s=None):
        self.held = True
        self.harness.record("lock.acquire")
        return True

    def release(self):
        self.held = False
        self.harness.record("lock.release")

    def close(self):
        self.held = False
        self.harness.record("lock.close")


class _FakeListener:
    def __init__(self, harness, waits, handle):
        self.harness = harness
        self.handle = handle
        self._waits = list(waits)
        self.wait_timeouts = []
        self.closed = False

    def wait(self, timeout_s):
        self.wait_timeouts.append(timeout_s)
        connected = self._waits.pop(0) if self._waits else False
        self.harness.record("listener.wait", self.handle, round(timeout_s, 6), connected)
        if connected:
            # A connect is quick; a wait that finds nobody burns the timeout
            # it was given (capped so a 30s default cannot spin forever here).
            self.harness.clock.advance(self.harness.connect_latency)
        else:
            self.harness.clock.advance(min(timeout_s, self.harness.idle_advance))
        return connected

    def close(self):
        self.closed = True
        self.harness.record("listener.close", self.handle)


class Harness:
    """Scripted boundaries plus an ordered log of every call across them."""

    connect_latency = 0.02
    idle_advance = 0.2

    def __init__(self, monkeypatch, timeout=1.0, real_decide=False):
        self.monkeypatch = monkeypatch
        self.clock = _Clock()
        self.fake_time = _FakeTime(self.clock, on_sleep=lambda s: self.record("sleep", s))
        self.fake_random = _FakeRandom()
        self.events = []
        self.listeners = []
        self.listener_waits = []  # per-listener wait scripts, e.g. [[True], []]
        self.replies = {}  # conn handle -> [response dict | exception]
        self.decisions = []  # scripted Decision | exception | callable
        self.decide_default = None  # used once the script runs out
        self.decide_calls = []
        self.pids = None  # value _list_codesys_pids returns
        self.pid_list_calls = 0
        self.write_calls = []
        self.write_errors = {}  # cmd_name -> exception raised on write
        self.read_calls = []
        self.released = []
        self.closed_handles = []
        self.diagnose_hint = "DIAG"
        self.ssh_hint = ""
        self.per_call = None  # {"listener_waits": ..., "replies": ...} per run()
        self._next_handle = 100

        monkeypatch.setattr(rpc, "time", self.fake_time)
        monkeypatch.setattr(rpc, "random", self.fake_random)
        monkeypatch.setattr(rpc, "CloseHandle", self._close_handle)
        monkeypatch.setattr(rpc, "_write_msg", self._write_msg)
        monkeypatch.setattr(rpc, "_read_msg", self._read_msg)
        monkeypatch.setattr(rpc, "_send_release_and_close", self._release_close)
        monkeypatch.setattr(rpc, "_SessionLock", self._new_lock)
        monkeypatch.setattr(rpc, "_PipeListener", self._new_listener)
        monkeypatch.setattr(rpc, "_list_codesys_pids", self._list_pids)
        monkeypatch.setattr(rpc, "ssh_dacl_hint", lambda: self.ssh_hint)
        monkeypatch.setattr(
            rpc.ReversePipeClient,
            "_diagnose_ide_timeout",
            staticmethod(lambda target_pid=None: self.diagnose_hint),
        )
        if not real_decide:
            monkeypatch.setattr(rpc, "decide", self._decide)

        self.client = rpc.ReversePipeClient(timeout=timeout)

    # -- recording ---------------------------------------------------------

    def record(self, name, *args):
        self.events.append((name,) + args)

    def names(self):
        return [event[0] for event in self.events]

    def first(self, name):
        for index, event in enumerate(self.events):
            if event[0] == name:
                return index
        raise AssertionError("{0!r} never happened: {1}".format(name, self.events))

    def assert_before(self, first, second):
        assert self.first(first) < self.first(second), (
            "{0} did not precede {1} in {2}".format(first, second, self.events)
        )

    # -- fake boundaries ---------------------------------------------------

    def _new_lock(self, pipe_path):
        self.record("lock.new")
        return _FakeLock(self)

    def _new_listener(self, pipe_path):
        index = len(self.listeners)
        waits = self.listener_waits[index] if index < len(self.listener_waits) else []
        listener = _FakeListener(self, waits, self._next_handle)
        self._next_handle += 1
        self.listeners.append(listener)
        self.record("listener.new", listener.handle)
        return listener

    def _write_msg(self, handle, data, deadline=None, cmd_name=""):
        self.record("write", handle, dict(data), cmd_name)
        self.write_calls.append((handle, dict(data), cmd_name, deadline))
        if cmd_name in self.write_errors:
            raise self.write_errors[cmd_name]

    def _read_msg(self, handle, deadline=None, cmd_name="", max_size=None):
        self.record("read", handle, cmd_name)
        self.read_calls.append((handle, cmd_name, deadline))
        queue = self.replies.get(handle)
        assert queue, "no scripted reply for handle {0} ({1})".format(handle, cmd_name)
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def _release_close(self, handle):
        self.released.append(handle)
        self.record("release_close", handle)

    def _close_handle(self, handle):
        self.closed_handles.append(handle)
        self.record("close_handle", handle)

    def _list_pids(self):
        self.pid_list_calls += 1
        self.record("pids")
        return self.pids

    def _decide(self, hellos, legacy_pids=None, target_pid=None, codesys_pids=None,
                window_over=False):
        self.decide_calls.append(
            {
                "hellos": dict(hellos),
                "legacy_pids": set(legacy_pids or ()),
                "target_pid": target_pid,
                "codesys_pids": codesys_pids,
                "window_over": window_over,
            }
        )
        self.record("decide", target_pid, window_over)
        if self.decisions:
            item = self.decisions.pop(0)
        elif self.decide_default is not None:
            item = self.decide_default
        else:
            raise AssertionError("decide called more times than scripted")
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(hellos, legacy_pids, target_pid, codesys_pids, window_over)
        return item

    def run(self, method="ping", params=None):
        if self.per_call is not None:
            # A multi-call test wants each send_command to read like its own
            # setup: fresh handles, fresh listener list, fresh script.
            self._next_handle = 100
            self.listeners = []
            self.listener_waits = [list(waits) for waits in self.per_call["listener_waits"]]
            self.replies = {
                handle: list(queue) for handle, queue in self.per_call["replies"].items()
            }
        return self.client.send_command(method, params)


@pytest.fixture
def harness(monkeypatch):
    for name in _STATE_GLOBALS:
        monkeypatch.setattr(rpc, name, None)
    monkeypatch.setattr(rpc, "_codesys_pids_listed", False)
    monkeypatch.setattr(rpc, "_cached_codesys_pids", None)
    monkeypatch.setattr(rpc, "_request_counter", 0)
    return Harness(monkeypatch)


@pytest.fixture
def real_harness(monkeypatch):
    for name in _STATE_GLOBALS:
        monkeypatch.setattr(rpc, name, None)
    monkeypatch.setattr(rpc, "_request_counter", 0)
    return Harness(monkeypatch, real_decide=True)


# ── Which PID the call aims at ─────────────────────────────────────────────


class TestTargetResolution:
    def test_resolved_pid_is_used_without_parsing_or_listing(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 999)
        harness.monkeypatch.setattr(rpc, "_configured_target", "ide-1234")
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.decide_calls[0]["target_pid"] == 999
        assert harness.pid_list_calls == 0

    def test_configured_target_string_is_parsed_into_a_pid(self, harness):
        harness.monkeypatch.setattr(rpc, "_configured_target", "ide-1234")
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.decide_calls[0]["target_pid"] == 1234
        assert harness.pid_list_calls == 0

    def test_configured_target_accepts_a_bare_pid(self, harness):
        harness.monkeypatch.setattr(rpc, "_configured_target", 4321)
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.decide_calls[0]["target_pid"] == 4321

    def test_invalid_configured_target_still_raises_where_it_always_did(self, harness):
        # parse_target raises bare ValueError out of send_command: not wrapped
        # into TargetError here, and no pipe is created for it.  Pinned as-is.
        harness.monkeypatch.setattr(rpc, "_configured_target", "not-a-pid")

        with pytest.raises(ValueError):
            harness.run()

        assert harness.names() == []

    def test_without_a_target_the_process_list_is_read_before_the_lock(self, harness):
        harness.pids = {11, 22}
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.pid_list_calls == 1
        assert harness.decide_calls[0]["codesys_pids"] == {11, 22}
        harness.assert_before("pids", "lock.acquire")

    def test_process_list_is_not_re_read_when_it_cannot_be_taken(self, harness):
        harness.pids = None
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.decide_calls[0]["codesys_pids"] is None


# ── Hello handshake ────────────────────────────────────────────────────────


class TestHelloExchange:
    def test_every_connection_is_probed_with_a_ping_before_the_command(self, harness):
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        result = harness.run("ping", {"foo": "bar"})

        assert result == {"ok": True, "data": {}}
        assert harness.write_calls[0][:3] == (100, wire.hello_request(), "ping")
        assert harness.read_calls[0][:2] == (100, "ping")
        assert harness.write_calls[-1][0] == 100
        assert harness.write_calls[-1][1]["method"] == "ping"
        assert harness.write_calls[-1][1]["params"] == {"foo": "bar"}

    def test_the_ping_gets_two_seconds_while_the_command_gets_the_deadline(
        self, harness
    ):
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        ping_write, ping_read, command_write = harness.write_calls[0], harness.read_calls[0], harness.write_calls[-1]
        assert ping_write[3] == pytest.approx(1000.02 + 2.0)
        assert ping_read[2] == pytest.approx(1000.02 + 2.0)
        assert command_write[3] == pytest.approx(1000.0 + 1.0)

    def test_hellos_are_passed_to_decide_keyed_by_pid(self, harness):
        project = {"name": "VKO", "path": "S:\\VKO.project"}
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234, project=project), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234, project=project))]

        harness.run()

        seen = harness.decide_calls[0]["hellos"]
        assert list(seen) == [1234]
        assert seen[1234].project == project
        assert seen[1234].id == "ide-1234"

    def test_a_second_hello_for_the_same_pid_releases_the_older_connection(self, harness):
        harness.listener_waits = [[True], [True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.replies[101] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="wait"), Decision(kind="send", target=hello(1234))]

        harness.run()

        assert harness.released == [100]
        assert harness.write_calls[-1][0] == 101

    def test_a_targeted_call_releases_a_hello_from_another_pid_at_once(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(5678)]
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.released == [100]
        # Oddity pinned as-is: the hello of the other PID is released, but it
        # stays in the hellos dict handed to decide.
        assert list(harness.decide_calls[0]["hellos"]) == [5678]

    def test_a_plain_dict_reply_is_read_as_a_legacy_pid(self, harness):
        harness.listener_waits = [[True]]
        harness.replies[100] = [{"ok": True, "data": {"pid": 777}}]
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.decide_calls[0]["legacy_pids"] == {777}
        assert harness.closed_handles == [100]
        assert rpc._last_ide_pid is None

    def test_a_bare_pid_key_is_also_read_as_a_legacy_pid(self, harness):
        harness.listener_waits = [[True]]
        harness.replies[100] = [{"ok": True, "pid": 778}]
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.decide_calls[0]["legacy_pids"] == {778}

    def test_a_failed_hello_exchange_closes_the_connection_and_moves_on(self, harness):
        harness.listener_waits = [[True]]
        harness.replies[100] = [RuntimeError("pipe disconnected during read")]
        harness.decisions = [Decision(kind="error", error=TargetError("unknown_target", "x"))]

        with pytest.raises(TargetError):
            harness.run()

        assert harness.closed_handles == [100]
        assert harness.decide_calls[0]["hellos"] == {}

    def test_the_discovery_window_opens_on_the_first_hello(self, harness):
        harness.monkeypatch.setenv("CTS_DISCOVERY_MS", "250")
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.decisions = [
            Decision(kind="wait"),
            Decision(kind="error", error=TargetError("unknown_target", "x")),
        ]

        with pytest.raises(TargetError):
            harness.run()

        # Second listener: hello arrived 0.02 in, window closes 0.25 later, so
        # the wait is capped by the window rather than the 1.0s deadline.
        assert harness.listeners[1].wait_timeouts[0] == pytest.approx(0.25)

    def test_a_later_hello_is_added_while_an_earlier_one_is_still_held(self, harness):
        harness.listener_waits = [[True], [True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.replies[101] = [hello_reply(5678), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="wait"), Decision(kind="send", target=hello(5678))]

        harness.run()

        assert sorted(harness.decide_calls[1]["hellos"]) == [1234, 5678]
        assert harness.released == [100]


# ── Sending over a chosen hello ────────────────────────────────────────────


class TestSendPath:
    def test_the_session_lock_is_released_before_the_command_is_written(self, harness):
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        release = harness.first("lock.release")
        command_write = harness.events.index(
            ("write", 100, harness.write_calls[-1][1], "ping")
        )
        assert release < command_write

    def test_other_held_connections_are_released_once_the_target_is_chosen(self, harness):
        harness.listener_waits = [[True], [True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.replies[101] = [hello_reply(5678), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="wait"), Decision(kind="send", target=hello(5678))]

        harness.run()

        assert harness.released == [100]
        writes = [i for i, event in enumerate(harness.events) if event[0] == "write"]
        assert harness.first("release_close") < writes[-1]

    def test_the_response_dict_is_returned_verbatim(self, harness):
        response = {"ok": True, "data": {"pong": True}, "extra": [1, 2, 3]}
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), response]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        assert harness.run() is response

    def test_the_chosen_pid_is_remembered_as_resolved_and_as_last_ide(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        assert rpc._resolved_pid == 1234
        assert rpc._last_ide_pid == 1234

    def test_the_instance_key_of_the_response_is_stored(self, harness):
        instance = {"id": "ide-1234", "project": {"name": "VKO"}}
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "instance": instance}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        assert rpc._last_instance is instance

    def test_without_an_instance_key_the_hello_is_stored_instead(self, harness):
        project = {"name": "VKO"}
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234, project=project), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234, project=project))]

        harness.run()

        assert rpc._last_instance == {"id": "ide-1234", "project": project}

    def test_the_chosen_connection_is_closed_after_a_successful_command(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        assert harness.closed_handles == [100]

    def test_the_request_id_is_carried_on_the_command(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        command = harness.write_calls[-1][1]
        assert command[wire.REQUEST_ID_KEY] == harness.client._request_id
        assert command[wire.REQUEST_ID_KEY].startswith("{0}-1-".format(os.getpid()))

    def test_no_params_is_sent_as_an_empty_dict(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run("status", None)

        assert harness.write_calls[-1][1]["params"] == {}

    def test_a_timeout_inside_the_exchange_gains_the_request_id(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [
            hello_reply(1234),
            RuntimeError("Timeout (1.0s) waiting for a response"),
        ]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        message = str(excinfo.value)
        assert message.startswith("Timeout (1.0s) waiting for a response")
        assert "Request id: {0}".format(harness.client._request_id) in message
        assert "cts last-result" in message

    def test_a_non_timeout_failure_is_not_decorated(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), RuntimeError("Pipe disconnected")]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        assert str(excinfo.value) == "Pipe disconnected"

    def test_each_command_gets_a_fresh_request_id(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.per_call = {
            "listener_waits": [[True]],
            "replies": {100: [hello_reply(1234), {"ok": True, "data": {}}]},
        }
        harness.decisions = [Decision(kind="send", target=hello(1234))] * 2

        harness.run()
        first = harness.write_calls[-1][1][wire.REQUEST_ID_KEY]
        harness.run()
        second = harness.write_calls[-1][1][wire.REQUEST_ID_KEY]

        assert first != second
        assert first.endswith("-1-120000")
        assert second.endswith("-2-120000")


class TestExpectProject:
    def test_a_matching_project_name_is_accepted_case_insensitively(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.monkeypatch.setattr(rpc, "_configured_expect_project", "vko")
        harness.listener_waits = [[True]]
        project = {"name": "VKO", "path": "S:\\VKO.project"}
        harness.replies[100] = [hello_reply(1234, project=project), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234, project=project))]

        assert harness.run() == {"ok": True, "data": {}}

    def test_a_mismatching_project_raises_target_error_and_releases_the_connection(
        self, harness
    ):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.monkeypatch.setattr(rpc, "_configured_expect_project", "Other")
        harness.listener_waits = [[True]]
        project = {"name": "VKO"}
        harness.replies[100] = [hello_reply(1234, project=project)]
        harness.decisions = [Decision(kind="send", target=hello(1234, project=project))]

        with pytest.raises(TargetError) as excinfo:
            harness.run()

        error = excinfo.value
        assert error.code == "project_mismatch"
        assert "expected 'Other'" in str(error)
        assert "but IDE ide-1234 has 'VKO' open" in str(error)
        assert [h.pid for h in error.instances] == [1234]
        assert harness.released == [100]
        assert rpc._resolved_pid == 1234  # the pre-set value, never re-stored
        assert rpc._last_ide_pid is None
        assert rpc._last_instance is None

    def test_a_mismatch_against_a_project_less_ide_says_so(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.monkeypatch.setattr(rpc, "_configured_expect_project", "Other")
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234, project=None)]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        with pytest.raises(TargetError) as excinfo:
            harness.run()

        assert "has 'no project' open" in str(excinfo.value)


# ── The legacy daemon path ─────────────────────────────────────────────────

class TestLegacyPath:
    def _legacy_setup(self, harness, legacy_wait=True):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[], [legacy_wait]]
        harness.decisions = [Decision(kind="send", target=LEGACY)]
        harness.replies[101] = [{"ok": True, "data": {"pid": 4321}}]

    def test_the_command_goes_over_a_fresh_listener_for_a_legacy_daemon(self, harness):
        self._legacy_setup(harness)

        result = harness.run("ping", {"a": 1})

        assert result == {"ok": True, "data": {"pid": 4321}}
        assert harness.write_calls[-1][:3] == (
            101,
            {
                "method": "ping",
                "params": {"a": 1},
                wire.REQUEST_ID_KEY: harness.client._request_id,
            },
            "ping",
        )
        assert harness.listeners[1].closed is True

    def test_the_session_lock_stays_held_until_the_legacy_exchange_is_done(
        self, harness
    ):
        # Oddity pinned as-is: for a v2 hello the lock is released before the
        # command is written, but the legacy branch holds it through the whole
        # exchange.
        self._legacy_setup(harness)

        harness.run()

        harness.assert_before("write", "lock.release")

    def test_the_pid_from_a_legacy_response_is_remembered(self, harness):
        self._legacy_setup(harness)

        harness.run()

        assert rpc._last_ide_pid == 4321
        assert rpc._resolved_pid == 1234
        assert rpc._last_instance is None

    def test_a_legacy_response_without_a_pid_leaves_the_global_alone(self, harness):
        self._legacy_setup(harness)
        harness.replies[101] = [{"ok": True, "data": {}}]

        harness.run()

        assert rpc._last_ide_pid is None

    def test_a_legacy_daemon_that_never_connects_raises_the_diagnostic(self, harness):
        self._legacy_setup(harness, legacy_wait=False)

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        assert "Timeout waiting for legacy IDE to connect." in str(excinfo.value)
        assert harness.diagnose_hint in str(excinfo.value)
        assert harness.listeners[1].closed is True

    def test_held_hello_connections_are_released_before_the_legacy_send(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True], [], [True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.replies[102] = [{"ok": True, "data": {"pid": 4321}}]
        harness.decisions = [
            Decision(kind="wait"),
            Decision(kind="send", target=LEGACY),
        ]

        harness.run()

        # The hello that was held for the target is released before the legacy
        # listener is even opened; the command goes out on that fresh listener.
        assert harness.released == [100]
        assert harness.write_calls[-1][0] == 102


# ── Error decisions ────────────────────────────────────────────────────────


class TestErrorDecision:
    def test_the_target_error_is_raised_after_releasing_everything(self, harness):
        error = TargetError("ambiguous_target", "error: 2 IDE instances, choose one:")
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.decisions = [Decision(kind="error", error=error)]

        with pytest.raises(TargetError) as excinfo:
            harness.run()

        assert excinfo.value is error
        assert harness.released == [100]
        harness.assert_before("release_close", "lock.close")

    def test_an_error_with_no_hellos_gains_the_ssh_hint(self, harness):
        harness.ssh_hint = "SSH HINT"
        error = TargetError("unknown_target", "error: IDE instance ide-1 not found")
        harness.decisions = [Decision(kind="error", error=error)]

        with pytest.raises(TargetError) as excinfo:
            harness.run()

        assert str(excinfo.value) == "error: IDE instance ide-1 not found SSH HINT"
        assert excinfo.value.code == "unknown_target"

    def test_an_error_with_hellos_keeps_the_message_clean(self, harness):
        harness.ssh_hint = "SSH HINT"
        error = TargetError("protocol_mismatch", "error: protocol mismatch")
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.decisions = [Decision(kind="error", error=error)]

        with pytest.raises(TargetError) as excinfo:
            harness.run()

        assert excinfo.value is error


# ── Giving up / deadlines ──────────────────────────────────────────────────


class TestTimeout:
    def test_a_never_connecting_ide_times_out_with_the_diagnostic(self, harness):
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        message = str(excinfo.value)
        assert "Timeout (1.0s) waiting for IDE to connect to {0}".format(
            harness.client._pipe_path
        ) in message
        assert "the command loop is single-threaded" in message
        assert message.endswith(harness.diagnose_hint)

    def test_the_ssh_hint_wins_over_the_process_diagnostic(self, harness):
        harness.ssh_hint = "SSH HINT"
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        assert str(excinfo.value).endswith("SSH HINT")
        assert harness.diagnose_hint not in str(excinfo.value)

    def test_a_targeted_timeout_asks_decide_one_last_time(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)

        def last_chance(hellos, legacy_pids=None, target_pid=None, codesys_pids=None,
                        window_over=False):
            if window_over:
                return Decision(
                    kind="error",
                    error=TargetError(
                        "unknown_target", "error: IDE instance ide-1234 not found"
                    ),
                )
            return Decision(kind="wait")

        harness.decide_default = last_chance

        with pytest.raises(TargetError) as excinfo:
            harness.run()

        assert excinfo.value.code == "unknown_target"
        assert harness.decide_calls[-1]["window_over"] is True
        assert harness.decide_calls[-1]["target_pid"] == 1234

    def test_an_untargeted_timeout_raises_right_after_the_loop(self, harness):
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        assert "Timeout (1.0s)" in str(excinfo.value)
        # The last decide ran inside the loop; the close of the loop's listener
        # follows it, so an untargeted call asks nobody again.
        last_decide = max(i for i, e in enumerate(harness.events) if e[0] == "decide")
        assert harness.events[last_decide + 1][0] == "listener.close"

    def test_a_targeted_timeout_asks_once_more_after_the_loop_closed(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError):
            harness.run()

        last_decide = max(i for i, e in enumerate(harness.events) if e[0] == "decide")
        assert harness.events[last_decide - 1][0] == "listener.close"
        assert harness.decide_calls[-1]["window_over"] is True

    def test_the_deadline_bounds_the_whole_call(self, harness):
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError):
            harness.run()

        assert harness.clock.now >= 1001.0


class TestLockSlicing:
    def test_a_targeted_call_gives_the_pipe_back_after_the_slice(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError):
            harness.run()

        assert harness.fake_random.calls[0] == (0.03, 0.1)
        assert harness.names().count("lock.acquire") >= 2
        # The listener is dropped and rebuilt around the handover.
        assert harness.listeners[0].closed is True
        slice_start = harness.first("lock.release")
        assert harness.events[slice_start - 1][0] == "listener.close"
        assert harness.names()[slice_start + 1] == "sleep"

    def test_an_untargeted_call_never_gives_up_the_lock(self, harness):
        harness.decide_default = Decision(kind="wait")

        with pytest.raises(RuntimeError):
            harness.run()

        assert harness.fake_random.calls == []
        assert harness.names().count("lock.acquire") == 1


# ── Cleanup ────────────────────────────────────────────────────────────────


class TestCleanup:
    def test_success_closes_the_listener_the_lock_and_the_connections(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234), {"ok": True, "data": {}}]
        harness.decisions = [Decision(kind="send", target=hello(1234))]

        harness.run()

        names = harness.names()
        assert names[-2:] == ["lock.release", "lock.close"]
        assert harness.listeners[-1].closed is True
        assert harness.client._request_id is not None

    def test_an_unexpected_failure_still_unwinds_everything(self, harness):
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.decisions = [RuntimeError("boom from decide")]

        with pytest.raises(RuntimeError) as excinfo:
            harness.run()

        assert str(excinfo.value) == "boom from decide"
        assert harness.released == [100]
        names = harness.names()
        # listener.close, then lock.release, then the held connection, then the
        # lock itself: the same unwind as the success path.
        assert names[-4:] == ["listener.close", "lock.release", "release_close", "lock.close"]

    def test_a_failing_command_write_still_closes_the_chosen_connection(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.listener_waits = [[True]]
        harness.replies[100] = [hello_reply(1234)]
        harness.decisions = [Decision(kind="send", target=hello(1234))]
        # A distinct method name: the probe write is always named "ping".
        harness.write_errors["status"] = RuntimeError("Pipe disconnected or broken during write")

        with pytest.raises(RuntimeError) as excinfo:
            harness.run("status")

        assert str(excinfo.value) == "Pipe disconnected or broken during write"
        assert harness.closed_handles == [100]
        assert harness.client._request_id is not None

    def test_the_pipe_is_left_free_for_the_next_call(self, harness):
        harness.monkeypatch.setattr(rpc, "_resolved_pid", 1234)
        harness.per_call = {
            "listener_waits": [[True]],
            "replies": {100: [hello_reply(1234), {"ok": True, "data": {}}]},
        }
        harness.decisions = [Decision(kind="send", target=hello(1234))] * 2

        harness.run()
        harness.run()

        assert harness.names().count("lock.close") == 2
        assert harness.names().count("lock.acquire") == 2


# ── End to end with the real decision function ─────────────────────────────


class TestRealDecideWiring:
    def test_a_lone_hello_is_chosen_without_a_target(self, real_harness):
        real_harness.listener_waits = [[True]]
        real_harness.replies[100] = [
            hello_reply(1234, project={"name": "VKO"}),
            {"ok": True, "data": {"pong": True}, "instance": {"id": "ide-1234"}},
        ]

        assert real_harness.run() == {
            "ok": True,
            "data": {"pong": True},
            "instance": {"id": "ide-1234"},
        }
        assert rpc._resolved_pid == 1234

    def test_a_lone_legacy_hello_is_used_when_no_v2_daemon_answers(self, real_harness):
        real_harness.listener_waits = [[True], [], [True]]
        real_harness.replies[100] = [{"ok": True, "data": {"pid": 777}}]
        real_harness.replies[102] = [{"ok": True, "data": {"pong": True, "pid": 777}}]

        assert real_harness.run() == {"ok": True, "data": {"pong": True, "pid": 777}}
        assert rpc._last_ide_pid == 777
        assert rpc._resolved_pid is None

    def test_two_hellos_without_a_target_are_ambiguous(self, real_harness):
        real_harness.listener_waits = [[True], [True]]
        real_harness.replies[100] = [hello_reply(1234)]
        real_harness.replies[101] = [hello_reply(5678)]

        with pytest.raises(TargetError) as excinfo:
            real_harness.run()

        assert excinfo.value.code == "ambiguous_target"
        assert "2 IDE instances, choose one" in str(excinfo.value)


# ── Public surface ─────────────────────────────────────────────────────────


class TestPublicSurface:
    def test_send_command_signature(self):
        import inspect

        parameters = list(
            inspect.signature(rpc.ReversePipeClient.send_command).parameters
        )
        assert parameters == ["self", "method", "params"]

    def test_client_defaults(self):
        client = rpc.ReversePipeClient()
        assert client._timeout == 30
        assert client._request_id is None
        assert client._pipe_path == rpc.reverse_pipe_name(None)

    def test_send_command_reverse_builds_a_client_and_delegates(self, monkeypatch):
        calls = {}

        class FakeClient:
            def __init__(self, user=None, timeout=30):
                calls["init"] = (user, timeout)

            def send_command(self, method, params=None):
                calls["call"] = (method, params)
                return {"ok": True}

        monkeypatch.setattr(rpc, "ReversePipeClient", FakeClient)

        assert rpc.send_command_reverse("ping", {"a": 1}, user="u", timeout=7) == {
            "ok": True
        }
        assert calls == {"init": ("u", 7), "call": ("ping", {"a": 1})}
