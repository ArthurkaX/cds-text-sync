# -*- coding: utf-8 -*-
"""
test_last_result.py — T50: the outcome of a command the CLI never received.

When the CLI times out it stops listening, but the daemon runs the command to
completion and then cannot write the response. The result -- created/updated/
failed lists, the saved flag -- used to vanish, leaving a successful import
indistinguishable from a hang. The daemon now records it in
``<sync folder>/.dump/last-result.json`` and ``cts last-result`` reads it back.

Covers both halves: the daemon writes the file (and only when it is worth
writing), the reader returns it, and the client puts a request id on the
command and names it in the timeout message.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
_ENGINE_SRC = _ROOT / "products" / "cds-text-sync" / "src"
_SHARED_SRC = _ROOT / "shared" / "src"

for _path in (_SHARED_SRC, _ENGINE_SRC, _BRIDGE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from cts_shared import wire  # noqa: E402

import ide_last_result  # noqa: E402

from cds_text_sync.engine import reverse_pipe_client as rpc  # noqa: E402


@pytest.fixture
def sync_folder(tmp_path, monkeypatch):
    """Point the recorder's sync-folder lookup at a scratch directory."""
    monkeypatch.setattr(
        ide_last_result, "_sync_folder", lambda: (str(tmp_path), "")
    )
    return tmp_path


def _read(path):
    with open(path, "r") as handle:
        return json.load(handle)


# ── The daemon records the outcome ─────────────────────────────────────────


def test_a_lost_import_result_is_recorded(sync_folder):
    """The exact T50 case: the response write failed, so this file is the only
    surviving record of an import that did happen."""
    response = {
        "ok": True,
        "data": {
            "created_text_objects": ["_05_VM_NEW_GVL", "_06_VM_PERSISTENT"],
            "updated_text_objects": [],
            "failed_text_objects": [],
            "saved": True,
        },
    }

    path = ide_last_result.record_last_result(
        "sync_import_text", response, request_id="77-1", write_failed=True
    )

    assert path == str(sync_folder / ".dump" / "last-result.json")
    payload = _read(path)
    assert payload["method"] == "sync_import_text"
    assert payload["request_id"] == "77-1"
    assert payload["delivered"] is False
    assert payload["ok"] is True
    assert payload["saved"] is True
    assert payload["result"]["created_text_objects"] == [
        "_05_VM_NEW_GVL",
        "_06_VM_PERSISTENT",
    ]
    assert payload["recorded_at"]


def test_a_refusal_is_recorded_too(sync_folder):
    """A command that was refused is a result as well; the user needs to see
    the reason rather than guess that the daemon never got the command."""
    response = {"ok": False, "error": "Refused: a persistent list already exists"}

    ide_last_result.record_last_result(
        "sync_import_text", response, request_id="77-2", write_failed=True
    )

    payload = _read(str(sync_folder / ".dump" / "last-result.json"))
    assert payload["ok"] is False
    assert "persistent list already exists" in payload["error"]
    assert payload["result"] == {}


def test_an_undelivered_quick_command_is_recorded(sync_folder):
    """Write failure records whatever the command was -- naming the id is the
    whole point for a command whose result nobody expected to need."""
    ide_last_result.record_last_result(
        "project_info", {"ok": True, "data": {"name": "Demo"}}, "77-3", True
    )
    payload = _read(str(sync_folder / ".dump" / "last-result.json"))
    assert payload["method"] == "project_info"


def test_a_delivered_quick_command_is_not_recorded(sync_folder):
    """Only the long sync commands are kept when the caller did get the answer;
    otherwise every ping would overwrite the import result."""
    path = ide_last_result.record_last_result(
        "ping", {"ok": True, "data": {"status": "pong"}}, "77-4", False
    )
    assert path is None
    assert not (sync_folder / ".dump" / "last-result.json").exists()


def test_a_delivered_sync_command_is_recorded(sync_folder):
    """`cts last-result` must work even when nothing timed out."""
    path = ide_last_result.record_last_result(
        "sync_import_text", {"ok": True, "data": {"saved": False}}, "77-5", False
    )
    assert path is not None
    assert _read(path)["delivered"] is True


