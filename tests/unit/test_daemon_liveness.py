# -*- coding: utf-8 -*-
"""The daemon's liveness marker, and what the CLI says when it times out.

The command loop is single-threaded, so a long command makes every other
``cts`` call time out.  Both cases -- daemon alive but busy, and daemon not
running -- used to print the same "The daemon never picked up this request /
is CODESYS running with the daemon started?".  The daemon now writes a small
status file around each command; the CLI reads it and says which case it is.
"""

import json
import os
import sys

import pytest

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _path in (_BRIDGE, _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import ide_daemon_state as state  # noqa: E402

from cds_text_sync.engine import reverse_pipe_client as client  # noqa: E402


# ── the daemon side ─────────────────────────────────────────────────────────


@pytest.fixture
def status_path(tmp_path, monkeypatch):
    path = tmp_path / "cds-daemon-status.json"
    monkeypatch.setattr(state, "STATUS_FILE", str(path))
    return path


def test_the_marker_names_the_running_command(status_path):
    state.write_daemon_status("busy", "build", 100.0)

    data = json.loads(status_path.read_text(encoding="utf-8"))

    assert data["state"] == "busy"
    assert data["method"] == "build"
    assert data["started_ts"] == 100.0
    assert data["pid"] == os.getpid()


def test_clearing_the_marker_leaves_nothing_to_read(status_path):
    state.write_daemon_status("idle")
    assert status_path.exists()

    state.clear_daemon_status()

    assert not status_path.exists()


def test_a_failed_write_does_not_raise(status_path, monkeypatch):
    """The marker is best effort; it must never break the command loop."""
    monkeypatch.setattr(state, "STATUS_FILE", os.path.join("\0bad", "x.json"))

    state.write_daemon_status("busy", "build")  # must not raise


# ── the CLI reading it ──────────────────────────────────────────────────────


def _write_status(tmp_path, monkeypatch, **fields):
    monkeypatch.setenv("TEMP", str(tmp_path))
    (tmp_path / client.DAEMON_STATUS_FILE).write_text(
        json.dumps(fields), encoding="utf-8"
    )


def test_a_busy_daemon_is_named_with_its_command_and_wait(tmp_path, monkeypatch):
    _write_status(
        tmp_path,
        monkeypatch,
        pid=1234,
        state="busy",
        method="build",
        started_ts=958.0,
        updated=958.0,
    )

    hint = client.daemon_activity_hint(now=1000.0)

    assert "alive but busy with build for 42s" in hint
    assert "1234" in hint


def test_an_idle_daemon_is_not_called_busy(tmp_path, monkeypatch):
    _write_status(
        tmp_path, monkeypatch, pid=7, state="idle", method="", updated=999.0
    )

    hint = client.daemon_activity_hint(now=1000.0)

    assert "alive and idle" in hint
    assert "busy" not in hint


def test_a_long_idle_gap_reads_as_stuck(tmp_path, monkeypatch):
    _write_status(
        tmp_path, monkeypatch, pid=7, state="idle", method="", updated=900.0
    )

    hint = client.daemon_activity_hint(now=1000.0)

    assert "may be stuck" in hint


def test_no_marker_means_nothing_to_say(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))

    assert client.daemon_activity_hint() is None


def test_a_busy_daemon_leads_the_timeout_message(tmp_path, monkeypatch):
    """The verdict is the first line, then the one action to take."""
    _write_status(
        tmp_path, monkeypatch, pid=1, state="busy", method="build",
        started_ts=999.0, updated=999.0,
    )
    session = client._CommandSession(
        pipe_path=r"\\.\pipe\x", method="ping", params={}, request_id="r",
        timeout=5, deadline=0.0, target_pid=None, codesys_pids=None,
        discovery_budget_s=0.4,
    )

    with pytest.raises(RuntimeError) as excinfo:
        client.ReversePipeClient(timeout=5)._raise_connect_timeout(session)

    message = str(excinfo.value)
    assert message.splitlines()[0].startswith("The daemon is alive but busy with build")
    assert "Retry once that command finishes" in message
    assert "Timeout (5s) waiting for IDE to connect" in message


def test_a_corrupt_marker_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))
    (tmp_path / client.DAEMON_STATUS_FILE).write_text("{not json", encoding="utf-8")

    assert client.daemon_activity_hint() is None


# ── the loop marks itself around a command ──────────────────────────────────


def test_a_served_command_is_marked_busy_then_idle(monkeypatch):
    import ide_reverse_pipe_loop as loop

    saved = getattr(sys, "_codesys_daemon_loop", None)
    setattr(sys, "_codesys_daemon_loop", {})
    events = []
    try:
        monkeypatch.setattr(
            loop,
            "write_daemon_status",
            lambda state, method="", started_ts=None: events.append((state, method)),
        )
        monkeypatch.setattr(
            loop, "_read_json_from_pipe", lambda pipe: {"method": "ping", "params": {}}
        )
        monkeypatch.setattr(
            loop,
            "handle_command",
            lambda method, params, request_id=None: {"ok": True, "data": {}},
        )
        monkeypatch.setattr(
            loop.ide_response_context, "attach_response_metadata", lambda *a, **k: None
        )
        monkeypatch.setattr(loop, "_deliver_response", lambda *a, **k: True)
        monkeypatch.setattr(loop, "record_last_result", lambda *a, **k: None)

        loop._serve_connection(object(), dash=None)
    finally:
        if saved is None:
            if hasattr(sys, "_codesys_daemon_loop"):
                delattr(sys, "_codesys_daemon_loop")
        else:
            setattr(sys, "_codesys_daemon_loop", saved)

    assert events == [("busy", "ping"), ("idle", "")]
