# -*- coding: utf-8 -*-
"""Reusable external-UI process launcher for the CODESYS menu entrypoints.

This module runs under the CODESYS IronPython ScriptEngine, but it deliberately
contains no UI and imports no analyzer or FSM modules.  It holds the reusable
half of the old analyzer launcher: resolving the active project's configured
sync folder, resolving the CPython interpreter, reporting messages, and the
bounded readiness handshake that starts the separate CPython process hosting
the WebView2 window.
"""
from __future__ import print_function

import os
import subprocess
import threading
import time

READY_LINE = "CTS-UI-READY"
READY_TIMEOUT_SECONDS = 8.0
_INSTALL_HINT = 'Install the optional UI dependency with: pip install -e ".[ui]"'


def project_sync_folder(project):
    """Read and resolve the project's cds-sync-folder without creating paths."""
    info = None
    if hasattr(project, "get_project_info"):
        info = project.get_project_info()
    elif hasattr(project, "project_info"):
        info = project.project_info
    if info is None:
        return None, "Project Information is not available."

    props = info.values if hasattr(info, "values") else info
    try:
        value = props["cds-sync-folder"] if "cds-sync-folder" in props else ""
    except Exception:
        try:
            value = props.get("cds-sync-folder", "")
        except Exception:
            value = ""
    sync_folder = str(value or "").strip()
    if not sync_folder:
        return None, (
            "Sync folder is not configured. Run Project_directory.py first."
        )

    relative = not os.path.isabs(sync_folder)
    if relative:
        project_path = str(getattr(project, "path", "") or "").strip()
        if not project_path:
            return None, (
                "Cannot resolve the relative sync folder because the project "
                "has no saved file path. Save it, or configure an absolute "
                "folder with Project_directory.py."
            )
        sync_folder = os.path.normpath(
            os.path.join(
                os.path.dirname(project_path),
                sync_folder.replace("/", os.sep).replace("\\", os.sep),
            )
        )
    return os.path.abspath(sync_folder), None


def body_root():
    """The repository/package body containing the CPython package."""
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(
            os.path.join(
                current,
                "products",
                "cds-text-sync",
                "src",
                "cds_text_sync",
            )
        ):
            return current
        if os.path.isdir(os.path.join(current, "cds_text_sync")):
            return current
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def python_command():
    """Allow an explicit CPython path; otherwise resolve python.exe via PATH."""
    return os.environ.get("CDS_PYTHON", "").strip() or "python"


def notify(runtime, message, is_error=False):
    try:
        if is_error:
            runtime.ui.error(message)
        else:
            runtime.ui.info(message)
    except Exception:
        print(message)


def _drain_stdout(stream):
    """Read *stream* to EOF and discard, so a full pipe never blocks the child."""
    try:
        while stream.readline():
            pass
    except Exception:
        pass


def _start_drain(stream):
    """Start a daemon thread that drains *stream* to EOF and discards it.

    Chosen over detaching the pipe: closing the launcher's read end would turn
    the child's next write into a BrokenPipeError at an arbitrary later point,
    and IronPython 2.7 offers no portable non-blocking pipe read.  A daemon
    thread keeps reading until the child closes stdout, so the pipe buffer can
    never fill and stall the long-lived window; it dies with this (launcher)
    process, which is exactly the window we need it to cover.
    """
    thread = threading.Thread(target=_drain_stdout, args=(stream,))
    thread.daemon = True
    thread.start()
    return thread


def _wait_for_readiness(process, timeout_seconds):
    """Wait for the child's readiness line, its exit, or the deadline.

    Returns a (outcome, detail) pair:
      ("ready", None)      the child printed the readiness line
      ("exited", output)   the child exited first; *output* is what it wrote
      ("timeout", output)  neither happened within *timeout_seconds*
    """
    result = {}
    stream = process.stdout
    output = []
    lock = threading.Lock()

    def _reader():
        try:
            while True:
                line = stream.readline()
                if not line:
                    with lock:
                        result["eof"] = True
                    return
                with lock:
                    output.append(line)
                if READY_LINE in line:
                    with lock:
                        result["ready"] = True
                    return
        except Exception:
            with lock:
                result["eof"] = True

    reader = threading.Thread(target=_reader)
    reader.daemon = True
    reader.start()

    deadline = time.time() + timeout_seconds
    while True:
        with lock:
            ready = result.get("ready")
        if ready:
            return "ready", None
        if process.poll() is not None:
            with lock:
                captured = "".join(output)
            return "exited", captured
        if time.time() >= deadline:
            with lock:
                captured = "".join(output)
            return "timeout", captured
        time.sleep(0.05)


def start_ui(runtime, project, command_args, label, timeout_seconds=None):
    """Resolve the sync folder and start the CPython UI process.

    The child prints ``READY_LINE`` and flushes just before entering its event
    loop; this function waits up to *timeout_seconds* for that line, the
    child's exit, or the deadline, and reports whichever happens first.
    """
    if timeout_seconds is None:
        timeout_seconds = READY_TIMEOUT_SECONDS

    sync_folder, error = project_sync_folder(project)
    if error:
        notify(runtime, error, is_error=True)
        return {"status": "error", "error": error}

    command = [python_command(), "-m", "cds_cli.main"]
    command.extend(command_args)
    command.extend(["--workspace", sync_folder])

    kwargs = {
        "cwd": body_root(),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    # Keep a second hand-off channel for installations where the host or
    # launcher normalizes command-line arguments before starting CPython.
    # The UI uses this only when --workspace is absent.
    environment = os.environ.copy()
    environment["CTS_INITIAL_WORKSPACE"] = sync_folder
    kwargs["env"] = environment
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        message = (
            "Cannot start CPython for " + label + ": " + str(exc)
            + "\nSet CDS_PYTHON to the full path of python.exe if needed."
        )
        notify(runtime, message, is_error=True)
        return {"status": "error", "error": message}

    outcome, detail = _wait_for_readiness(process, timeout_seconds)
    if outcome == "ready":
        _start_drain(process.stdout)
        return {
            "status": "started",
            "pid": process.pid,
            "sync_folder": sync_folder,
        }

    if outcome == "exited":
        message = (
            label + " exited before the readiness line (code {0}).\n"
        ).format(process.returncode)
        if detail:
            message = message + detail.rstrip() + "\n"
        message = message + _INSTALL_HINT
        notify(runtime, message, is_error=True)
        return {"status": "error", "error": message}

    message = (
        label + " did not report readiness within {0} seconds.\n"
        "The UI process is still starting; check the Python environment."
    ).format(int(timeout_seconds))
    notify(runtime, message, is_error=True)
    return {"status": "error", "error": message}
