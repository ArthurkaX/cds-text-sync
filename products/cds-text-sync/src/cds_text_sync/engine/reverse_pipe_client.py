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
import random
import struct
import sys
import time
from ctypes import wintypes
from typing import Any

from cts_shared.coerce import as_bool

from cds_text_sync.engine.pipe_targets import (
    LEGACY,
    Hello,
    TargetError,
    decide,
    match_project,
    parse_target,
)

# ── Win32 constants ────────────────────────────────────────────────────────

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255

INVALID_HANDLE_VALUE = -1

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_ABANDONED = 0x00000080

ERROR_PIPE_CONNECTED = 535
ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_BUSY = 231
ERROR_BROKEN_PIPE = 109
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995

# ── Win32 API ──────────────────────────────────────────────────────────────

class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", getattr(wintypes, "DWORD", ctypes.c_uint32)),
        ("OffsetHigh", getattr(wintypes, "DWORD", ctypes.c_uint32)),
        ("hEvent", getattr(wintypes, "HANDLE", ctypes.c_void_p)),
    ]


LPOVERLAPPED = ctypes.POINTER(OVERLAPPED)


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", getattr(wintypes, "DWORD", ctypes.c_uint32)),
        ("lpSecurityDescriptor", getattr(wintypes, "LPVOID", ctypes.c_void_p)),
        ("bInheritHandle", getattr(wintypes, "BOOL", ctypes.c_int)),
    ]


_pipe_security: SECURITY_ATTRIBUTES | None = None

if sys.platform == "win32" and hasattr(ctypes, "windll"):
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
    ConnectNamedPipe.argtypes = [wintypes.HANDLE, LPOVERLAPPED]
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
        LPOVERLAPPED,
    ]
    ReadFile.restype = wintypes.BOOL

    WriteFile = kernel32.WriteFile
    WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        LPOVERLAPPED,
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
        LPOVERLAPPED,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    GetOverlappedResult.restype = wintypes.BOOL

    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE

    ReleaseMutex = kernel32.ReleaseMutex
    ReleaseMutex.argtypes = [wintypes.HANDLE]
    ReleaseMutex.restype = wintypes.BOOL

    CancelIo = kernel32.CancelIo
    CancelIo.argtypes = [wintypes.HANDLE]
    CancelIo.restype = wintypes.BOOL

    CancelIoEx = kernel32.CancelIoEx
    CancelIoEx.argtypes = [wintypes.HANDLE, LPOVERLAPPED]
    CancelIoEx.restype = wintypes.BOOL
else:
    kernel32 = None
    CreateNamedPipeW = None
    ConnectNamedPipe = None
    DisconnectNamedPipe = None
    CloseHandle = None
    ReadFile = None
    WriteFile = None
    FlushFileBuffers = None
    GetLastError = None
    CreateEventW = None
    CreateMutexW = None
    ReleaseMutex = None
    WaitForSingleObject = None
    GetOverlappedResult = None
    CancelIo = None
    CancelIoEx = None


def _current_user_sid() -> str:
    advapi32 = ctypes.windll.advapi32
    TOKEN_QUERY = 0x0008
    TOKEN_USER = 1
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        wintypes.HANDLE(-1), TOKEN_QUERY, ctypes.byref(token)  # current process
    ):
        raise ctypes.WinError()
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, TOKEN_USER, buf, size, ctypes.byref(size)
        ):
            raise ctypes.WinError()
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is PSID.
        psid = ctypes.cast(buf, ctypes.POINTER(wintypes.LPVOID))[0]
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            wintypes.LPVOID(psid), ctypes.byref(text)
        ):
            raise ctypes.WinError()
        try:
            return text.value
        finally:
            kernel32.LocalFree(ctypes.cast(text, wintypes.LPVOID))
    finally:
        CloseHandle(token)


def _user_dacl_enabled() -> bool:
    return as_bool(os.environ.get("CTS_PIPE_USER_DACL", ""))


def ssh_dacl_hint() -> str:
    """Hint for an SSH session whose pipe the desktop IDE cannot open, or ''."""
    if not os.environ.get("SSH_CONNECTION") or _user_dacl_enabled():
        return ""
    return (
        "cts runs over SSH without CTS_PIPE_USER_DACL=1, so the desktop IDE "
        "cannot open this pipe. Run `setx CTS_PIPE_USER_DACL 1` once on "
        "this machine and reconnect."
    )


