# -*- coding: utf-8 -*-
"""Start the CPython/pywebview analyzer UI from a CODESYS menu entry.

This module runs under the CODESYS IronPython ScriptEngine, but it deliberately
contains no UI and imports no analyzer modules.  Its only responsibility is to
read the active project's configured sync folder and start the separate
CPython process that hosts the WebView2 window.
"""
from __future__ import print_function

import os
import subprocess
import time

from codesys_runtime import resolve_runtime
from codesys_utils import resolve_projects


def _project_sync_folder(project):
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

    relative = (
        sync_folder == "."
        or sync_folder.startswith("./")
        or sync_folder.startswith(".\\")
    )
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
    return sync_folder, None


def _body_root():
    """The repository/package body, two levels above src/ide_bridge."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _python_command():
    """Allow an explicit CPython path; otherwise resolve python.exe via PATH."""
    return os.environ.get("CDS_PYTHON", "").strip() or "python"


def _notify(runtime, message, is_error=False):
    try:
        if is_error:
            runtime.ui.error(message)
        else:
            runtime.ui.info(message)
    except Exception:
        print(message)


def main(params=None, caller_globals=None):
    runtime = resolve_runtime(
        caller_globals=caller_globals, params=params, headless=False
    )
    projects = resolve_projects(runtime.projects, runtime.caller_globals)
    project = projects.primary if projects is not None else None
    if project is None:
        message = "No CODESYS project is open."
        _notify(runtime, message, is_error=True)
        return {"status": "error", "error": message}

    sync_folder, error = _project_sync_folder(project)
    if error:
        _notify(runtime, error, is_error=True)
        return {"status": "error", "error": error}

    command = [
        _python_command(),
        "-m",
        "cds_text_sync.main",
        "ui",
        "--workspace",
        sync_folder,
    ]
    kwargs = {"cwd": _body_root()}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        message = (
            "Cannot start CPython for the analyzer UI: " + str(exc)
            + "\nSet CDS_PYTHON to the full path of python.exe if needed."
        )
        _notify(runtime, message, is_error=True)
        return {"status": "error", "error": message}

    # Missing pywebview or an invalid Python is reported promptly rather than
    # leaving the user with a menu click that appears to do nothing.
    time.sleep(0.4)
    if process.poll() is not None:
        message = (
            "The analyzer UI process exited immediately (code {0}).\n"
            'Install the optional UI dependency with: pip install -e ".[ui]"'
        ).format(process.returncode)
        _notify(runtime, message, is_error=True)
        return {"status": "error", "error": message}

    message = "Static analysis UI opened for:\n" + sync_folder
    _notify(runtime, message)
    return {"status": "started", "pid": process.pid, "sync_folder": sync_folder}
