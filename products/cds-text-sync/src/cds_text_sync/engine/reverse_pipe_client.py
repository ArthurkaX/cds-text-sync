# -*- coding: utf-8 -*-
"""
reverse_pipe_client.py — CLI-side client for the reverse-pipe daemon.

Architecture (reverse pipe):
  1. CLI creates a named pipe server (named pipe cds-cli-<user>)
  2. CLI waits (with timeout) for IDE to connect as client
  3. CLI writes command JSON
  4. IDE reads command, executes in main loop, writes response JSON
  5. CLI reads response and returns it

This is the reverse of the older IDE-hosted pipe architecture.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import struct
import time
import threading
from ctypes import wintypes
from typing import Any

# ── Win32 constants ────────────────────────────────────────────────────────

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255

INVALID_HANDLE_VALUE = -1

ERROR_PIPE_CONNECTED = 535
ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_BUSY = 231
ERROR_BROKEN_PIPE = 109
ERROR_IO_PENDING = 997

# ── Win32 API ──────────────────────────────────────────────────────────────

kernel32 = ctypes.windll.kernel32

CreateNamedPipeW = kernel32.CreateNamedPipeW
CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
]
CreateNamedPipeW.restype = wintypes.HANDLE

ConnectNamedPipe = kernel32.ConnectNamedPipe
ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
ConnectNamedPipe.restype = wintypes.BOOL

DisconnectNamedPipe = kernel32.DisconnectNamedPipe
DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
DisconnectNamedPipe.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

ReadFile = kernel32.ReadFile
ReadFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
ReadFile.restype = wintypes.BOOL

WriteFile = kernel32.WriteFile
WriteFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
WriteFile.restype = wintypes.BOOL

FlushFileBuffers = kernel32.FlushFileBuffers
FlushFileBuffers.argtypes = [wintypes.HANDLE]
FlushFileBuffers.restype = wintypes.BOOL

GetLastError = kernel32.GetLastError
GetLastError.restype = wintypes.DWORD

CreateEventW = kernel32.CreateEventW
CreateEventW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
CreateEventW.restype = wintypes.HANDLE

WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
WaitForSingleObject.restype = wintypes.DWORD

GetOverlappedResult = kernel32.GetOverlappedResult
GetOverlappedResult.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL,
]
GetOverlappedResult.restype = wintypes.BOOL

CancelIo = kernel32.CancelIo
CancelIo.argtypes = [wintypes.HANDLE]
CancelIo.restype = wintypes.BOOL


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.POINTER(ctypes.c_ulong)),
        ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


# ── Pipe name ──────────────────────────────────────────────────────────────


def reverse_pipe_name(user: str | None = None) -> str:
    """Get the named pipe path for the reverse-pipe daemon."""
    if user is None:
        user = os.environ.get("USERNAME", "default")
    return r"\\.\pipe\cds-cli-" + user


# ── Helper: read/write length-prefixed JSON via raw pipe handle ────────────


def _write_msg(handle, data: dict) -> None:
    msg = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack("<I", len(msg))
    written = wintypes.DWORD(0)
    ok = WriteFile(
        handle, header + msg, len(header) + len(msg), ctypes.byref(written), None
    )
    if not ok:
        err = GetLastError()
        raise RuntimeError(f"WriteFile failed (error {err})")
    # No FlushFileBuffers: local named pipe with FILE_FLAG_OVERLAPPED | PIPE_WAIT
    # already provides reliable message framing, and a flush forces pointless
    # kernel round-trips/filter-driver wake-ups on every command.


# Default maximum single response size (bytes). Raised to 32 MiB to support
# large application_tree / sync_export_text responses on big projects.
DEFAULT_MAX_RESPONSE_SIZE = 32 * 1024 * 1024


def _read_msg(handle, max_size: int = DEFAULT_MAX_RESPONSE_SIZE) -> dict:
    # Read 4-byte length
    raw_len = b""
    while len(raw_len) < 4:
        buf = ctypes.create_string_buffer(4)
        read = wintypes.DWORD(0)
        ok = ReadFile(handle, buf, 4 - len(raw_len), ctypes.byref(read), None)
        if not ok:
            err = GetLastError()
            raise RuntimeError(f"ReadFile failed reading header (error {err})")
        raw_len += buf.raw[: read.value]

    msg_len = struct.unpack("<I", raw_len[:4])[0]
    if msg_len == 0:
        return {}
    if msg_len > max_size:
        raise RuntimeError(f"Response too large: {msg_len} bytes")

    # Read body
    raw_msg = b""
    while len(raw_msg) < msg_len:
        chunk = min(msg_len - len(raw_msg), 65536)
        buf = ctypes.create_string_buffer(chunk)
        read = wintypes.DWORD(0)
        ok = ReadFile(handle, buf, chunk, ctypes.byref(read), None)
        if not ok:
            err = GetLastError()
            raise RuntimeError(f"ReadFile failed reading body (error {err})")
        raw_msg += buf.raw[: read.value]

    return json.loads(raw_msg.decode("utf-8"))


# ── Reverse Pipe Client ────────────────────────────────────────────────────

# Cache the last known IDE PID for smart timeout diagnostics
_last_ide_pid: int | None = None


class ReversePipeClient:
    """CLI creates a pipe server, IDE connects as client.

    Uses overlapped I/O for ConnectNamedPipe so we can timeout
    without blocking the calling thread.
    """

    def __init__(self, user: str | None = None, timeout: float = 30):
        self._pipe_path = reverse_pipe_name(user)
        self._timeout = timeout

    # ── Smart Timeout Diagnostics ──────────────────────────────────────────

    @staticmethod
    def _find_ide_pid() -> int | None:
        """Locate a running CODESYS process without a prior successful call.

        ``_last_ide_pid`` is process-global, and every ``cts`` run is a fresh
        process, so on the command that times out it is almost always None --
        which used to send every first-command timeout down the "make sure the
        daemon is running" path, including the case where it is running and
        merely busy. Looking the process up by image name keeps the real
        diagnosis (exited / not responding / busy) available from the start.
        """
        try:
            import subprocess

            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq CODESYS.exe", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in (r.stdout or "").strip().splitlines():
                fields = [f.strip('" ') for f in line.split('","')]
                if len(fields) >= 2 and fields[1].isdigit():
                    return int(fields[1])
        except Exception:
            pass
        return None

    @staticmethod
    def _diagnose_ide_timeout() -> str:
        """Check if the IDE process is still alive and responding."""
        global _last_ide_pid
        pid = _last_ide_pid
        if pid is None:
            pid = ReversePipeClient._find_ide_pid()
        if pid is None:
            return (
                "No CODESYS process is running, so nothing could answer. Start "
                "CODESYS and run Project_daemon.py inside it."
            )
        try:
            import subprocess

            # Check if PID exists via tasklist
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if str(pid) not in r.stdout:
                return f"IDE process (PID {pid}) has exited. Restart Project_daemon.py in CODESYS."
            # Extract process name from tasklist output
            name = "CODESYS"
            for line in r.stdout.strip().split("\n"):
                if str(pid) in line:
                    parts = line.split()
                    if parts:
                        name = parts[0]
                    break
            # Check CPU usage via powershell Get-Process
            ps_cmd = (
                f"Get-Process -Id {pid} | Format-List Id,ProcessName,CPU,Responding"
            )
            r2 = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = r2.stdout or ""
            # Parse output
            cpu_s = "?"
            responding = None
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("CPU:"):
                    cpu_s = line.split(":", 1)[-1].strip()
                elif line.startswith("Responding:"):
                    val = line.split(":", 1)[-1].strip()
                    responding = val.lower() == "true"
            if responding is False:
                return (
                    f"IDE process {name} (PID {pid}) is running but NOT responding. "
                    f"Likely blocked by a modal dialog. Check the CODESYS window "
                    f"and dismiss any dialogs/prompts."
                )
            try:
                cpu_val = float(cpu_s) if cpu_s != "?" else -1
                if 0 <= cpu_val < 0.1:
                    return (
                        f"IDE process {name} (PID {pid}) is running and responding "
                        f"but CPU is near-zero ({cpu_s}s total). It may be idle or "
                        f"waiting for user input. Check the CODESYS window."
                    )
            except ValueError:
                pass
            return (
                f"IDE process {name} (PID {pid}) is running. CPU: {cpu_s}s total. "
                f"It may still be busy. Try increasing --timeout."
            )
        except Exception:
            return (
                f"Could not inspect the IDE process (PID {pid}). Check that "
                f"Project_daemon.py is running inside CODESYS."
            )

    # Maximum retries for CreateNamedPipeW (to handle brief OS cleanup delay)
    MAX_CREATE_RETRIES = 3
    CREATE_RETRY_DELAY_MS = 50

    def send_command(self, method: str, params: dict | None = None) -> dict:
        global _last_ide_pid
        params = params or {}
        deadline = time.monotonic() + self._timeout

        # Create the named pipe server with overlapped flag and unlimited instances
        pipe_handle = -1
        for _ in range(self.MAX_CREATE_RETRIES):
            pipe_handle = CreateNamedPipeW(
                self._pipe_path,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES,  # max instances (allow multiple)
                65536,  # out buffer
                65536,  # in buffer
                0,  # default timeout
                None,  # default security
            )
            if pipe_handle > 0 and pipe_handle != INVALID_HANDLE_VALUE:
                break
            err = GetLastError()
            time.sleep(self.CREATE_RETRY_DELAY_MS / 1000.0)
        if pipe_handle <= 0 or pipe_handle == INVALID_HANDLE_VALUE:
            err = GetLastError()
            raise RuntimeError(
                f"Cannot create pipe server at {self._pipe_path} (error {err})"
            )

        # Create event for overlapped ConnectNamedPipe
        overlapped = OVERLAPPED()
        event = CreateEventW(None, True, False, None)
        overlapped.hEvent = event

        try:
            # Start overlapped ConnectNamedPipe
            result = ConnectNamedPipe(pipe_handle, ctypes.byref(overlapped))
            err = GetLastError()

            if not result:
                if err == ERROR_PIPE_CONNECTED:
                    # Already connected (rare race condition)
                    pass
                elif err == ERROR_IO_PENDING:
                    # Waiting for connection — wait with remaining budget
                    remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                    wait_result = WaitForSingleObject(event, remaining_ms)
                    if wait_result != 0:  # 0 = WAIT_OBJECT_0
                        # Timeout — check IDE process status for a helpful hint
                        hint = self._diagnose_ide_timeout()
                        CancelIo(pipe_handle)
                        raise RuntimeError(
                            f"Timeout ({self._timeout}s) waiting for IDE to connect to "
                            f"{self._pipe_path}. The daemon never picked up this "
                            f"request: it is either not running, or still running an "
                            f"earlier command -- the command loop is single-threaded, "
                            f"so one slow command makes every other one time out here. "
                            f"{hint}"
                        )
                    # Verify connection result with GetOverlappedResult
                    bytes_xferd = wintypes.DWORD(0)
                    ok = GetOverlappedResult(
                        pipe_handle,
                        ctypes.byref(overlapped),
                        ctypes.byref(bytes_xferd),
                        True,
                    )
                    if not ok:
                        err = GetLastError()
                        CancelIo(pipe_handle)
                        raise RuntimeError(
                            f"Overlapped ConnectNamedPipe failed (error {err})"
                        )
                else:
                    CancelIo(pipe_handle)
                    raise RuntimeError(f"ConnectNamedPipe failed (error {err})")

            # Connected! Use blocking I/O for the rest of the exchange.

            # Write command
            cmd = {"method": method, "params": params}
            _write_msg(pipe_handle, cmd)

            # Read response with the same deadline. CODESYS API calls can
            # block after the IDE has already accepted the pipe request.
            box: dict[str, Any] = {}

            def _reader():
                try:
                    box["response"] = _read_msg(pipe_handle)
                except Exception as exc:
                    box["error"] = exc

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()
            reader.join(max(0, deadline - time.monotonic()))
            if reader.is_alive():
                CancelIo(pipe_handle)
                CloseHandle(pipe_handle)
                pipe_handle = -1
                raise RuntimeError(
                    f"Timeout ({self._timeout}s) waiting for IDE response to "
                    f"'{method}'. Giving up here does NOT cancel the command: "
                    f"the daemon keeps running it, so the IDE may still change "
                    f"after this error. On a large project export/compare/"
                    f"import legitimately take minutes -- retry with a bigger "
                    f"--timeout before assuming a hang. A real hang looks "
                    f"different: 'cts ping' stops answering too, and then you "
                    f"check CODESYS for a modal dialog or restart "
                    f"Project_daemon.py."
                )
            if "error" in box:
                raise box["error"]
            response = box.get("response", {})

            # Cache PID from responses that include it
            if isinstance(response, dict):
                data = response.get("data", response)
                if isinstance(data, dict):
                    pid = data.get("pid")
                    if pid is not None:
                        _last_ide_pid = int(pid)

            return response

        finally:
            # Clean up
            with contextlib.suppress(Exception):
                CancelIo(pipe_handle)
            with contextlib.suppress(Exception):
                DisconnectNamedPipe(pipe_handle)
            with contextlib.suppress(Exception):
                CloseHandle(pipe_handle)
            with contextlib.suppress(Exception):
                CloseHandle(event)


# ── Convenience ────────────────────────────────────────────────────────────


def send_command_reverse(
    method: str,
    params: dict | None = None,
    user: str | None = None,
    timeout: float = 30,
) -> dict:
    """Send a command using reverse-pipe protocol.

    Creates the pipe server and waits for the IDE loop to connect.
    """
    client = ReversePipeClient(user=user, timeout=timeout)
    return client.send_command(method, params)


# ── Demo ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Reverse Pipe Client Demo")
    print("Creating pipe server at:", reverse_pipe_name())
    print("Waiting for IDE to connect (30s timeout)...")

    try:
        resp = send_command_reverse("ping", timeout=30)
        print("Response:", json.dumps(resp, indent=2, ensure_ascii=False))
    except RuntimeError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