def _with_ssh_hint(err: TargetError, hellos: dict) -> TargetError:
    """Append ssh_dacl_hint() to err when no IDE answered at all."""
    hint = "" if hellos else ssh_dacl_hint()
    if not hint:
        return err
    return TargetError(err.code, f"{err} {hint}", instances=err.instances)


def _pipe_security_attributes():
    """SECURITY_ATTRIBUTES for CreateNamedPipeW, or None for default security."""
    global _pipe_security
    if not _user_dacl_enabled():
        return None
    if _pipe_security is None:
        sddl = "D:(A;;GA;;;{0})(A;;GA;;;SY)".format(_current_user_sid())
        sd = wintypes.LPVOID()
        if not ctypes.windll.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(sd), None
        ):
            raise ctypes.WinError()
        # Kept for the process lifetime; never freed.
        _pipe_security = SECURITY_ATTRIBUTES(
            ctypes.sizeof(SECURITY_ATTRIBUTES), sd, False
        )
    return ctypes.byref(_pipe_security)


# ── Pipe name ──────────────────────────────────────────────────────────────


def reverse_pipe_name(user: str | None = None) -> str:
    """Get the named pipe path for the reverse-pipe daemon."""
    if user is None:
        user = os.environ.get("USERNAME", "default")
    return r"\\.\pipe\cds-cli-" + user


# ── Overlapped Operation Primitive ─────────────────────────────────────────


def _overlapped_op(
    handle: int,
    buf: Any,
    length: int,
    is_read: bool,
    deadline: float,
    cmd_name: str = "",
) -> int:
    """Perform one overlapped ReadFile or WriteFile operation with a deadline.

    Returns the actual number of transferred bytes.
    """
    event = CreateEventW(None, True, False, None)
    if not event:
        err = GetLastError()
        raise RuntimeError(f"CreateEventW failed (error {err})")

    overlapped = OVERLAPPED()
    overlapped.hEvent = event
    transferred = wintypes.DWORD(0)

    try:
        if is_read:
            ok = ReadFile(
                handle,
                buf,
                length,
                ctypes.byref(transferred),
                ctypes.byref(overlapped),
            )
        else:
            ok = WriteFile(
                handle,
                buf,
                length,
                ctypes.byref(transferred),
                ctypes.byref(overlapped),
            )

        if ok:
            # Immediate synchronous completion
            return transferred.value

        err = GetLastError()
        if is_read and err == ERROR_BROKEN_PIPE:
            return 0
        if err != ERROR_IO_PENDING:
            op_name = "ReadFile" if is_read else "WriteFile"
            raise RuntimeError(f"{op_name} failed (error {err})")

        # Asynchronous I/O pending: wait until event is signaled or deadline expires
        remaining_s = deadline - time.monotonic()
        remaining_ms = max(0, int(remaining_s * 1000))
        wait_res = WaitForSingleObject(event, remaining_ms)

        if wait_res == WAIT_OBJECT_0:
            ok = GetOverlappedResult(
                handle,
                ctypes.byref(overlapped),
                ctypes.byref(transferred),
                False,
            )
            if ok:
                return transferred.value
            err = GetLastError()
            if is_read and err == ERROR_BROKEN_PIPE:
                return 0
            op_name = "ReadFile" if is_read else "WriteFile"
            raise RuntimeError(f"{op_name} overlapped completion failed (error {err})")

        # Timeout or wait failure
        with contextlib.suppress(Exception):
            CancelIoEx(handle, ctypes.byref(overlapped))
        with contextlib.suppress(Exception):
            GetOverlappedResult(
                handle,
                ctypes.byref(overlapped),
                ctypes.byref(transferred),
                True,
            )

        if wait_res == WAIT_TIMEOUT or remaining_s <= 0:
            if is_read:
                raise RuntimeError(
                    f"Timeout waiting for IDE response to "
                    f"'{cmd_name}'. Giving up here does NOT cancel the command: "
                    f"the daemon keeps running it, so the IDE may still change "
                    f"after this error. On a large project export/compare/"
                    f"import legitimately take minutes -- retry with a bigger "
                    f"--timeout before assuming a hang. A real hang looks "
                    f"different: 'cts ping' stops answering too, and then you "
                    f"check CODESYS for a modal dialog or restart "
                    f"Project_daemon.py."
                )
            raise RuntimeError(f"Timeout writing to IDE pipe for '{cmd_name}'")

        raise RuntimeError(f"WaitForSingleObject failed (result {wait_res})")

    finally:
        with contextlib.suppress(Exception):
            CloseHandle(event)


