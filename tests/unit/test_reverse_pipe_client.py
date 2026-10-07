# -*- coding: utf-8 -*-
"""
test_reverse_pipe_client.py - Tests for Windows named-pipe transport.

Covers:
- Integration test with a real pipe server (protocol v2 hello / release / multi-instance)
- Fake API unit tests covering partial transfers, disconnects, timeouts, oversized response, and cleanup
"""

import ctypes
import json
import os
import struct
import sys
import threading
import time
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
    """Integration tests on real Windows named pipes."""

    def test_transport_round_trip(self, monkeypatch):
        # A real CODESYS on this machine must not count as a second instance.
        monkeypatch.setattr(rpc, "_list_codesys_pids", lambda: set())
        unique_user = f"test_user_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)
        rpc.configure(target=None, expect_project=None)
        client = rpc.ReversePipeClient(user=unique_user, timeout=5)

        received_requests = []
        peer_error = []

        def peer():
            try:
                time.sleep(0.05)
                with open(pipe_path, "r+b", buffering=0) as f:
                    # 1. Read H1
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    h1 = json.loads(f.read(msg_len).decode("utf-8"))
                    received_requests.append(h1)

                    # 2. Reply H2
                    h2 = {
                        "ok": True,
                        "hello": {
                            "protocol": 2,
                            "id": "ide-1234",
                            "pid": 1234,
                            "version": "3.2.0",
                            "poll_ms": 200,
                            "project": {"name": "VKO", "path": "S:\\VKO.project"},
                        },
                    }
                    f.write(_encode_msg(h2))
                    f.flush()

                    # 3. Read Command C
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    cmd = json.loads(f.read(msg_len).decode("utf-8"))
                    received_requests.append(cmd)

                    # 4. Reply A
                    resp_obj = {
                        "ok": True,
                        "data": {"pong": True, "pid": 1234},
                        "instance": {"id": "ide-1234", "project": {"name": "VKO", "path": "S:\\VKO.project"}},
                    }
                    f.write(_encode_msg(resp_obj))
                    f.flush()
            except Exception as e:
                peer_error.append(e)

        t = threading.Thread(target=peer)
        t.start()

        resp = client.send_command("ping", {"foo": "bar"})
        t.join(timeout=3)

        assert not peer_error, f"Peer encountered error: {peer_error[0]}"
        assert len(received_requests) == 2
        assert received_requests[0] == {"method": "ping", "params": {"hello": 2}}
        assert received_requests[1] == {"method": "ping", "params": {"foo": "bar"}}
        assert resp["ok"] is True
        assert resp["data"]["pong"] is True

    def test_response_larger_than_read_buffer(self, monkeypatch):
        """Test large payload (> 64KB read buffer)."""
        # A real CODESYS on this machine must not count as a second instance.
        monkeypatch.setattr(rpc, "_list_codesys_pids", lambda: set())
        unique_user = f"test_large_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)
        rpc.configure(target=None, expect_project=None)
        client = rpc.ReversePipeClient(user=unique_user, timeout=5)

        large_str = "x" * (128 * 1024)
        peer_error = []

        def peer():
            try:
                time.sleep(0.05)
                with open(pipe_path, "r+b", buffering=0) as f:
                    # 1. H1
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    f.read(msg_len)

                    # 2. H2
                    h2 = {
                        "ok": True,
                        "hello": {
                            "protocol": 2,
                            "id": "ide-1234",
                            "pid": 1234,
                            "version": "3.2.0",
                            "poll_ms": 200,
                            "project": None,
                        },
                    }
                    f.write(_encode_msg(h2))
                    f.flush()

                    # 3. C
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    f.read(msg_len)

                    # 4. A
                    resp_obj = {"ok": True, "data": {"large": large_str}}
                    f.write(_encode_msg(resp_obj))
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
        rpc.configure(target=None, expect_project=None)
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
        """Assert OVERLAPPED fields match pointer-sized Win32 definition."""
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


