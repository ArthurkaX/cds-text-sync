# -*- coding: utf-8 -*-
"""
daemon.py — Background HTTP Daemon for cds-text-sync.

Listens on localhost:8377, accepts JSON-RPC-like commands.
Allows running engine_cli.py asynchronously, checking status,
and stopping itself.

Usage:
    python daemon.py start          # run in background
    python daemon.py stop           # stop via HTTP
    python daemon.py status         # check status
    python daemon.py run            # run in current terminal (foreground)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8377
PID_FILE = os.path.join(tempfile.gettempdir(), "cds-daemon.pid")
LOCK_FILE = os.path.join(tempfile.gettempdir(), "cds-daemon.lock")

ENGINE_CLI = None  # resolved relative to daemon.py


def _find_engine_cli() -> str:
    """Locate engine_cli.py relative to this file."""
    here = Path(__file__).resolve().parent  # e.g. .../cli/external_engine/
    candidates = [
        here / "engine_cli.py",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(here / "engine_cli.py")


ENGINE_CLI = _find_engine_cli()


# ── Utilities ─────────────────────────────────────────────────────────────

def _log(msg: str):
    print(f"[cds-daemon] {msg}")


def _json_error(code: int, message: str) -> str:
    return json.dumps({"ok": False, "code": code, "error": message})


def _json_ok(data: Any = None) -> str:
    return json.dumps({"ok": True, "data": data})


def _read_pid() -> int | None:
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_pid(pid: int):
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# ── Task Manager ──────────────────────────────────────────────────────────

class TaskManager:
    """
    Stores running tasks (engine_cli subprocesses).
    Thread-safe.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}  # task_id -> info
        self._next_id = 0

    def start_task(self, args: list[str], cwd: str | None = None) -> str:
        task_id = f"tsk-{self._next_id:04d}"
        self._next_id += 1

        proc = subprocess.Popen(
            [sys.executable, ENGINE_CLI] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        info = {
            "id": task_id,
            "pid": proc.pid,
            "command": args[0] if args else "",
            "started_at": time.time(),
            "proc": proc,
            "done": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
        }

        with self._lock:
            self._tasks[task_id] = info

        # Collector thread for result
        def _collect(tid: str, process: subprocess.Popen):
            out, err = process.communicate()
            with self._lock:
                t = self._tasks.get(tid)
                if t:
                    t["done"] = True
                    t["returncode"] = process.returncode
                    t["stdout"] = out.decode("utf-8", "replace") if out else ""
                    t["stderr"] = err.decode("utf-8", "replace") if err else ""

        threading.Thread(target=_collect, args=(task_id, proc), daemon=True).start()
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return None
            # return copy without proc
            return {k: v for k, v in info.items() if k != "proc"}

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in t.items() if k != "proc"} for t in self._tasks.values()]

    def cleanup_old(self, max_age: float = 3600):
        now = time.time()
        with self._lock:
            to_del = [tid for tid, t in self._tasks.items()
                      if t["done"] and (now - t["started_at"]) > max_age]
            for tid in to_del:
                del self._tasks[tid]


# ── HTTP Handler ──────────────────────────────────────────────────────────

class DaemonHandler(BaseHTTPRequestHandler):
    """Handles JSON-RPC-like POST requests."""

    # Shared across all handler instances
    task_manager = TaskManager()
    daemon_should_stop = False

    def log_message(self, fmt, *args):
        _log(f"[HTTP] {args[0]} {args[1]} {args[2]}" if args else fmt % args)

    def _send_json(self, status: int, body: str):
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, _json_ok({"status": "running", "pid": os.getpid()}))
        elif self.path == "/tasks":
            self._send_json(200, _json_ok(self.task_manager.list_tasks()))
        else:
            self._send_json(404, _json_error(404, f"Unknown path: {self.path}"))

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length else b""

        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, _json_error(400, "Invalid JSON"))
            return

        method = body.get("method", "")
        params = body.get("params", {})

        if method == "ping":
            self._send_json(200, _json_ok({"pong": True, "pid": os.getpid()}))

        elif method == "exec":
            args = params.get("args", [])
            cwd = params.get("cwd")
            if not args:
                self._send_json(400, _json_error(400, "Missing 'args' in params"))
                return
            task_id = self.task_manager.start_task(args, cwd=cwd)
            self._send_json(200, _json_ok({
                "task_id": task_id,
                "message": f"Task {task_id} started",
            }))

        elif method == "task_status":
            task_id = params.get("task_id", "")
            info = self.task_manager.get_task(task_id)
            if info is None:
                self._send_json(404, _json_error(404, f"Task not found: {task_id}"))
                return
            self._send_json(200, _json_ok(info))

        elif method == "list_tasks":
            self._send_json(200, _json_ok(self.task_manager.list_tasks()))

        elif method == "stop":
            self._send_json(200, _json_ok({"message": "Daemon stopping..."}))
            # Signal stop from a separate thread so the response is sent first
            threading.Thread(target=self._do_stop, daemon=True).start()

        elif method == "shutdown":
            # Immediate shutdown
            self._send_json(200, _json_ok({"message": "Daemon shutting down..."}))
            threading.Thread(target=self._do_stop, daemon=True).start()

        else:
            self._send_json(400, _json_error(400, f"Unknown method: {method}"))

    def _do_stop(self):
        time.sleep(0.1)
        self.daemon_should_stop = True
        if hasattr(self.server, "shutdown"):
            self.server.shutdown()