# ── Helper: read/write length-prefixed JSON via raw pipe handle ────────────


def _write_msg(handle: int, data: dict, deadline: float, cmd_name: str = "") -> None:
    msg = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack("<I", len(msg))
    data_to_send = header + msg
    total_len = len(data_to_send)
    offset = 0

    while offset < total_len:
        chunk = data_to_send[offset:]
        buf = ctypes.create_string_buffer(chunk)
        written = _overlapped_op(
            handle,
            buf,
            len(chunk),
            is_read=False,
            deadline=deadline,
            cmd_name=cmd_name,
        )
        if written <= 0:
            raise RuntimeError("Pipe disconnected or broken during write")
        offset += written


# Default maximum single response size (bytes). Raised to 32 MiB to support
# large application_tree / sync_export_text responses on big projects.
DEFAULT_MAX_RESPONSE_SIZE = 32 * 1024 * 1024


def _read_msg(
    handle: int,
    deadline: float,
    cmd_name: str = "",
    max_size: int = DEFAULT_MAX_RESPONSE_SIZE,
) -> dict:
    # Read 4-byte length
    raw_len = bytearray()
    while len(raw_len) < 4:
        needed = 4 - len(raw_len)
        buf = ctypes.create_string_buffer(needed)
        n = _overlapped_op(
            handle,
            buf,
            needed,
            is_read=True,
            deadline=deadline,
            cmd_name=cmd_name,
        )
        if n == 0:
            raise RuntimeError("Pipe disconnected while reading header")
        raw_len.extend(buf.raw[:n])

    (msg_len,) = struct.unpack("<I", bytes(raw_len[:4]))
    if msg_len == 0:
        return {}
    if msg_len > max_size:
        raise RuntimeError(f"Response too large: {msg_len} bytes")

    # Read body
    raw_msg = bytearray()
    while len(raw_msg) < msg_len:
        chunk_size = min(msg_len - len(raw_msg), 65536)
        buf = ctypes.create_string_buffer(chunk_size)
        n = _overlapped_op(
            handle,
            buf,
            chunk_size,
            is_read=True,
            deadline=deadline,
            cmd_name=cmd_name,
        )
        if n == 0:
            raise RuntimeError("Pipe disconnected while reading body")
        raw_msg.extend(buf.raw[:n])

    return json.loads(bytes(raw_msg).decode("utf-8"))


# ── Target Resolution & Pipe Targets ───────────────────────────────────────

# Cache for resolved target PID, last instance info, and process list
_configured_target: str | int | None = None
_configured_expect_project: str | None = None
_resolved_pid: int | None = None
_last_instance: dict[str, Any] | None = None
_cached_codesys_pids: set[int] | None = None
_codesys_pids_listed = False


def configure(
    target: str | int | None = None,
    expect_project: str | None = None,
) -> None:
    """Configure reverse pipe target and expected project for this CLI process."""
    global _configured_target, _configured_expect_project, _resolved_pid
    if target is None:
        target = os.environ.get("CTS_TARGET")
    _configured_target = target
    _configured_expect_project = expect_project
    _resolved_pid = None


def get_last_instance() -> dict[str, Any] | None:
    """Return the last instance metadata seen by reverse pipe client."""
    return _last_instance