def test_recording_without_a_sync_folder_does_not_raise(monkeypatch):
    monkeypatch.setattr(ide_last_result, "_sync_folder", lambda: (None, "no project"))
    assert ide_last_result.record_last_result("sync_import_text", {"ok": True}, "x", True) is None


# ── The CLI reads it back ──────────────────────────────────────────────────


def test_last_result_reads_the_recorded_outcome(sync_folder):
    ide_last_result.record_last_result(
        "sync_import_text",
        {"ok": True, "data": {"created_text_objects": ["GVL_A"]}},
        "88-1",
        True,
    )

    result = ide_last_result._cmd_last_result({})

    assert result["ok"] is True
    assert result["data"]["method"] == "sync_import_text"
    assert result["data"]["request_id"] == "88-1"
    assert result["data"]["result"]["created_text_objects"] == ["GVL_A"]
    assert result["data"]["path"].endswith("last-result.json")


def test_last_result_says_so_when_nothing_was_recorded(sync_folder):
    result = ide_last_result._cmd_last_result({})
    assert result["ok"] is False
    assert result["code"] == "not_found"
    assert "last-result.json" in result["error"]


def test_last_result_reports_an_unreadable_file(sync_folder):
    dump = sync_folder / ".dump"
    dump.mkdir()
    (dump / "last-result.json").write_text("{not json", encoding="utf-8")
    result = ide_last_result._cmd_last_result({})
    assert result["ok"] is False
    assert result["code"] == "unreadable"


# ── The refused-import marker: build must not misread "up to date" ─────────


def test_a_refused_import_leaves_a_marker(sync_folder):
    path = ide_last_result.record_import_refusal(
        "The IDE is online with the PLC", "sync_import_text"
    )

    assert path == str(sync_folder / ".dump" / "last-import-refused.json")
    marker = ide_last_result.read_import_refusal()
    assert marker["reason"] == "The IDE is online with the PLC"
    assert marker["command"] == "sync_import_text"
    assert marker["recorded_at"]


def test_a_successful_import_clears_the_marker(sync_folder):
    ide_last_result.record_import_refusal("nope")
    assert ide_last_result.read_import_refusal() is not None

    ide_last_result.clear_import_refusal()

    assert ide_last_result.read_import_refusal() is None


def test_no_marker_reads_as_none(sync_folder):
    assert ide_last_result.read_import_refusal() is None


def test_a_missing_sync_folder_records_nothing(monkeypatch):
    monkeypatch.setattr(
        ide_last_result, "_sync_folder", lambda: (None, "no project")
    )
    assert ide_last_result.record_import_refusal("x") is None
    assert ide_last_result.read_import_refusal() is None


def test_build_sees_the_refused_import(sync_folder):
    """A build compiles the unchanged IDE; the note says why it looks current."""
    import ide_handlers_build

    ide_last_result.record_import_refusal("The IDE is online with the PLC")

    assert (
        ide_handlers_build._last_import_refusal_reason()
        == "The IDE is online with the PLC"
    )

    ide_last_result.clear_import_refusal()
    assert ide_handlers_build._last_import_refusal_reason() is None


# ── Non-ASCII results survive the round trip (T52) ─────────────────────────


def test_a_cyrillic_result_is_written_and_read_back(sync_folder):
    """The writer must use an explicit utf-8 stream.

    A plain ``open()`` plus ``json.dump(..., ensure_ascii=False)`` fails under
    IronPython 2.7 for non-ASCII -- the streaming encoder mixes str and unicode
    chunks. A Cyrillic object name or error message would then make the whole
    file fail to write, losing the only record of an import the CLI never
    received.
    """
    response = {
        "ok": False,
        "error": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043f\u0438\u0441\u0430\u0442\u044c \u043e\u0431\u044a\u0435\u043a\u0442 '\u0421\u0447\u0451\u0442\u0447\u0438\u043a'",
        "data": {"created_text_objects": ["\u0421\u0447\u0451\u0442\u0447\u0438\u043a", "\u041f\u043b\u0430\u043d"]},
    }

    path = ide_last_result.record_last_result(
        "sync_import_text", response, "77-cyr", True
    )

    assert path is not None
    # Stored as real utf-8 bytes, not \uXXXX escapes.
    raw = Path(path).read_bytes()
    assert "\u0421\u0447\u0451\u0442\u0447\u0438\u043a".encode("utf-8") in raw

    payload = _read(path)
    assert payload["error"] == "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043f\u0438\u0441\u0430\u0442\u044c \u043e\u0431\u044a\u0435\u043a\u0442 '\u0421\u0447\u0451\u0442\u0447\u0438\u043a'"
    assert payload["result"]["created_text_objects"] == ["\u0421\u0447\u0451\u0442\u0447\u0438\u043a", "\u041f\u043b\u0430\u043d"]


