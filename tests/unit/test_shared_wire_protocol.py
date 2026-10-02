# -*- coding: utf-8 -*-
"""
test_shared_wire_protocol.py — the reverse-pipe wire format, pinned once.

T12: framing, the hello handshake and the response envelope were implemented
twice, once per side of the pipe. This pins the contract they must both meet,
so the shared module (cts_shared.wire) and the two callers can be checked
against it rather than against each other.

The frame bytes are asserted literally -- struct.pack("<I", len(body)) in front
of json.dumps(...).encode("utf-8") -- so a refactor that changes the format is
a red test, not a silent incompatibility with an older daemon. Protocol stays 2.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
_ENGINE_SRC = _ROOT / "products" / "cds-text-sync" / "src"
_SHARED_SRC = _ROOT / "shared" / "src"

for _path in (_SHARED_SRC, _ENGINE_SRC, _BRIDGE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from cts_shared import wire  # noqa: E402

import ide_daemon_state as daemon_state  # noqa: E402

from cds_text_sync.engine import pipe_targets  # noqa: E402
from cds_text_sync.engine import reverse_pipe_client as rpc  # noqa: E402


def _expected_frame(data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(body)) + body


class _BytePipe:
    """The minimal read/write stream ide_daemon_state treats as a pipe."""

    def __init__(self, incoming=b""):
        self._in = bytes(incoming)
        self.out = bytearray()

    def read(self, n):
        chunk = self._in[:n]
        self._in = self._in[n:]
        return chunk

    def write(self, data):
        self.out.extend(data)

    def flush(self):
        pass


# ── The frame contract ─────────────────────────────────────────────────────


def test_protocol_version_is_two():
    assert wire.PROTOCOL == 2
    assert daemon_state.PROTOCOL == 2
    assert rpc and pipe_targets  # both sides are importable for the checks below


def test_encode_message_is_the_pinned_bytes():
    for payload in (
        {"method": "ping", "params": {"hello": 2}},
        {"ok": True, "data": {"status": "pong"}},
        {"ok": False, "error": "unknown method: x", "request_id": "1-1"},
    ):
        assert wire.encode_message(payload) == _expected_frame(payload)


def test_decode_message_round_trips_a_frame():
    payload = {"ok": True, "data": {"count": 3, "names": ["a", "b", "c"]}}
    assert wire.decode_message(_expected_frame(payload)) == payload


def test_non_ascii_survives_the_round_trip():
    payload = {"ok": True, "data": {"text": "Grüße — 日本語"}}
    frame = _expected_frame(payload)
    assert frame == wire.encode_message(payload)
    assert wire.decode_message(frame) == payload


def test_empty_frame_is_the_empty_message():
    assert wire.parse_header(struct.pack("<I", 0)) == 0
    assert wire.decode_message(struct.pack("<I", 0)) == {}


def test_bad_headers_are_rejected_the_same_way_by_both_ends():
    with pytest.raises(wire.WireError):
        wire.parse_header(b"\x01\x02")
    with pytest.raises(wire.WireError):
        wire.parse_header(struct.pack("<I", wire.MAX_MESSAGE_SIZE + 1))
    with pytest.raises(wire.WireError):
        wire.decode_message(struct.pack("<I", 99) + b"{}")


# ── The host's pipe path produces and accepts that contract ────────────────


def test_host_write_json_to_pipe_emits_the_pinned_frame():
    pipe = _BytePipe()
    data = {"ok": True, "data": {"status": "pong", "pid": 42}}

    assert daemon_state._write_json_to_pipe(pipe, data) is True
    assert bytes(pipe.out) == _expected_frame(data)


def test_host_read_json_from_pipe_parses_the_pinned_frame():
    data = {"method": "sync_import_text", "params": {"save": True}}
    assert daemon_state._read_json_from_pipe(_BytePipe(_expected_frame(data))) == data


def test_host_read_rejects_an_oversize_length():
    oversize = struct.pack("<I", wire.MAX_MESSAGE_SIZE + 1)
    assert daemon_state._read_json_from_pipe(_BytePipe(oversize)) is None


# ── The hello handshake, as both sides describe it ─────────────────────────


def test_hello_request_is_a_ping_carrying_the_protocol():
    assert wire.hello_request() == {"method": "ping", "params": {"hello": 2}}
    assert wire.is_hello_message(wire.hello_request())
    assert not wire.is_hello_message({"method": "status", "params": {}})


def test_hello_reply_round_trips_through_both_parsers():
    payload = {
        "protocol": 2,
        "id": "ide-4242",
        "pid": 4242,
        "version": "3.3.0",
        "poll_ms": 200,
        "project": {"name": "Demo", "path": "P:/Demo.project", "sync_folder": "P:/Demo"},
    }
    reply = wire.hello_reply(payload)

    parsed = wire.parse_hello(reply)
    assert parsed == payload

    # The CLI's dataclass must read the same envelope the daemon writes.
    hello = pipe_targets.Hello.from_dict(reply)
    assert hello.protocol == 2
    assert hello.id == "ide-4242"
    assert hello.pid == 4242
    assert hello.version == "3.3.0"
    assert hello.poll_ms == 200
    assert hello.project == payload["project"]


def test_hello_parser_keeps_its_defaults_for_a_bare_older_payload():
    parsed = wire.parse_hello({"pid": 7})
    assert parsed["protocol"] == 2
    assert parsed["id"] == "ide-7"
    assert parsed["poll_ms"] == 200
    assert parsed["project"] is None
    assert pipe_targets.Hello.from_dict({"pid": 7}).id == "ide-7"


# ── The response envelope ──────────────────────────────────────────────────


def test_ok_response_shape():
    assert wire.ok_response({"status": "pong"}) == {
        "ok": True,
        "data": {"status": "pong"},
    }
    assert wire.ok_response() == {"ok": True}


def test_error_response_shape_and_optional_code():
    assert wire.error_response("boom") == {"ok": False, "error": "boom"}
    assert wire.error_response("boom", code="no_project") == {
        "ok": False,
        "error": "boom",
        "code": "no_project",
    }


def test_response_ok_never_assumes_success():
    assert wire.response_ok({"ok": True}) is True
    assert wire.response_ok({"ok": False, "error": "no"}) is False
    assert wire.response_ok({"data": {"looks": "fine"}}) is False
    assert wire.response_ok(None) is False
    assert wire.response_ok("pong") is False


def test_response_error_prefers_the_reported_reason():
    assert wire.response_error({"ok": False, "error": "no project"}) == "no project"
    assert wire.response_error({"ok": False}) == "unknown error"
    assert wire.response_error({"ok": False, "error": ""}) == "unknown error"
    assert wire.response_error(None, default="gone") == "gone"


def test_new_request_id_is_unique_per_command_and_plain_text():
    first = wire.new_request_id(1234, 1)
    second = wire.new_request_id(1234, 2)
    assert first != second
    assert "1234" in first
    assert wire.REQUEST_ID_KEY == "request_id"


# ── Both sides actually use the shared module ──────────────────────────────


def test_host_and_cli_share_the_size_cap_and_protocol():
    assert daemon_state.MAX_MESSAGE_SIZE == wire.MAX_MESSAGE_SIZE
    assert rpc.DEFAULT_MAX_RESPONSE_SIZE == wire.MAX_MESSAGE_SIZE


def test_cli_client_uses_the_shared_module():
    assert rpc.wire is wire


def test_host_state_uses_the_shared_module():
    assert daemon_state.wire is wire