def _list_codesys_pids() -> set[int] | None:
    """Running CODESYS.exe process IDs, or None when the list could not be taken.

    None is not the same as an empty set: the empty set means tasklist ran and
    found no IDE, while None means we do not know -- tasklist is missing or
    refused (a non-Windows host driving a remote IDE has no tasklist at all).
    Only the diagnostic distinguishes the two; the target decision cannot, and
    must go on working exactly as before in that case.

    The outcome is cached either way. A CLI invocation lives for one command,
    so the process list cannot meaningfully change under it, and a failing
    tasklist would otherwise be retried on every discovery loop.
    """
    global _cached_codesys_pids, _codesys_pids_listed
    if _codesys_pids_listed:
        return _cached_codesys_pids
    _codesys_pids_listed = True
    pids: set[int] = set()
    try:
        import subprocess

        user = os.environ.get("USERNAME")
        cmd = ["tasklist", "/FI", "IMAGENAME eq CODESYS.exe", "/NH", "/FO", "CSV"]
        if user:
            cmd = [
                "tasklist",
                "/FI",
                "IMAGENAME eq CODESYS.exe",
                "/FI",
                f"USERNAME eq {user}",
                "/NH",
                "/FO",
                "CSV",
            ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        for line in (r.stdout or "").strip().splitlines():
            fields = [f.strip('" ') for f in line.split('","')]
            if len(fields) >= 2 and fields[1].isdigit():
                pids.add(int(fields[1]))
    except Exception:
        return None
    _cached_codesys_pids = pids
    return pids


class _PipeListener:
    """Helper managing a single named pipe server instance and overlapped ConnectNamedPipe."""

    def __init__(self, pipe_path: str):
        self.pipe_path = pipe_path
        self.handle = -1
        self.event = None
        self.overlapped: OVERLAPPED | None = None
        self.connected_immediate = False
        self._create_and_connect()

    def _create_and_connect(self) -> None:
        if CreateNamedPipeW is None:
            return
        for _ in range(3):
            self.handle = CreateNamedPipeW(
                self.pipe_path,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES,
                65536,
                65536,
                0,
                _pipe_security_attributes(),
            )
            if self.handle > 0 and self.handle != INVALID_HANDLE_VALUE:
                break
            time.sleep(0.05)
        if self.handle <= 0 or self.handle == INVALID_HANDLE_VALUE:
            err = GetLastError() if GetLastError else 0
            raise RuntimeError(f"Cannot create pipe server at {self.pipe_path} (error {err})")

        self.event = CreateEventW(None, True, False, None)
        self.overlapped = OVERLAPPED()
        self.overlapped.hEvent = self.event

        res = ConnectNamedPipe(self.handle, ctypes.byref(self.overlapped))
        err = GetLastError() if GetLastError else 0
        if res:
            self.connected_immediate = True
        elif err == ERROR_PIPE_CONNECTED:
            self.connected_immediate = True
        elif err == ERROR_IO_PENDING:
            self.connected_immediate = False
        else:
            self.close()
            raise RuntimeError(f"ConnectNamedPipe failed (error {err})")

    def wait(self, timeout_s: float) -> bool:
        if self.connected_immediate:
            return True
        if not self.event or self.handle <= 0:
            return False
        timeout_ms = max(0, int(timeout_s * 1000))
        wait_res = WaitForSingleObject(self.event, timeout_ms)
        if wait_res == WAIT_OBJECT_0:
            bytes_xferd = wintypes.DWORD(0)
            ok = GetOverlappedResult(
                self.handle,
                ctypes.byref(self.overlapped),
                ctypes.byref(bytes_xferd),
                True,
            )
            err = GetLastError() if GetLastError else 0
            if ok or err == ERROR_PIPE_CONNECTED:
                return True
            return False
        return False

    def close(self) -> None:
        if self.handle > 0 and self.handle != INVALID_HANDLE_VALUE:
            if CancelIo:
                with contextlib.suppress(Exception):
                    CancelIo(self.handle)
            if DisconnectNamedPipe:
                with contextlib.suppress(Exception):
                    DisconnectNamedPipe(self.handle)
            if CloseHandle:
                with contextlib.suppress(Exception):
                    CloseHandle(self.handle)
            self.handle = -1
        if self.event:
            if CloseHandle:
                with contextlib.suppress(Exception):
                    CloseHandle(self.event)
            self.event = None


# Longest a targeted call keeps the session lock while it waits for a daemon
# that is not answering (usually busy with a long command). Past that it lets
# go and queues again, so a call aimed at a busy IDE never starves calls
# aimed at the other one.
_SESSION_LOCK_SLICE_S = 1.0
_SESSION_LOCK_WAIT_S = 10.0


class _SessionLock:
    """Cross-process lock around the pipe-server phase of a CLI call.

    The reverse pipe has one name per user, and every ``cts`` process serves it.
    A daemon connects to whichever server accepts first, so two ``cts`` running
    at once split the IDEs between them and each sees only one -- a targeted
    call then reports ``unknown_target`` for an IDE that is up, and an untargeted
    one silently talks to the only IDE it happened to see.

    The lock covers only creating the server, the hello exchange and choosing
    the target. It is released before the command itself is sent, so a long
    ``export`` in one IDE does not hold up calls to the other.

    ``Global\\`` because the pipe is machine-wide and an SSH logon and the
    desktop session are different sessions. If the mutex cannot be created or
    opened (e.g. it belongs to another account) the call proceeds unlocked,
    as it did before the lock existed.
    """

    def __init__(self, pipe_path: str):
        self._handle = None
        self.held = False
        if CreateMutexW is None:
            return
        name = "Global\\" + pipe_path.rsplit("\\", 1)[-1] + "-session"
        with contextlib.suppress(Exception):
            handle = CreateMutexW(None, False, name)
            if handle and handle != INVALID_HANDLE_VALUE:
                self._handle = handle

    def acquire(self, timeout_s: float = _SESSION_LOCK_WAIT_S) -> bool:
        if not self._handle or self.held:
            return self.held
        res = WaitForSingleObject(self._handle, max(0, int(timeout_s * 1000)))
        # WAIT_ABANDONED: the previous owner died holding it; we own it now.
        self.held = res in (WAIT_OBJECT_0, WAIT_ABANDONED)
        return self.held

    def release(self) -> None:
        if self.held:
            self.held = False
            with contextlib.suppress(Exception):
                ReleaseMutex(self._handle)

    def close(self) -> None:
        self.release()
        if self._handle:
            with contextlib.suppress(Exception):
                CloseHandle(self._handle)
            self._handle = None


def _send_release_and_close(handle: int) -> None:
    """Send R release message and close pipe handle.

    The release is a courtesy, not the signal: the daemon also returns to its
    poll loop when the connection simply drops (ide_reverse_pipe_loop.py, the
    ``next_msg is None`` branch), and the close below always happens. So a
    failed release is swallowed on purpose -- this runs while unwinding, often
    from a ``finally`` of a loop holding several connections, and letting it
    raise would abort the cleanup of the handles after this one, which is the
    part that actually matters.
    """
    if handle <= 0 or handle == INVALID_HANDLE_VALUE:
        return
    try:
        _write_msg(handle, {"release": True}, deadline=time.monotonic() + 0.5, cmd_name="release")
    except Exception:
        pass
    finally:
        if CancelIo:
            with contextlib.suppress(Exception):
                CancelIo(handle)
        if DisconnectNamedPipe:
            with contextlib.suppress(Exception):
                DisconnectNamedPipe(handle)
        if CloseHandle:
            with contextlib.suppress(Exception):
                CloseHandle(handle)


def discover(budget_s: float = 1.0, user: str | None = None) -> list[Hello]:
    """Discover live CODESYS daemon instances within budget_s seconds.

    Returns a list of Hello objects for all discovered daemons.
    All connected daemons are cleanly released.
    """
    if sys.platform != "win32" or not hasattr(ctypes, "windll") or CreateNamedPipeW is None:
        return []
    pipe_path = reverse_pipe_name(user)
    deadline = time.monotonic() + budget_s
    hellos: dict[int, Hello] = {}
    held_conns: list[int] = []
    listener: _PipeListener | None = None
    lock = _SessionLock(pipe_path)
    try:
        lock.acquire()
        listener = _PipeListener(pipe_path)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if listener.wait(min(0.2, remaining)):
                conn = listener.handle
                listener = _PipeListener(pipe_path)
                try:
                    _write_msg(
                        conn,
                        {"method": "ping", "params": {"hello": 2}},
                        deadline=time.monotonic() + 1.0,
                        cmd_name="ping",
                    )
                    reply = _read_msg(conn, deadline=time.monotonic() + 1.0, cmd_name="ping")
                    if isinstance(reply, dict) and "hello" in reply:
                        h = Hello.from_dict(reply)
                        hellos[h.pid] = h
                        held_conns.append(conn)
                    else:
                        with contextlib.suppress(Exception):
                            CloseHandle(conn)
                except Exception:
                    with contextlib.suppress(Exception):
                        CloseHandle(conn)
    finally:
        if listener:
            listener.close()
        lock.release()
        for c in held_conns:
            _send_release_and_close(c)
        lock.close()
    return list(hellos.values())


# ── Reverse Pipe Client ────────────────────────────────────────────────────

# Cache the last known IDE PID for smart timeout diagnostics
_last_ide_pid: int | None = None


class ReversePipeClient:
    """CLI creates a pipe server, IDE connects as client.

    Uses overlapped I/O with protocol v2 session support (hello, release, targeting).
    """

    def __init__(self, user: str | None = None, timeout: float = 30):
        self._pipe_path = reverse_pipe_name(user)
        self._timeout = timeout

    @staticmethod
    def _find_ide_pid() -> int | None:
        """Locate a running CODESYS process."""
        pids = _list_codesys_pids()
        if pids:
            return next(iter(pids))
        return None

    @staticmethod
    def _diagnose_ide_timeout(target_pid: int | None = None) -> str:
        """Check if the IDE process is still alive and responding."""
        global _last_ide_pid
        pid = target_pid or _last_ide_pid or ReversePipeClient._find_ide_pid()
        if pid is None:
            if _list_codesys_pids() is None:
                return (
                    "Could not list CODESYS processes (tasklist failed), so it "
                    "is unknown whether the IDE is running. Check that the IDE "
                    "is up and Project_daemon.py is running inside it."
                )
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

    def send_command(self, method: str, params: dict | None = None) -> dict:
        global _last_ide_pid, _resolved_pid, _last_instance
        params = params or {}
        deadline = time.monotonic() + self._timeout

        # Determine target PID
        target_pid = None
        if _resolved_pid is not None:
            target_pid = _resolved_pid
        elif _configured_target is not None:
            target_pid = parse_target(_configured_target)

        codesys_pids = None if target_pid is not None else _list_codesys_pids()

        discovery_ms = int(os.environ.get("CTS_DISCOVERY_MS", 400))
        discovery_budget_s = discovery_ms / 1000.0
        window_end: float | None = None

        hellos: dict[int, Hello] = {}
        held_conns: dict[int, int] = {}
        legacy_pids: set[int] = set()

        lock = _SessionLock(self._pipe_path)
        lock.acquire()
        lock_since = time.monotonic()
        listener = _PipeListener(self._pipe_path)

        try:
            while time.monotonic() < deadline:
                current_time = time.monotonic()
                if window_end is not None:
                    wait_timeout = min(deadline - current_time, max(0.0, window_end - current_time))
                else:
                    wait_timeout = deadline - current_time

                if wait_timeout < 0:
                    wait_timeout = 0
                if target_pid is not None and lock.held:
                    wait_timeout = min(
                        wait_timeout, max(0.0, lock_since + _SESSION_LOCK_SLICE_S - current_time)
                    )

                connected = listener.wait(wait_timeout)
                if connected:
                    conn = listener.handle
                    listener = _PipeListener(self._pipe_path)

                    try:
                        _write_msg(
                            conn,
                            {"method": "ping", "params": {"hello": 2}},
                            deadline=time.monotonic() + 2.0,
                            cmd_name="ping",
                        )
                        reply = _read_msg(conn, deadline=time.monotonic() + 2.0, cmd_name="ping")
                    except Exception:
                        with contextlib.suppress(Exception):
                            CloseHandle(conn)
                        conn = -1
                        reply = None

                    if conn > 0 and reply is not None:
                        if isinstance(reply, dict) and "hello" in reply:
                            h = Hello.from_dict(reply)
                            if h.pid in held_conns:
                                _send_release_and_close(held_conns.pop(h.pid))
                            hellos[h.pid] = h
                            held_conns[h.pid] = conn

                            if target_pid is not None and h.pid != target_pid:
                                _send_release_and_close(held_conns.pop(h.pid))

                            if target_pid is None and window_end is None:
                                window_end = time.monotonic() + discovery_budget_s
                        elif isinstance(reply, dict):
                            lp = reply.get("data", {}).get("pid") or reply.get("pid")
                            if lp:
                                legacy_pids.add(int(lp))
                            with contextlib.suppress(Exception):
                                CloseHandle(conn)
                            if target_pid is None and window_end is None:
                                window_end = time.monotonic() + discovery_budget_s

                if (
                    not connected
                    and target_pid is not None
                    and lock.held
                    and time.monotonic() - lock_since >= _SESSION_LOCK_SLICE_S
                ):
                    # The target has not answered for a while: give other calls a
                    # turn at the pipe. Nothing to lose -- in targeted mode a
                    # daemon that is not the target is released on arrival, and
                    # the target itself is used the moment it says hello.
                    listener.close()
                    lock.release()
                    time.sleep(random.uniform(0.03, 0.1))
                    lock.acquire()
                    lock_since = time.monotonic()
                    listener = _PipeListener(self._pipe_path)

                window_is_over = (
                    window_end is not None and time.monotonic() >= window_end
                ) or (time.monotonic() >= deadline)

                decision = decide(
                    hellos,
                    legacy_pids=legacy_pids,
                    target_pid=target_pid,
                    codesys_pids=codesys_pids,
                    window_over=window_is_over,
                )

                if decision.kind == "send":
                    listener.close()
                    if decision.target != LEGACY:
                        # Target chosen: the rest of the call runs over the held
                        # connection, so the pipe is free for the next cts.
                        lock.release()
                    if decision.target == LEGACY:
                        for h_conn in list(held_conns.values()):
                            _send_release_and_close(h_conn)
                        held_conns.clear()

                        legacy_listener = _PipeListener(self._pipe_path)
                        try:
                            ok = legacy_listener.wait(max(0.1, deadline - time.monotonic()))
                            if not ok:
                                hint = self._diagnose_ide_timeout(target_pid=target_pid)
                                raise RuntimeError(f"Timeout waiting for legacy IDE to connect. {hint}")
                            l_conn = legacy_listener.handle
                            cmd = {"method": method, "params": params}
                            _write_msg(l_conn, cmd, deadline=deadline, cmd_name=method)
                            response = _read_msg(l_conn, deadline=deadline, cmd_name=method)
                            if isinstance(response, dict):
                                data = response.get("data", response)
                                if isinstance(data, dict) and data.get("pid"):
                                    _last_ide_pid = int(data["pid"])
                            return response
                        finally:
                            legacy_listener.close()

                    elif isinstance(decision.target, Hello):
                        chosen = decision.target
                        chosen_conn = held_conns.pop(chosen.pid)
                        for h_conn in list(held_conns.values()):
                            _send_release_and_close(h_conn)
                        held_conns.clear()

                        if _configured_expect_project:
                            if not match_project(chosen.project, _configured_expect_project):
                                curr_desc = (
                                    chosen.project.get("name") if chosen.project else None
                                ) or "no project"
                                _send_release_and_close(chosen_conn)
                                raise TargetError(
                                    "project_mismatch",
                                    (
                                        f"error: project mismatch: expected '{_configured_expect_project}', "
                                        f"but IDE {chosen.id} has '{curr_desc}' open."
                                    ),
                                    instances=[chosen],
                                )

                        _resolved_pid = chosen.pid
                        _last_ide_pid = chosen.pid

                        try:
                            cmd = {"method": method, "params": params}
                            _write_msg(chosen_conn, cmd, deadline=deadline, cmd_name=method)
                            response = _read_msg(chosen_conn, deadline=deadline, cmd_name=method)

                            if isinstance(response, dict) and "instance" in response:
                                _last_instance = response["instance"]
                            else:
                                _last_instance = {"id": chosen.id, "project": chosen.project}

                            return response
                        finally:
                            with contextlib.suppress(Exception):
                                CloseHandle(chosen_conn)

                elif decision.kind == "error":
                    listener.close()
                    for h_conn in list(held_conns.values()):
                        _send_release_and_close(h_conn)
                    held_conns.clear()
                    raise _with_ssh_hint(decision.error, hellos)

            listener.close()
            for h_conn in list(held_conns.values()):
                _send_release_and_close(h_conn)
            held_conns.clear()

            if target_pid is not None:
                final_dec = decide(hellos, legacy_pids, target_pid, codesys_pids, window_over=True)
                if final_dec.kind == "error":
                    raise _with_ssh_hint(final_dec.error, hellos)

            hint = ssh_dacl_hint() or self._diagnose_ide_timeout(target_pid=target_pid)
            raise RuntimeError(
                f"Timeout ({self._timeout}s) waiting for IDE to connect to "
                f"{self._pipe_path}. The daemon never picked up this "
                f"request: it is either not running, or still running an "
                f"earlier command -- the command loop is single-threaded, "
                f"so one slow command makes every other one time out here. "
                f"{hint}"
            )

        finally:
            if listener:
                listener.close()
            lock.release()
            for h_conn in list(held_conns.values()):
                _send_release_and_close(h_conn)
            held_conns.clear()
            lock.close()


# ── Convenience ────────────────────────────────────────────────────────────


def send_command_reverse(
    method: str,
    params: dict | None = None,
    user: str | None = None,
    timeout: float = 30,
) -> dict:
    """Send a command using reverse-pipe protocol."""
    client = ReversePipeClient(user=user, timeout=timeout)
    return client.send_command(method, params)