def test_a_cyrillic_result_survives_the_daemon_read_path(sync_folder):
    """``cts last-result`` (the daemon side) reads the same utf-8 stream."""
    ide_last_result.record_last_result(
        "sync_import_text",
        {"ok": True, "data": {"updated_text_objects": ["\u0421\u0447\u0451\u0442\u0447\u0438\u043a"]}},
        "88-cyr",
        True,
    )

    result = ide_last_result._cmd_last_result({})

    assert result["ok"] is True
    assert result["data"]["error"] == ""
    assert result["data"]["result"]["updated_text_objects"] == ["\u0421\u0447\u0451\u0442\u0447\u0438\u043a"]


# ── The daemon loop records on a failed response write ─────────────────────

_STUB_NAMES = [
    "clr",
    "System",
    "System.IO",
    "System.IO.Pipes",
    "System.Threading",
    "System.Windows",
    "System.Windows.Forms",
    "System.Drawing",
    "System.Collections",
    "System.Collections.Generic",
    "System.Array",
    "System.Byte",
    "scriptengine",
]


class _AutoStub:
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return _STUB_SINGLETON

    def __iter__(self):
        return iter([])


_STUB_SINGLETON = _AutoStub()


def _load_loop_module():
    saved = {name: sys.modules.get(name) for name in _STUB_NAMES}
    for name in _STUB_NAMES:
        module = ModuleType(name)
        module.__spec__ = None
        module.__getattr__ = lambda attr: _STUB_SINGLETON  # type: ignore[attr-defined]
        sys.modules[name] = module
    had_loop = hasattr(sys, "_codesys_daemon_loop")
    if not had_loop:
        sys._codesys_daemon_loop = {}  # type: ignore[attr-defined]
    try:
        spec = importlib.util.spec_from_file_location(
            "ide_reverse_pipe_loop_last_result", str(_BRIDGE / "ide_reverse_pipe_loop.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        if not had_loop:
            sys._codesys_daemon_loop.pop("running", None)


class _BrokenPipe:
    """A connection whose response write always fails, like a CLI that gave up."""

    def __init__(self, command):
        self._command = command
        self.closed = False

    def read_msg(self):
        command, self._command = self._command, None
        return command

    def write_msg(self, data):
        return False

    def close(self):
        self.closed = True


def test_serve_connection_records_a_result_it_could_not_deliver(monkeypatch):
    loop = _load_loop_module()
    recorded = []
    monkeypatch.setattr(loop, "handle_command", lambda *a, **k: {"ok": True, "data": {"saved": True}})
    monkeypatch.setattr(loop, "_instance_info", lambda: {"id": "ide-1", "project": None})
    monkeypatch.setattr(
        loop,
        "record_last_result",
        lambda method, response, request_id=None, write_failed=False: recorded.append(
            (method, request_id, write_failed)
        ),
    )

    command = {"method": "sync_import_text", "params": {}, "request_id": "99-7"}
    stop = loop._serve_connection(_BrokenPipe(command), dash=None)

    assert stop is False
    assert recorded == [("sync_import_text", "99-7", True)]


def test_serve_connection_records_a_delivered_result(monkeypatch):
    loop = _load_loop_module()
    recorded = []

    class _WorkingPipe(_BrokenPipe):
        def write_msg(self, data):
            return True

    monkeypatch.setattr(loop, "handle_command", lambda *a, **k: {"ok": True, "data": {}})
    monkeypatch.setattr(loop, "_instance_info", lambda: {"id": "ide-1", "project": None})
    monkeypatch.setattr(
        loop,
        "record_last_result",
        lambda method, response, request_id=None, write_failed=False: recorded.append(
            (method, request_id, write_failed)
        ),
    )

    loop._serve_connection(_WorkingPipe({"method": "sync_import_text", "params": {}}), dash=None)

    assert recorded == [("sync_import_text", None, False)]


def test_serve_connection_echoes_the_request_id(monkeypatch):
    loop = _load_loop_module()
    seen = {}

    class _CapturingPipe(_BrokenPipe):
        def write_msg(self, data):
            seen.update(data)
            return True

    monkeypatch.setattr(loop, "handle_command", lambda *a, **k: {"ok": True, "data": {}})
    monkeypatch.setattr(loop, "_instance_info", lambda: {"id": "ide-1", "project": None})
    monkeypatch.setattr(loop, "record_last_result", lambda *a, **k: None)

    loop._serve_connection(
        _CapturingPipe({"method": "ping", "params": {}, "request_id": "55-2"}), dash=None
    )

    assert seen[wire.REQUEST_ID_KEY] == "55-2"


def test_serve_connection_keeps_working_without_a_request_id(monkeypatch):
    """An older CLI sends none; the daemon must not require one."""
    loop = _load_loop_module()
    seen = {}

    class _CapturingPipe(_BrokenPipe):
        def write_msg(self, data):
            seen.update(data)
            return True

    monkeypatch.setattr(loop, "handle_command", lambda *a, **k: {"ok": True, "data": {}})
    monkeypatch.setattr(loop, "_instance_info", lambda: {"id": "ide-1", "project": None})
    monkeypatch.setattr(loop, "record_last_result", lambda *a, **k: None)

    loop._serve_connection(_CapturingPipe({"method": "ping", "params": {}}), dash=None)

    assert seen["ok"] is True
    assert wire.REQUEST_ID_KEY not in seen


# ── The client puts an id on the command and names it on a timeout ─────────


def test_client_puts_a_request_id_on_the_command(monkeypatch):
    sent = {}

    def _capture(handle, data, deadline, cmd_name=""):
        sent.update(data)

    monkeypatch.setattr(rpc, "_write_msg", _capture)
    monkeypatch.setattr(rpc, "_read_msg", lambda handle, deadline, cmd_name="": {"ok": True})

    client = rpc.ReversePipeClient(timeout=1)
    client._request_id = "42-9"
    client._exchange(1, "sync_import_text", {"save": True}, time.monotonic() + 1)

    assert sent["method"] == "sync_import_text"
    assert sent["params"] == {"save": True}
    assert sent[wire.REQUEST_ID_KEY] == "42-9"


def test_client_timeout_message_points_at_last_result(monkeypatch):
    monkeypatch.setattr(rpc, "_write_msg", lambda *a, **k: None)

    def _timeout(*args, **kwargs):
        raise RuntimeError("Timeout waiting for IDE response to 'sync_import_text'.")

    monkeypatch.setattr(rpc, "_read_msg", _timeout)

    client = rpc.ReversePipeClient(timeout=1)
    client._request_id = "42-10"
    with pytest.raises(RuntimeError) as excinfo:
        client._exchange(1, "sync_import_text", {}, time.monotonic() + 1)

    message = str(excinfo.value)
    assert "cts last-result" in message
    assert "42-10" in message
    # The original diagnostic must survive; the hint is added to it.
    assert "Timeout waiting for IDE response" in message


def test_client_does_not_dress_up_a_non_timeout_error(monkeypatch):
    monkeypatch.setattr(rpc, "_write_msg", lambda *a, **k: None)

    def _broken(*args, **kwargs):
        raise RuntimeError("Pipe disconnected while reading header")

    monkeypatch.setattr(rpc, "_read_msg", _broken)

    client = rpc.ReversePipeClient(timeout=1)
    client._request_id = "42-11"
    with pytest.raises(RuntimeError) as excinfo:
        client._exchange(1, "ping", {}, time.monotonic() + 1)

    assert "cts last-result" not in str(excinfo.value)


def test_next_request_id_is_unique_per_command():
    first = rpc._next_request_id()
    second = rpc._next_request_id()
    assert first != second
    assert str(__import__("os").getpid()) in first