class TestSessionLock:
    """Tests for cross-process _SessionLock and targeted client routing."""

    def test_session_lock_threads_same_process(self):
        """(a) Two _SessionLock instances on the same pipe path in one process.

        Second acquire(0.2) returns False while first holds, True after release.
        (Win32 mutex is re-entrant within the SAME thread, so the second lock is tested from another thread).
        """
        unique_user = f"test_sl_threads_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)

        lock1 = rpc._SessionLock(pipe_path)
        lock2 = rpc._SessionLock(pipe_path)

        try:
            assert lock1.acquire(1.0) is True
            assert lock1.held is True

            res_while_held = []
            t1 = threading.Thread(target=lambda: res_while_held.append(lock2.acquire(0.2)))
            t1.start()
            t1.join()
            assert res_while_held == [False]
            assert lock2.held is False

            lock1.release()
            assert lock1.held is False

            res_after_rel = []
            t2 = threading.Thread(target=lambda: res_after_rel.append(lock2.acquire(0.2)))
            t2.start()
            t2.join()
            assert res_after_rel == [True]
            assert lock2.held is True
        finally:
            lock1.close()
            lock2.close()

    def test_session_lock_mutual_exclusion_subprocesses(self):
        """(b) Mutual exclusion across two real processes (subprocess) holding the lock."""
        import subprocess

        unique_user = f"test_sl_proc_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)

        lock = rpc._SessionLock(pipe_path)
        try:
            assert lock.acquire(1.0) is True

            code = (
                "import sys; "
                "from cds_text_sync.engine import reverse_pipe_client as rpc; "
                f"l = rpc._SessionLock({repr(pipe_path)}); "
                "sys.exit(0 if l.acquire(0.2) else 1)"
            )
            p1 = subprocess.run([sys.executable, "-c", code])
            assert p1.returncode == 1, "Child process should fail to acquire held lock"

            lock.release()

            p2 = subprocess.run([sys.executable, "-c", code])
            assert p2.returncode == 0, "Child process should acquire lock after release"
        finally:
            lock.close()

    def test_session_lock_wait_abandoned(self):
        """(c) WAIT_ABANDONED: a child process acquires and exits without release -> parent acquire succeeds."""
        import subprocess

        unique_user = f"test_sl_aband_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)

        code = (
            "import sys; "
            "from cds_text_sync.engine import reverse_pipe_client as rpc; "
            f"l = rpc._SessionLock({repr(pipe_path)}); "
            "assert l.acquire(1.0); "
            "sys.exit(42)"
        )
        p = subprocess.run([sys.executable, "-c", code])
        assert p.returncode == 42

        parent_lock = rpc._SessionLock(pipe_path)
        try:
            acq = parent_lock.acquire(1.0)
            assert acq is True
            assert parent_lock.held is True
        finally:
            parent_lock.close()

    def test_lock_released_before_command_written(self):
        """(d) Lock released before command is written in send_command.

        Peer fake daemon checks after hello that another _SessionLock on the same
        name can be acquired while the command is still pending.
        """
        unique_user = f"test_sl_rel_cmd_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)
        rpc.configure(target=None, expect_project=None)
        client = rpc.ReversePipeClient(user=unique_user, timeout=5)

        peer_acquired_lock = []
        peer_error = []

        def peer():
            try:
                time.sleep(0.05)
                with open(pipe_path, "r+b", buffering=0) as f:
                    # 1. Read H1
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    f.read(msg_len)

                    # 2. Reply H2
                    h2 = {
                        "ok": True,
                        "hello": {
                            "protocol": 2,
                            "id": "ide-5555",
                            "pid": 5555,
                            "version": "3.2.0",
                            "poll_ms": 200,
                            "project": None,
                        },
                    }
                    f.write(_encode_msg(h2))
                    f.flush()

                    # Peer tests acquiring another _SessionLock on the same pipe
                    # (must succeed because target is chosen and client released lock before command)
                    time.sleep(0.05)
                    other_lock = rpc._SessionLock(pipe_path)
                    try:
                        acq = other_lock.acquire(0.5)
                        peer_acquired_lock.append(acq)
                    finally:
                        other_lock.close()

                    # 3. Read Command C
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    f.read(msg_len)

                    # 4. Reply A
                    resp_obj = {"ok": True, "data": {"pong": True}}
                    f.write(_encode_msg(resp_obj))
                    f.flush()
            except Exception as e:
                peer_error.append(e)

        t = threading.Thread(target=peer)
        t.start()

        # Target ide-5555 explicitly so client selects it without ambiguity check
        rpc.configure(target="ide-5555", expect_project=None)
        resp = client.send_command("ping")
        t.join(timeout=3)

        assert not peer_error, f"Peer error: {peer_error[0]}"
        assert peer_acquired_lock == [True], "Lock was not released before command was written"
        assert resp["ok"] is True

    def test_session_lock_noop_when_create_mutex_fails(self, monkeypatch):
        """(e) No-op / no crash when CreateMutexW returns NULL (monkeypatch to return 0).

        send_command still works unlocked.
        """
        unique_user = f"test_sl_nomutex_{os.getpid()}_{int(time.monotonic() * 1000)}"
        pipe_path = rpc.reverse_pipe_name(unique_user)
        client = rpc.ReversePipeClient(user=unique_user, timeout=5)

        # Monkeypatch CreateMutexW to return 0 (NULL)
        monkeypatch.setattr(rpc, "CreateMutexW", lambda sec, initial, name: 0)

        # Test _SessionLock directly
        lock = rpc._SessionLock(pipe_path)
        assert lock._handle is None
        assert lock.acquire(0.1) is False
        lock.release()
        lock.close()

        # Test send_command with fake daemon
        peer_error = []

        def peer():
            try:
                time.sleep(0.05)
                with open(pipe_path, "r+b", buffering=0) as f:
                    # 1. H1
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    f.read(msg_len)

                    # 2. H2
                    h2 = {
                        "ok": True,
                        "hello": {
                            "protocol": 2,
                            "id": "ide-4444",
                            "pid": 4444,
                            "version": "3.2.0",
                            "poll_ms": 200,
                            "project": None,
                        },
                    }
                    f.write(_encode_msg(h2))
                    f.flush()

                    # 3. C
                    raw_len = f.read(4)
                    (msg_len,) = struct.unpack("<I", raw_len)
                    f.read(msg_len)

                    # 4. A
                    resp_obj = {"ok": True, "data": {"pong": True}}
                    f.write(_encode_msg(resp_obj))
                    f.flush()
            except Exception as e:
                peer_error.append(e)

        t = threading.Thread(target=peer)
        t.start()

        rpc.configure(target="ide-4444", expect_project=None)
        resp = client.send_command("ping")
        t.join(timeout=3)

        assert not peer_error, f"Peer error: {peer_error[0]}"
        assert resp["ok"] is True

    def test_two_concurrent_targeted_clients_and_daemons_20_iterations(self):
        """(f) Two concurrent send_command clients and two fake daemons.

        Repeated 20 times: with --target-style _resolved_pid each client must
        reach ITS daemon without a miss.
        """
        for iteration in range(20):
            unique_user = f"test_sl_20iter_{os.getpid()}_{iteration}_{int(time.monotonic() * 1000)}"
            pipe_path = rpc.reverse_pipe_name(unique_user)

            stop_daemons = threading.Event()

            def fake_daemon(daemon_pid: int):
                while not stop_daemons.is_set():
                    try:
                        with open(pipe_path, "r+b", buffering=0) as f:
                            # 1. Read H1
                            raw_len = f.read(4)
                            if not raw_len:
                                continue
                            (msg_len,) = struct.unpack("<I", raw_len)
                            f.read(msg_len)

                            # 2. Reply H2
                            h2 = {
                                "ok": True,
                                "hello": {
                                    "protocol": 2,
                                    "id": f"ide-{daemon_pid}",
                                    "pid": daemon_pid,
                                    "version": "3.2.0",
                                    "poll_ms": 50,
                                    "project": {"name": f"PRJ_{daemon_pid}"},
                                },
                            }
                            f.write(_encode_msg(h2))
                            f.flush()

                            # 3. Read Command C or Release
                            raw_len = f.read(4)
                            if not raw_len:
                                continue
                            (msg_len,) = struct.unpack("<I", raw_len)
                            msg = json.loads(f.read(msg_len).decode("utf-8"))

                            if msg.get("release"):
                                continue

                            # 4. Reply Answer
                            resp = {
                                "ok": True,
                                "data": {"answered_by": daemon_pid},
                                "instance": {"id": f"ide-{daemon_pid}"},
                            }
                            f.write(_encode_msg(resp))
                            f.flush()
                    except Exception:
                        time.sleep(0.01)

            t_d1 = threading.Thread(target=fake_daemon, args=(1111,))
            t_d2 = threading.Thread(target=fake_daemon, args=(2222,))
            t_d1.daemon = True
            t_d2.daemon = True
            t_d1.start()
            t_d2.start()

            results = {}
            client_errors = []

            def run_client(target_pid: int):
                try:
                    c = rpc.ReversePipeClient(user=unique_user, timeout=5)
                    # Use _resolved_pid to target specifically without hitting global config race between threads
                    old_res = rpc._resolved_pid
                    rpc._resolved_pid = target_pid
                    try:
                        resp = c.send_command("ping")
                        results[target_pid] = resp
                    finally:
                        rpc._resolved_pid = old_res
                except Exception as e:
                    client_errors.append((target_pid, e))

            # Run both clients simultaneously
            c1 = threading.Thread(target=run_client, args=(1111,))
            c2 = threading.Thread(target=run_client, args=(2222,))
            c1.start()
            c2.start()
            c1.join(timeout=5)
            c2.join(timeout=5)

            stop_daemons.set()

            assert not client_errors, f"Iteration {iteration}: Client errors: {client_errors}"
            assert 1111 in results and 2222 in results
            assert results[1111]["data"]["answered_by"] == 1111
            assert results[2222]["data"]["answered_by"] == 2222

