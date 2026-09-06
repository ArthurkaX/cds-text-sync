# -*- coding: utf-8 -*-
"""
test_reverse_pipe_client.py - Tests for Windows named-pipe transport.

Covers Step 1.1 - 1.6:
- Integration test with a real pipe server
{ peer threaf
- Fake API unit tests covering partial transfers, disconnects, timeouts, oversized response, and cleanup
"""

import ctypes
import json
import os
import struct
import sys
import threading
import time
from ctypes import wintypes
from typing import Any
import pytest

from cds_text_sync.engine import reverse_pipe_client as rpc


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows named-pipe transport tests require Windows",
)


def _encode_msg(data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def _decode_msg(raw: bytes) -> tuple[dict, bytes]:
    if len(raw) < 4:
        raise ValueError("Incomplete length header")
    (msg_len,) = struct.unpack("<I", raw[:4])
    if len(raw) < 4 + msg_len:
        raise ValueError("Incomplete body")
    data = json.loads(raw[4 : 4 + msg_len].decode("utf-8"))
    return data, raw[4 + msg_len :]


class TestReversePipeIntegration:
    """Step 1.1 & Phase 1 integration tests on real Windows named pipes."""

    def test_transport_round_trip(self):
        unique_user = f"test_user_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)
        client = rpc.ReversePipeClient(user=unique_user, timeout=5)

        received_requests = []
        peer_error = []

        def peer():
            try:
                time.sleep(0.05)
                with open(pipe_path, "r+b", buffering=0) as f:
                    raw_len = f.read(4)
                    (l,) = struct.unpack("<I", raw_len)
                    raw_req = f.read(l)
                    req = json.loads(raw_req.decode("utf-8"))
                    received_requests.append(req)

                    resp_obj = {"ok": True, "data": {"pong": True, "pid": 1234}}
                    resp_bytes = json.dumps(resp_obj).encode("utf-8")
                    f.write(struct.pack("<I", len(resp_bytes)) + resp_bytes)
                    f.flush()
            except Exception as e:
                peer_error.append(e)


        t = threading.Thread(target=peer)
        t.start()

        resp = client.send_command("ping", {"foo": "bar"})
        t.join(timeout=3)

        assert not peer_error, f"Peer encountered error: {peer_error[0]}"
        assert len(received_requests) == 1
        assert received_requests[0] == {"method": "ping", "params": {"foo": "bar"}}
        assert resp == {"ok": True, "data": {"pong": True, "pid": 1234}}

    def test_response_larger_than_read_buffer(self):
        """Test large payload (> 64KB read buffer)."""
        unique_user = f"test_large_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)
        client = rpc.ReversePipeClient(user=unique_user, timeout=5)

        large_str = "x" * (128 * 1024)
        peer_error = []

        def peer():
            try:
                time.sleep(0.05)
                with open(pipe_path, "r+b", buffering=0) as f:
                    raw_len = f.read(4)
                    (l,) = struct.unpack("<I", raw_len)
                    f.read(l)
                    resp_obj = {"ok": True, "data": {"large": large_str}}
                    resp_bytes = json.dumps(resp_obj).encode("utf-8")
                    f.write(struct.pack("<I", len(resp_bytes)) + resp_bytes)
                    f.flush()
            except Exception as e:
                peer_error.append(e)


        t = threading.Thread(target=peer)
        t.start()

        resp = client.send_command("test_large")
        t.join(timeout=3)

        assert not peer_error
        assert resp["data"]["large"] == large_str

    def test_connect_timeout(self):
        """Test that if peer never connects, timeout raises with diagnostic hint."""
        unique_user = f"test_timeout_{os.getpid()}_{int(time.monotonic() * 1000)}"
        client = rpc.ReversePipeClient(user=unique_user, timeout=0.3)

        start = time.monotonic()
        with pytest.raises(RuntimeError) as exc_info:
            client.send_command("ping")
        elapsed = time.monotonic() - start

        assert "Timeout (0.3s) waiting for IDE to connect" in str(exc_info.value)
        assert elapsed < 2.0


class TestReversePipeOverlappedUnit:
    """Step 1.6 failure modes tested via controlled fake API / unit mocks."""

    def test_overlapped_structure_definition(self):
        """Assert OVERLAQPED fields match pointer-sized Win32 definition."""
        assert ctypes.sizeof(rpc.OVERLAPPED) == (32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20)

    def test_oversized_response_rejected(self, monkeypatch):
        """Step 1.4 & 1.6: responses larger than max_size raise RuntimeError."""
        fake_header = struct.pack("<I", 33 * 1024 * 1024)

        def fake_op(handle, buf, length, is_read, deadline, cmd_name=""):
            buf[:4] = fake_header
            return 4

        monkeypatch.setattr(rpc, "_overlapped_op", fake_op)
        with pytest.raises(RuntimeError) as exc_info:
            rpc._read_msg(1234, deadline=time.monotonic() + 5, max_size=32 * 1024 * 1024)
        assert "Response too large" in str(exc_info.value)

    def test_peer_disconnect_while_reading_header(self, monkeypatch):
        """Step 1.4 & 1.6: zero-byte read treated as broken pipe."""
        def fake_op(handle, buf, length, is_read, deadline, cmd_name=""):
            return 0

        monkeypatch.setattr(rpc, "_overlapped_op", fake_op)
        with pytest.raises(RuntimeError) as exc_info:
            rpc._read_msg(1234, deadline=time.monotonic() + 5)
        assert "Pipe disconnected" in str(exc_info.value) or "broken" in str(exc_info.value).lower()

    def test_peer_disconnect_while_reading_body(self, monkeypatch):
        """Step 1.6: peer disconnect after header is read."""
        calls = 0

        def fake_op(handle, buf, length, is_read, deadline, cmd_name=""):
            nonlocal calls
            calls += 1
            if calls == 1:
                buf[:4] = struct.pack("<I", 100)
                return 4
            return 0

        monkeypatch.setattr(rpc, "_overlapped_op", fake_op)
        with pytest.raises(RuntimeError) as exc_info:
            rpc._read_msg(1234, deadline=time.monotonic() + 5)
        assert "Pipe disconnected" in str(exc_info.value) or "broken" in str(exc_info.value).lower()

    def test_partial_transfers_reassembled(self, monkeypatch):
        """Step 1.4: partial transfers in header and body must complete."""
        full_msg = json.dumps({"test": "ok"}).encode("utf-8")
        header = struct.pack("<I", len(full_msg))
        stream = header + full_msg
        offset = 0

        def fake_op(handle, buf, length, is_read, deadline, cmd_name=""):
            nonlocal offset
            chunk_len = min(2, length, len(stream) - offset)
            buf[:chunk_len] = stream[offset : offset + chunk_len]
            offset += chunk_len
            return chunk_len

        monkeypatch.setattr(rpc, "_overlapped_op", fake_op)
        res = rpc._read_msg(1234, deadline=time.monotonic() + 5)
        assert res == {"test": "ok"}

    def test_response_timeout_retains_message(self, monkeypatch):
        """Step 1.4 & 1.6: Timeout error retains command name and full explanation."""
        def fake_op(handle, buf, length, is_read, deadline, cmd_name=""):
            raise RuntimeError(
                f"Timeout (5s) waiting for IDE response to "
                f"'{cmd_name}'. Giving up here does NOT cancel the command: "
                "the daemon keeps running it, so the IDE may still change "
                "after this error. On a large project export/compare/"
                "import legitimately take minutes -- retry with a bigger "
                "--timeout before assuming a hang. A real hang looks "
                "different: 'cts ping' stops answering too, and then you "
                "check CODESYS for a modal dialog or restart "
                "Project_daemon.py."
            )

        monkeypatch.setattr(rpc, "_overlapped_op", fake_op)
        with pytest.raises(RuntimeError) as exc_info:
            rpc._read_msg(1234, deadline=time.monotonic() + 5, cmd_name="long_job")
        assert "'long_job'" in str(exc_info.value)
        assert "Giving up here does NOT cancel the command" in str(exc_info.value)

    def test_cleanup_after_exception(self, monkeypatch):
        """Step 1.6: Cleanup after an exception closes event and pipe handles."""
        closed_handles = []
        canceled_handles = []
        disconnected_handles = []

        orig_close = rpc.CloseHandle
        orig_cancel = rpc.CancelIo
        orig_disconnect = rpc.DisconnectNamedPipe

        def fake_close(h):
            closed_handles.append(h)
            return True

        def fake_cancel(h):
            canceled_handles.append(h)
            return True

        def fake_disconnect(h):
            disconnected_handles.append(h)
            return True

        monkeypatch.setattr(rpc, "CloseHandle", fake_close)
        monkeypatch.setattr(rpc, "CancelIo", fake_cancel)
        monkeypatch.setattr(rpc, "DisconnectNamedPipe", fake_disconnect)
        monkeypatch.setattr(rpc, "CreateNamedPipeW", lambda *a, **k: 9999)
        monkeypatch.setattr(rpc, "CreateEventW", lambda *a, **k: 8888)
        monkeypatch.setattr(rpc, "ConnectNamedPipe", lambda *a, **k: False)
        monkeypatch.setattr(rpc, "GetLastError", lambda: rpc.ERROR_PIPE_CONNECTED)

        def raise_boom(*a, **k):
            raise RuntimeError("Boom inside write")

        monkeypatch.setattr(rpc, "_write_msg", raise_boom)

        client = rpc.ReversePipeClient(user="fake_user", timeout=5)
        with pytest.raises(RuntimeError, match="Boom inside write"):
            client.send_command("ping")

        assert 9999 in closed_handles
        assert 8888 in closed_handles
        assert 9999 in canceled_handles
        assert 9999 in disconnected_handles
