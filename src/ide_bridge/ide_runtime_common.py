# -*- coding: utf-8 -*-
"""
ide_runtime_common.py - Common functions for the IDE bridge.
Provides paths, logging, process execution and error handling.
Must be compatible with IronPython 2.7.
"""
import os
import sys
import subprocess
import warnings
import time
import codecs

# Suppress IronPython DeprecationWarnings that occur when importing/using subprocess
# (e.g. "sys.exc_clear() not supported in 3.x")
warnings.filterwarnings("ignore", category=DeprecationWarning)

_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
# Try new path first (cds_text_sync/engine/), fall back to old (src/external_engine/)
_ENGINE_DIR = os.path.normpath(os.path.join(_BRIDGE_DIR, "..", "..", "cds_text_sync", "engine"))
if not os.path.isdir(_ENGINE_DIR):
    _ENGINE_DIR = os.path.normpath(os.path.join(_BRIDGE_DIR, "..", "external_engine"))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from _project_layout import resolve_layout
from _project_settings import load_project_settings


def dump_path(project_root):
    return resolve_layout(project_root).dump_root


def layout(project_root, view_root=None, layout_mode=None):
    if view_root is None and layout_mode is None:
        settings = load_project_settings(project_root)
        view_root = settings.get("view_root")
        layout_mode = settings.get("layout")
    return resolve_layout(project_root, view_root=view_root, layout_mode=layout_mode)


def object_name(obj):
    try:
        return str(obj.get_name())
    except Exception:
        return ""


def get_workspace_dir(script_file=None):
    # Find the root by looking for src/ide_bridge or cds_text_sync/engine
    path = os.path.abspath(script_file or __file__)
    current = os.path.dirname(path)
    while True:
        if (os.path.isdir(os.path.join(current, "src", "ide_bridge"))
                or os.path.isdir(os.path.join(current, "cds_text_sync", "engine"))):
            return current
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return os.path.dirname(os.path.abspath(__file__))


def _timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _safe_project_settings(project_root):
    if not project_root:
        return {}
    try:
        return load_project_settings(project_root) or {}
    except Exception:
        return {}


def project_logging_config(project_root, dump_root=None):
    settings = _safe_project_settings(project_root)
    verbose_logging = bool(settings.get("verbose_logging", False))
    if dump_root is None and project_root:
        try:
            dump_root = dump_path(project_root)
        except Exception:
            dump_root = None
    log_path = os.path.join(dump_root, "sync_debug.log") if verbose_logging and dump_root else None
    return verbose_logging, log_path

def _write_detailed_log(log_path, header_lines, stdout_text, stderr_text):
    if not log_path:
        return
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    with codecs.open(log_path, "a", "utf-8") as handle:
        for line in header_lines or []:
            handle.write(line + "\n")
        if stdout_text:
            handle.write(stdout_text)
            if not stdout_text.endswith("\n"):
                handle.write("\n")
        if stderr_text:
            if stdout_text:
                handle.write("\n")
            handle.write("[stderr]\n")
            handle.write(stderr_text)
            if not stderr_text.endswith("\n"):
                handle.write("\n")
        handle.write("\n")


def make_detailed_logger(log_path):
    if not log_path:
        return None

    def _log(message):
        _write_detailed_log(log_path, ["[{0}] {1}".format(_timestamp(), message)], "", "")

    return _log

def _external_notice_lines(stdout_text, stderr_text):
    lines = []
    seen = set()
    for text in (stdout_text or "", stderr_text or ""):
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if "Warning:" not in line and "Error:" not in line:
                continue
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
    return lines

def run_external_engine(command_args, script_file=None, project_root=None, dump_root=None, warning_fn=None):
    root_dir = get_workspace_dir(script_file)
    # Try new path first (cds_text_sync/engine/), fall back to old path
    engine_cli = os.path.join(root_dir, "cds_text_sync", "engine", "engine_cli.py")
    if not os.path.exists(engine_cli):
        engine_cli = os.path.join(root_dir, "src", "external_engine", "engine_cli.py")
    if not os.path.exists(engine_cli):
        log_error("External engine CLI not found (tried cds_text_sync/ and src/ paths): " + str(engine_cli))
        return False
        
    cmd = ["python", engine_cli] + command_args
    _, log_path = project_logging_config(project_root, dump_root)
    command_name = command_args[0] if command_args else "unknown"
    try:
        if log_path:
            _write_detailed_log(
                log_path,
                [
                    "[{0}] command={1}".format(_timestamp(), command_name),
                    "[{0}] args={1}".format(_timestamp(), " ".join(cmd)),
                ],
                "",
                "",
            )

        # Prevent the black console window from flashing on Windows
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE
        }
        if os.name == 'nt':
            kwargs["creationflags"] = 0x08000000 # CREATE_NO_WINDOW

        p = subprocess.Popen(cmd, cwd=root_dir, **kwargs)
        out, err = p.communicate()

        out_text = out.decode('utf-8', 'replace') if out else ""
        err_text = err.decode('utf-8', 'replace') if err else ""

        if log_path:
            _write_detailed_log(
                log_path,
                ["[{0}] returncode={1}".format(_timestamp(), p.returncode)],
                out_text,
                err_text,
            )

        warning_lines = _external_notice_lines(out_text, err_text)
        if warning_lines:
            warning_text = "\n".join(warning_lines)
            if warning_fn:
                try:
                    warning_fn(warning_text)
                except Exception:
                    log_error(warning_text)
            else:
                log_error(warning_text)

        if p.returncode != 0:
            log_error("External engine failed with return code " + str(p.returncode))
            return False
        return True
    except Exception as e:
        log_error("Failed to execute external engine: " + str(e))
        return False

def log_info(msg):
    print("[IDE INFO] {0} {1}".format(_timestamp(), str(msg)))

def log_error(msg):
    print("[IDE ERROR] {0} {1}".format(_timestamp(), str(msg)))
