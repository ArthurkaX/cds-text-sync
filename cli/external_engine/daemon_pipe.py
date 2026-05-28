# -*- coding: utf-8 -*-
"""
daemon_pipe.py — Named pipe helpers for Python 3 side.
Communicates with ide_daemon.pyw running inside CODESYS.
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes
from typing import Any

# ── Win32 constants ────────────────────────────────────────────────────────

PIPE_ACCESS_DUPLEX    = 0x00000003
PIPE_TYPE_MESSAGE     = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT             = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

FILE_FLAG_OVERLAPPED = 0x40000000
OPEN_EXISTING        = 0x00000003

GENERIC_READ  = 0x80000000
GENERIC_WRITE = 0x40000000

NMPWAIT_USE_DEFAULT_WAIT = 0x00000000
NMPWAIT_WAIT_FOREVER     = 0xFFFFFFFF

ERROR_PIPE_BUSY      = 231
ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_NO_DATA        = 232
ERROR_MORE_DATA      = 234

# ── Win32 API ──────────────────────────────────────────────────────────────

kernel32 = ctypes.windll.kernel32

CreateNamedPipeW = kernel32.CreateNamedPipeW
CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR,    # lpName
    wintypes.DWORD,      # dwOpenMode
    wintypes.DWORD,      # dwPipeMode
    wintypes.DWORD,      # nMaxInstances
    wintypes.DWORD,      # nOutBufferSize
    wintypes.DWORD,      # nInBufferSize
    wintypes.DWORD,      # nDefaultTimeOut
    wintypes.LPVOID,     # lpSecurityAttributes
]
CreateNamedPipeW.restype = wintypes.HANDLE

ConnectNamedPipe = kernel32.ConnectNamedPipe
ConnectNamedPipe.argtypes = [
    wintypes.HANDLE,     # hNamedPipe
    wintypes.LPVOID,     # lpOverlapped
]
ConnectNamedPipe.restype = wintypes.BOOL

DisconnectNamedPipe = kernel32.DisconnectNamedPipe
DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
DisconnectNamedPipe.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [
    wintypes.LPCWSTR,    # lpFileName
    wintypes.DWORD,      # dwDesiredAccess
    wintypes.DWORD,      # dwShareMode
    wintypes.LPVOID,     # lpSecurityAttributes
    wintypes.DWORD,      # dwCreationDisposition
    wintypes.DWORD,      # dwFlagsAndAttributes
    wintypes.HANDLE,     # hTemplateFile
]
CreateFileW.restype = wintypes.HANDLE

ReadFile = kernel32.ReadFile
ReadFile.argtypes = [
    wintypes.HANDLE,     # hFile
    wintypes.LPVOID,     # lpBuffer
    wintypes.DWORD,      # nNumberOfBytesToRead
    ctypes.POINTER(wintypes.DWORD),  # lpNumberOfBytesRead
    wintypes.LPVOID,     # lpOverlapped
]
ReadFile.restype = wintypes.BOOL

WriteFile = kernel32.WriteFile
WriteFile.argtypes = [
    wintypes.HANDLE,     # hFile
    wintypes.LPCVOID,    # lpBuffer
    wintypes.DWORD,      # nNumberOfBytesToWrite
    ctypes.POINTER(wintypes.DWORD),  # lpNumberOfBytesWritten
    wintypes.LPVOID,     # lpOverlapped
]
WriteFile.restype = wintypes.BOOL

FlushFileBuffers = kernel32.FlushFileBuffers
FlushFileBuffers.argtypes = [wintypes.HANDLE]
FlushFileBuffers.restype = wintypes.BOOL

GetLastError = kernel32.GetLastError
GetLastError.restype = wintypes.DWORD

WaitNamedPipeW = kernel32.WaitNamedPipeW
WaitNamedPipeW.argtypes = [
    wintypes.LPCWSTR,    # lpNamedPipeName
    wintypes.DWORD,      # nTimeOut
]
WaitNamedPipeW.restype = wintypes.BOOL

SetNamedPipeHandleState = kernel32.SetNamedPipeHandleState
SetNamedPipeHandleState.argtypes = [
    wintypes.HANDLE,     # hNamedPipe
    ctypes.POINTER(wintypes.DWORD),  # lpMode
    ctypes.POINTER(wintypes.DWORD),  # lpMaxCollectionCount
    ctypes.POINTER(wintypes.DWORD),  # lpCollectDataTimeout
]
SetNamedPipeHandleState.restype = wintypes.BOOL


# ── Pipe name ──────────────────────────────────────────────────────────────

def pipe_name(user: str | None = None) -> str:
    """Get the named pipe path for the daemon."""
    if user is None:
        user = os.environ.get("USERNAME", "default")
    return rf"\\.\pipe\cds-daemon-{user}"


# ── Client side (CLI) ──────────────────────────────────────────────────────

class PipeClient:
    """Connect to daemon's named pipe and send/receive messages."""

    def __init__(self, user: str | None = None, timeout: float = 10):
        self._pipe = None
        self.pipe_path = pipe_name(user)
        self._timeout = timeout

    def connect(self, timeout: float = 10) -> bool:
        """Connect to the pipe. Returns True on success."""
        pipe_path = self.pipe_path
        start = time.time()

        while True:
            # Try to open the pipe
            handle = CreateFileW(
                pipe_path,
                GENERIC_READ | GENERIC_WRITE,
                0,          # no sharing
                None,       # default security
                OPEN_EXISTING,
                0,          # no overlapped
                None,
            )

            if handle != INVALID_HANDLE_VALUE:
                # Pipe opened successfully — use BYTE mode (default)
                self._pipe = handle
                return True

            err = GetLastError()
            if err != ERROR_PIPE_BUSY:
                return False

            # Pipe busy — wait and retry
            if time.time() - start > timeout:
                return False

            # Wait for pipe to become available
            WaitNamedPipeW(pipe_path, 2000)
            # loop to retry

    def disconnect(self):
        if self._pipe is not None:
            CloseHandle(self._pipe)
            self._pipe = None

    def send_message(self, data: dict) -> dict:
        """Send a JSON command and receive the response."""
        if self._pipe is None:
            raise RuntimeError("Not connected to daemon. Call connect() first.")

        msg_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")

        # Send: 4-byte length prefix + json data
        header = struct.pack("<I", len(msg_bytes))
        written = wintypes.DWORD(0)

        result = WriteFile(
            self._pipe,
            header + msg_bytes,
            len(header) + len(msg_bytes),
            ctypes.byref(written),
            None,
        )
        if not result:
            err = GetLastError()
            raise RuntimeError(f"WriteFile failed (error {err})")

        FlushFileBuffers(self._pipe)

        # Read: 4-byte length prefix + json data
        raw_len = b""
        while len(raw_len) < 4:
            buf = ctypes.create_string_buffer(4)
            read = wintypes.DWORD(0)
            result = ReadFile(
                self._pipe,
                buf,
                4 - len(raw_len),
                ctypes.byref(read),
                None,
            )
            if not result:
                err = GetLastError()
                if err == ERROR_MORE_DATA:
                    pass  # continue reading
                else:
                    raise RuntimeError(f"ReadFile failed (error {err})")
            raw_len += buf.raw[:read.value]

        msg_len = struct.unpack("<I", raw_len[:4])[0]
        if msg_len == 0:
            return {}

        raw_msg = b""
        while len(raw_msg) < msg_len:
            buf = ctypes.create_string_buffer(msg_len)
            read = wintypes.DWORD(0)
            remaining = msg_len - len(raw_msg)
            result = ReadFile(
                self._pipe,
                buf,
                min(remaining, 4096),
                ctypes.byref(read),
                None,
            )
            if not result:
                err = GetLastError()
                if err == ERROR_MORE_DATA:
                    pass
                else:
                    raise RuntimeError(f"ReadFile failed (error {err})")
            raw_msg += buf.raw[:read.value]

        return json.loads(raw_msg.decode("utf-8"))

    def __enter__(self):
        if not self.connect(timeout=self._timeout):
            raise ConnectionError(
                f"Cannot connect to CODESYS daemon.\n"
                f"Make sure ide_daemon.pyw is running inside CODESYS.\n"
                f"Pipe: {self.pipe_path}"
            )
        return self

    def __exit__(self, *args):
        self.disconnect()