# ── Daemon (foreground) ──────────────────────────────────────────────────

def run_daemon_foreground():
    """Run daemon in the current terminal (foreground)."""
    server = HTTPServer((HOST, PORT), DaemonHandler)
    _log(f"Daemon started on http://{HOST}:{PORT} (pid={os.getpid()})")
    _log(f"Engine CLI: {ENGINE_CLI}")

    # Periodic cleanup of old tasks
    def _cleanup_loop():
        while not DaemonHandler.daemon_should_stop:
            time.sleep(300)  # every 5 minutes
            DaemonHandler.task_manager.cleanup_old()
    threading.Thread(target=_cleanup_loop, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Shutting down (Ctrl+C)...")
    finally:
        server.server_close()
        _remove_pid()
        _log("Daemon stopped.")


def run_daemon_background():
    """Run daemon in background (self-subprocess)."""
    if _read_pid() is not None:
        pid = _read_pid()
        if pid and _is_pid_alive(pid):
            print(f"Daemon already running (pid={pid}).")
            return
        _remove_pid()

    script = __file__
    cmd = [sys.executable, script, "run"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        if sys.platform == "win32" else 0,
        close_fds=True,
    )
    _write_pid(proc.pid)
    print(f"Daemon started in background (pid={proc.pid}).")


def stop_daemon():
    """Stop daemon via HTTP."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://{HOST}:{PORT}/",
            data=json.dumps({"method": "stop"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        print(f"Daemon response: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"Failed to stop daemon via HTTP: {e}")
        # fallback — kill by PID
        pid = _read_pid()
        if pid:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False)
                else:
                    os.kill(pid, signal.SIGTERM)
                _remove_pid()
                print(f"Daemon (pid={pid}) killed.")
            except Exception as kill_err:
                print(f"Failed to kill daemon: {kill_err}")
        else:
            print("No PID file found.")


def daemon_status():
    """Check daemon status."""
    pid = _read_pid()
    if pid is None:
        print("Daemon is NOT running (no PID file).")
        return False

    if not _is_pid_alive(pid):
        print(f"Daemon is NOT running (PID {pid} is dead). Removing stale PID file.")
        _remove_pid()
        return False

    # Verify via HTTP
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=3)
        data = json.loads(resp.read())
        print(f"Daemon is RUNNING (pid={pid}). Health: {json.dumps(data, indent=2)}")
        return True
    except Exception:
        print(f"Daemon PID={pid} exists but HTTP not responding. Stale?")
        return True


# ── CLI — direct engine_cli execution (without daemon) ────────────────────

def direct_exec(args: list[str]):
    """Run engine_cli directly (without daemon)."""
    cmd = [sys.executable, ENGINE_CLI] + args
    _log(f"Executing: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    proc.wait()
    return proc.returncode


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="cds-text-sync Daemon — background HTTP server for sync commands",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="help",
        choices=["start", "stop", "status", "run", "help"],
        help="start — run in background | stop — stop daemon | status — check status | run — run in foreground",
    )
    args = parser.parse_args()

    if args.command == "run":
        run_daemon_foreground()
    elif args.command == "start":
        run_daemon_background()
    elif args.command == "stop":
        stop_daemon()
    elif args.command == "status":
        daemon_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
