# -*- coding: utf-8 -*-
"""A client that left before reading its reply must not cost the daemon a minute.

The reported symptom: ``cts`` times out (or is killed), the daemon finishes the
command, tries to write the reply and gets ``[Errno 232] Pipe is broken`` --
and then stops serving new clients, so the next ``cts`` reports the daemon as
unreachable.

Two code-level causes are possible, and both are covered here.

* The reply path ended in ``Flush()``. On a named pipe ``FlushFileBuffers``
  waits for the *other* end to read, so when the peer is gone (or alive but no
  longer reading) the flush is the one call that can wait a whole CLI lifetime
  before failing with 232. A byte-mode pipe needs no flush: the bytes are on
  the wire as soon as ``Write`` returns.
* A failed write was not treated as "this connection is over". The reply must
  be abandoned in one line of log, the instance dropped at once, and the loop
  must go straight to the next client -- the outcome itself is kept by
  ``record_last_result`` for ``cts last-result``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
for _path in (_ROOT / "shared" / "src", _BRIDGE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from cts_shared import wire  # noqa: E402

import ide_daemon_state  # noqa: E402
import ide_reverse_pipe_loop as loop  # noqa: E402


_COMMAND = {"method": "sync_export_text", "params": {}, wire.REQUEST_ID_KEY: "ide-test-1"}


class _BrokenPipe(object):
    """A .NET-shaped pipe whose peer is gone: the body write fails with 232."""

    def __init__(self, request=None, fail_write=True, fail_flush=False):
        self._request = wire.encode_message(
            _COMMAND if request is None else request
        )
        self._offset = 0
        self.fail_write = fail_write
        self.fail_flush = fail_flush
        self.flush_calls = 0
        self.close_calls = 0
        self.write_calls = 0

    # read side -- the daemon's CPython branch, so the fake needs `read`
    def read(self, size=-1):
        if size < 0:
            chunk = self._request[self._offset:]
        else:
            chunk = self._request[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    # write side -- .NET names only, so the dotnet branch of the helper runs
    def WriteByte(self, value):
        self.write_calls += 1
        if self.fail_write:
            raise IOError(232, "Pipe is broken")

    def Write(self, buffer, offset, count):
        self.write_calls += 1
        if self.fail_write:
            raise IOError(232, "Pipe is broken")

    def Flush(self):
        self.flush_calls += 1
        if self.fail_flush:
            raise IOError(232, "Pipe is broken")

    def Close(self):
        self.close_calls += 1


@pytest.fixture
def logs(monkeypatch):
    lines = []
    monkeypatch.setattr(loop, "_log", lines.append)
    monkeypatch.setattr(ide_daemon_state, "_log", lines.append)
    return lines


@pytest.fixture
def recorded(monkeypatch):
    """Capture record_last_result calls without touching the sync folder."""
    calls = []
    monkeypatch.setattr(
        loop, "record_last_result",
        lambda method, response, request_id=None, write_failed=False: calls.append(
            {"method": method, "request_id": request_id, "write_failed": write_failed}
        ),
    )
    return calls


@pytest.fixture
def order(monkeypatch):
    """A shared list every step appends to, so the sequence can be asserted."""
    steps = []
    monkeypatch.setattr(
        loop, "_close_connection", lambda pipe: steps.append("close")
    )
    monkeypatch.setattr(
        loop, "record_last_result",
        lambda *a, **k: steps.append("record"),
    )
    return steps


def _serve(pipe, command=_COMMAND):
    """Run one connection with a stubbed command handler."""
    return loop._serve_connection(pipe, dash=None)


@pytest.fixture(autouse=True)
def _stub_handlers(monkeypatch):
    monkeypatch.setattr(
        loop, "handle_command",
        lambda method, params, request_id=None: wire.ok_response({"done": True}),
    )
    monkeypatch.setattr(
        loop.ide_response_context, "attach_response_metadata",
        lambda response, request_id=None: None,
    )


class _ByteArrayFactory(object):
    """Stands in for ``System.Array[System.Byte]``."""

    def __getitem__(self, _type):
        return lambda values: values


@pytest.fixture(autouse=True)
def _stub_dotnet(monkeypatch):
    """The .NET branch of the pipe helpers only needs ``System`` to exist.

    The real byte-array is never inspected -- the write is the thing under
    test, and the fake pipe records the calls it receives.
    """
    system = type(sys)("System")
    system.Byte = int
    system.Array = _ByteArrayFactory()
    monkeypatch.setitem(sys.modules, "System", system)


def _write_error_lines(logs):
    """The helper's raw line; the caller's own line is the one that stays."""
    return [line for line in logs if "Write error" in line]


# ── the flush is what waits for a reader that has gone ─────────────────────


def test_a_successful_reply_does_not_flush_the_pipe():
    """``FlushFileBuffers`` on a pipe waits for the peer to read.

    That is the only call on the reply path that can stall for as long as the
    CLI lives, and byte-mode pipes deliver on Write, so it must not be called.
    """
    pipe = _BrokenPipe(fail_write=False, fail_flush=True)

    assert ide_daemon_state._write_json_to_pipe(pipe, {"ok": True}) is True
    assert pipe.flush_calls == 0


def test_a_reply_written_to_a_dead_peer_is_not_reported_as_undelivered_bytes():
    pipe = _BrokenPipe(fail_write=False)

    assert ide_daemon_state._write_json_to_pipe(pipe, {"ok": True}) is True
    assert pipe.write_calls > 0


# ── a failed write ends the connection at once ─────────────────────────────


def test_a_broken_write_logs_one_line_naming_the_command(logs, recorded):
    pipe = _BrokenPipe()

    _serve(pipe)

    left = [line for line in logs if "client left before the reply was written" in line]
    assert len(left) == 1, logs
    assert "sync_export_text" in left[0]
    assert "ide-test-1" in left[0]
    # The generic low-level "Write error: ..." line is gone: one line, one
    # meaning, and it says whose fault it is (nobody's -- the client left).
    assert _write_error_lines(logs) == []


def test_a_broken_write_drops_the_connection_immediately(logs, recorded):
    pipe = _BrokenPipe()

    _serve(pipe)

    assert pipe.close_calls == 1


def test_a_write_that_reports_failure_without_raising_is_a_failure_too(logs, recorded):
    """The helper signals a lost peer by returning False as well as by raising.

    Treating only the exception as "client left" recorded an undelivered reply
    as delivered, which is exactly the state `cts last-result` exists to avoid.
    """

    class _RefusingPipe(object):
        def read_msg(self):
            return _COMMAND

        def write_msg(self, _data):
            return False

        def close(self):
            self.closed = True

    pipe = _RefusingPipe()

    _serve(pipe)

    assert getattr(pipe, "closed", False) is True
    assert [line for line in logs if "client left before the reply was written" in line]
    assert recorded[0]["write_failed"] is True


def test_the_outcome_survives_a_broken_write(logs, recorded):
    """`cts last-result` is the only copy of a reply the caller never read."""
    pipe = _BrokenPipe()

    _serve(pipe)

    assert len(recorded) == 1
    assert recorded[0]["method"] == "sync_export_text"
    assert recorded[0]["write_failed"] is True


def test_a_delivered_reply_is_recorded_as_delivered(logs, recorded):
    pipe = _BrokenPipe(fail_write=False)

    _serve(pipe)

    assert recorded[0]["write_failed"] is False
    assert [line for line in logs if "client left" in line] == []


# ── the next client is served straight afterwards ──────────────────────────


def test_the_connection_is_dropped_before_the_result_is_recorded(order):
    """The dead instance must not be held while the result is written to disk.

    Recording reads the sync folder and writes a file; nothing about that
    needs the pipe, and the next client is waiting for the instance to be
    free.
    """
    _serve(_BrokenPipe())

    assert order == ["close", "record"], order


def test_a_delivered_reply_leaves_the_close_to_the_loop(order, monkeypatch):
    """Only the lost-reply path closes early, and that is deliberate.

    A delivered reply is closed by the loop right after the handler returns.
    Closing it here instead would race the reader for bytes still sitting in
    the pipe buffer -- a real reply can be discarded that way -- so the early
    close is confined to the connection nobody is reading any more.
    """
    closed_by_loop = []
    monkeypatch.setattr(
        loop, "_close_connection", lambda pipe: closed_by_loop.append(pipe)
    )

    _serve(_BrokenPipe(fail_write=False))

    assert closed_by_loop == []
    assert order == ["record"]


def test_the_next_client_is_served_after_a_broken_reply(logs, recorded, monkeypatch):
    """No wait, no drain: the loop's next iteration serves a live client.

    The daemon is single-threaded, so the only thing that could delay the next
    client is work done on the dead connection after its write failed. Any
    sleep between the two connections fails the test here instead of making it
    pass slowly.
    """
    monkeypatch.setattr(
        loop.time, "sleep",
        lambda *_: pytest.fail("the daemon waited after a broken write"),
    )
    first = _BrokenPipe()

    _serve(first)

    second = _BrokenPipe(fail_write=False)
    _serve(second)

    assert second.flush_calls == 0
    assert len(recorded) == 2
    # The live client's reply was delivered, not abandoned like the first.
    assert recorded[1]["write_failed"] is False
    assert len([line for line in logs if "client left" in line]) == 1


def test_a_second_client_gets_its_own_pipe_instance():
    """The server side is created with ``PIPE_UNLIMITED_INSTANCES``.

    Every ``cts`` process serves the same pipe name, and the daemon connects to
    whichever instance accepts first -- so a second call must never have to
    wait for the first one's instance to be released, dead or alive. The
    Win32 API is unavailable off Windows, so the mechanism itself is pinned
    here: the unlimited instance count, and the fact that the create call
    passes it (and not a default).
    """
    import inspect

    client = pytest.importorskip("cds_text_sync.engine.reverse_pipe_client")

    assert client.PIPE_UNLIMITED_INSTANCES == 255
    source = inspect.getsource(client._PipeListener._create_and_connect)
    create_call = source.split("CreateNamedPipeW(", 1)[1]
    assert "PIPE_UNLIMITED_INSTANCES" in create_call.split(")", 1)[0]


def test_a_broken_hello_reply_also_ends_the_connection(logs):
    hello = dict(_COMMAND)
    hello["method"] = wire.HELLO_METHOD
    hello["params"] = {"hello": wire.hello_request()["params"]["hello"]}
    pipe = _BrokenPipe(request=hello)

    _serve(pipe)

    assert pipe.close_calls == 1
    assert [line for line in logs if "hello" in line.lower()]