# ── Server side (Daemon inside CODESYS) ────────────────────────────────────

class PipeServer:
    """Named pipe server — used by the daemon inside CODESYS.

    Note: In IronPython you'd use System.IO.Pipes.NamedPipeServerStream.
    This class is for testing / future use from Python 3 side.
    """

    def __init__(self, user: str | None = None):
        self._pipe_handle = None
        self.pipe_path = pipe_name(user)

    def create(self) -> bool:
        """Create the named pipe instance."""
        handle = CreateNamedPipeW(
            self.pipe_path,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            65536,  # out buffer
            65536,  # in buffer
            0,      # default timeout
            None,   # default security
        )
        if handle == INVALID_HANDLE_VALUE:
            return False
        self._pipe_handle = handle
        return True

    def wait_for_connection(self) -> bool:
        """Wait for a client to connect."""
        if self._pipe_handle is None:
            return False
        result = ConnectNamedPipe(self._pipe_handle, None)
        if not result:
            err = GetLastError()
            if err == ERROR_PIPE_CONNECTED:  # already connected
                return True
            return False
        return True

    def read_message(self) -> dict:
        """Read a JSON message from the pipe."""
        if self._pipe_handle is None:
            raise RuntimeError("Pipe not created")

        raw_len = b""
        while len(raw_len) < 4:
            buf = ctypes.create_string_buffer(4)
            read = wintypes.DWORD(0)
            result = ReadFile(
                self._pipe_handle,
                buf,
                4 - len(raw_len),
                ctypes.byref(read),
                None,
            )
            if not result:
                err = GetLastError()
                if err != ERROR_MORE_DATA:
                    raise RuntimeError(f"ReadFile failed (error {err})")
            raw_len += buf.raw[:read.value]

        msg_len = struct.unpack("<I", raw_len[:4])[0]
        if msg_len == 0:
            return {}

        raw_msg = b""
        while len(raw_msg) < msg_len:
            buf = ctypes.create_string_buffer(msg_len)
            read = wintypes.DWORD(0)
            remaining = msg_len - len(raw_msg)
            result = ReadFile(
                self._pipe_handle,
                buf,
                min(remaining, 65536),
                ctypes.byref(read),
                None,
            )
            if not result:
                err = GetLastError()
                if err != ERROR_MORE_DATA:
                    raise RuntimeError(f"ReadFile failed (error {err})")
            raw_msg += buf.raw[:read.value]

        return json.loads(raw_msg.decode("utf-8"))

    def send_message(self, data: dict):
        """Send a JSON response."""
        if self._pipe_handle is None:
            raise RuntimeError("Pipe not created")

        msg_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        header = struct.pack("<I", len(msg_bytes))
        written = wintypes.DWORD(0)

        result = WriteFile(
            self._pipe_handle,
            header + msg_bytes,
            len(header) + len(msg_bytes),
            ctypes.byref(written),
            None,
        )
        if not result:
            err = GetLastError()
            raise RuntimeError(f"WriteFile failed (error {err})")

        FlushFileBuffers(self._pipe_handle)

    def disconnect_and_close(self):
        """Disconnect and close the pipe."""
        if self._pipe_handle is not None:
            DisconnectNamedPipe(self._pipe_handle)
            CloseHandle(self._pipe_handle)
            self._pipe_handle = None

    def __enter__(self):
        self.create()
        return self

    def __exit__(self, *args):
        self.disconnect_and_close()


# ── Convenience ────────────────────────────────────────────────────────────

def send_command(method: str, params: dict | None = None,
                 user: str | None = None, timeout: float = 30) -> dict:
    """Connect to daemon, send a command, return response.

    This is the main entry point for CLI commands.
    """
    with PipeClient(user=user, timeout=5) as client:
        return client.send_message({
            "method": method,
            "params": params or {},
        })


# ── Demo (Python 3 side) ───────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        # Test server mode (for debugging)
        with PipeServer() as server:
            print(f"Pipe server created: {server.pipe_path}")
            print("Waiting for connection...")
            if server.wait_for_connection():
                print("Client connected. Reading message...")
                msg = server.read_message()
                print(f"Received: {json.dumps(msg, indent=2, ensure_ascii=False)}")
                server.send_message({"ok": True, "echo": msg})
                print("Response sent.")
            print("Done.")
    else:
        # Test client mode
        try:
            resp = send_command("ping", {"message": "Hello from CLI!"})
            print(f"Response: {json.dumps(resp, indent=2, ensure_ascii=False)}")
        except ConnectionError as e:
            print(f"Error: {e}")
