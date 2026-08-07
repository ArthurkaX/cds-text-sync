# -*- coding: utf-8 -*-
"""
_cli_io.py - Shared I/O helpers, daemon communication, CODESYS launcher.

Imported by cds_text_sync/_cli_handlers_project.py and cds_text_sync/_cli_handlers_vars.py.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

_SCRIPT_DIR = Path(__file__).resolve().parents[4]
_ENGINE_DIR = (
    _SCRIPT_DIR
    / "products"
    / "cds-text-sync"
    / "src"
    / "cds_text_sync"
    / "engine"
)
if _ENGINE_DIR.exists() and str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
from cds_text_sync.engine.reverse_pipe_client import send_command_reverse

# -- Config ------------------------------------------------------------------

ENGINE_CLI = _ENGINE_DIR / "engine_cli.py"
_REPO_ROOT = _SCRIPT_DIR
_HOST_DAEMON = _REPO_ROOT / "products" / "codesys-host" / "Project_daemon.py"
_LEGACY_DAEMON = _REPO_ROOT / "Project_daemon.py"
DAEMON_SCRIPT = _HOST_DAEMON if _HOST_DAEMON.is_file() else _LEGACY_DAEMON

_CODESYS_CANDIDATES = [
    r"C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files\CODESYS 3.5.20.0\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files\CODESYS 3.5.18.0\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files (x86)\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files (x86)\CODESYS 3.5.20.0\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files (x86)\CODESYS 3.5.18.0\CODESYS\Common\CODESYS.exe",
]


# -- Print helpers ------------------------------------------------------------


def _print_info(msg):
    print(f"[INFO] {msg}", file=sys.stderr)


def _print_ok(msg):
    print(f"[OK] {msg}", file=sys.stderr)


def _print_error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)


def _print_warn(msg):
    print(f"[WARN] {msg}", file=sys.stderr)


# Text mode is for a person reading a terminal, so it has to stay readable
# whatever the daemon returns. The limits below are on rendered size, never on
# item count: `cts compare` returns five added objects carrying a ~300 KB XML
# blob each, and a count-based guard let all five through — 1.5 MB across 16
# lines. The same guard hid a whole project tree behind "children: [8 items]".
MAX_TEXT_VALUE_CHARS = 500
MAX_TEXT_LIST_ITEMS = 20
# Nesting costs two levels per tree level (a dict holds a list holds a dict), so
# this allows about four levels of project tree. The real bound is the line
# budget below; this only stops pathologically deep payloads early.
MAX_TEXT_DEPTH = 8
MAX_TEXT_LINES = 200


class _TextRenderer:
    """Render a payload as indented lines, remembering whether it elided any.

    The flag is the point: four different limits can cut something out, and a
    reader who cannot tell the difference between "that is all of it" and "that
    is the first 500 characters of it" is worse off than before.
    """

    def __init__(self):
        self.elided = False

    def scalar(self, value):
        """One scalar on exactly one line, capped.

        Newlines are folded away: an embedded XML blob would otherwise wreck
        the indentation and slip past the line budget, which counts entries.
        """
        text = " ".join(str(value).split())
        if len(text) <= MAX_TEXT_VALUE_CHARS:
            return text
        self.elided = True
        omitted = len(text) - MAX_TEXT_VALUE_CHARS
        return f"{text[:MAX_TEXT_VALUE_CHARS]}… (+{omitted} more chars)"

    def entry(self, label, value, indent, depth):
        """Lines for one labelled value — a dict's "key:" or a list's "-"."""
        pad = "  " * indent
        if not isinstance(value, (dict, list, tuple)):
            rendered = self.scalar(value)
            return [f"{pad}{label} {rendered}" if rendered else f"{pad}{label}"]
        if not value:
            return [f"{pad}{label} {_empty_marker(value)}"]
        if depth >= MAX_TEXT_DEPTH:
            self.elided = True
            kind = "keys" if isinstance(value, dict) else "items"
            return [f"{pad}{label} [{len(value)} {kind}]"]
        return [f"{pad}{label}"] + self.block(value, indent + 1, depth + 1)

    def block(self, value, indent, depth):
        """Lines for the contents of a dict or a sequence."""
        lines = []
        if isinstance(value, dict):
            for key, item in value.items():
                lines.extend(self.entry(f"{key}:", item, indent, depth))
            return lines

        for item in value[:MAX_TEXT_LIST_ITEMS]:
            lines.extend(self.entry("-", item, indent, depth))
        hidden = len(value) - MAX_TEXT_LIST_ITEMS
        if hidden > 0:
            self.elided = True
            lines.append(f"{'  ' * indent}… and {hidden} more")
        return lines


def _empty_marker(value):
    return "{}" if isinstance(value, dict) else "[]"


def _format_output(data, fmt="json", title=None):
    """Format output as JSON (machine) or text (human)."""
    if fmt != "text":
        return json.dumps(data, indent=2, ensure_ascii=False)

    if data is None:
        return "None"

    renderer = _TextRenderer()
    lines = [f"── {title} ──"] if title else []
    if isinstance(data, (dict, list, tuple)):
        lines.extend(
            renderer.block(data, 0, 0) if data else [_empty_marker(data)]
        )
    else:
        lines.append(renderer.scalar(data))

    if len(lines) > MAX_TEXT_LINES:
        renderer.elided = True
        lines = lines[:MAX_TEXT_LINES]
    if renderer.elided:
        lines.append("… shortened for reading; use --output json for all of it")
    return "\n".join(lines)


# -- CODESYS launcher --------------------------------------------------------


def _find_codesys() -> str | None:
    """Find CODESYS executable on this system."""
    for candidate in _CODESYS_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    for pattern in [
        r"C:\Program Files\CODESYS*\CODESYS\Common\CODESYS.exe",
        r"C:\Program Files (x86)\CODESYS*\CODESYS\Common\CODESYS.exe",
    ]:
        matches = glob.glob(pattern)
        for m in matches:
            if os.path.exists(m):
                return m
    return None


def _launch_codesys(
    project_path: str | None = None,
    codesys_path: str | None = None,
    script_path: str | None = None,
    wait: bool = False,
) -> bool:
    """Launch CODESYS IDE with optional project and startup script.

    Args:
        project_path: Path to .project or .projectxml file
        codesys_path: Path to CODESYS.exe (auto-detect if None)
        script_path: Path to Python script to run on startup
        wait: If True, wait for CODESYS to exit

    Returns:
        True if launch succeeded
    """
    exe = codesys_path or _find_codesys()
    if not exe:
        _print_error("CODESYS executable not found. Specify --codesys-path")
        return False
    if not os.path.exists(exe):
        _print_error("CODESYS not found: {0}".format(exe))
        return False

    args = [exe]
    if project_path:
        abs_project = os.path.abspath(project_path)
        if not os.path.exists(abs_project):
            _print_error("Project not found: {0}".format(abs_project))
            return False
        args.append("--project={0}".format(abs_project))

    if script_path:
        abs_script = os.path.abspath(script_path)
        if not os.path.exists(abs_script):
            _print_error("Script not found: {0}".format(abs_script))
            return False
        args.append("--runscript={0}".format(abs_script))

    _print_info("Launching CODESYS: {0}".format(" ".join(args)))
    try:
        if wait:
            subprocess.run(args, check=False)
        else:
            subprocess.Popen(args)
        _print_ok("CODESYS launched.")
        return True
    except Exception as e:
        _print_error("Failed to launch CODESYS: {0}".format(e))
        return False


def _load_project_config():
    """Load cds-text-sync.json and resolved profile from cwd.

    Returns (config, profile) or ({}, None).
    """
    config = {}
    profile = None
    config_path = os.path.join(os.getcwd(), "cds-text-sync.json")
    if not os.path.exists(config_path):
        return config, profile

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    profile_name = config.get("profile")
    if profile_name:
        from _project_profiles import PROFILES_DIR, load_profile

        profile = load_profile(profile_name, PROFILES_DIR)

    return config, profile


# -- Reverse-pipe output helpers ----------------------------------------------


def _print_rp_error(resp, command):
    """Print reverse-pipe error details."""
    err = resp.get("error")
    if err is not None and err != "":
        _print_error(err)
    else:
        messages = resp.get("data", {}).get("messages")
        if isinstance(messages, list) and messages:
            errors = [m for m in messages if m.get("severity") in ("Error", "error")]
            if errors:
                for m in errors:
                    code = m.get("code", "")
                    text = m.get("text", "")
                    obj = m.get("object", "")
                    _print_error("[{0}] {1} (in {2})".format(code, text, obj))
            else:
                _print_error(
                    "{0} failed with {1} warnings".format(command, len(messages))
                )
        else:
            _print_error("unknown error")
    diag = resp.get("diagnostics")
    if diag:
        _print_info("Diagnostics: {0}".format(json.dumps(diag, ensure_ascii=False)))


def _parse_key_value_args(args: list[str]) -> dict:
    params = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                params[key] = args[i + 1]
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1
    return params


# -- High-level daemon commands -----------------------------------------------


def cmd_rp_command(args: list[str], timeout: float = 15, output_fmt: str = "json"):
    """Send a command via reverse-pipe daemon.

    Args:
        args: Command name followed by --key value pairs
        timeout: Timeout in seconds
        output_fmt: Output format ("json" or "text")
    """
    if not args:
        _print_error(
            "Specify a command: ping, status, project_info, application_state, etc."
        )
        sys.exit(1)

    command = args[0]
    params = _parse_key_value_args(args[1:])
    # Apply profile defaults for app/app_dir
    try:
        _config, profile = _load_project_config()
        if profile:
            if "default_app_name" in profile and "app" not in params:
                params["app"] = profile["default_app_name"]
            if "plc_app_path" in profile and "app_dir" not in params:
                params["app_dir"] = profile["plc_app_path"]
    except Exception as e:
        _print_info("Warning: could not load profile: {0}".format(e))
    if "timeout" in params:
        timeout = float(params.pop("timeout"))

    try:
        resp = send_command_reverse(command, params, timeout=timeout)
    except RuntimeError as e:
        _print_error("Reverse pipe error: {0}".format(e))
        sys.exit(1)

    if resp.get("ok"):
        data = resp.get("data", {})
        print(_format_output(data, fmt=output_fmt, title=command))
    else:
        _print_rp_error(resp, command)
        sys.exit(1)


def cmd_daemon(
    method: str,
    params: dict | None = None,
    timeout: float = 15,
    output_fmt: str = "json",
):
    """Send one structured command to the CODESYS daemon."""
    params = params or {}
    try:
        _config, profile = _load_project_config()
        if profile:
            if "default_app_name" in profile and "app" not in params:
                params["app"] = profile["default_app_name"]
            if "plc_app_path" in profile and "app_dir" not in params:
                params["app_dir"] = profile["plc_app_path"]
    except Exception as e:
        _print_info("Warning: could not load profile: {0}".format(e))

    try:
        resp = send_command_reverse(method, params, timeout=timeout)
    except RuntimeError as e:
        _print_error("Reverse pipe error: {0}".format(e))
        sys.exit(1)

    if resp.get("ok"):
        print(_format_output(resp.get("data", {}), fmt=output_fmt, title=method))
    else:
        _print_rp_error(resp, method)
        sys.exit(1)


# -- Legacy project command low-level -----------------------------------------


def _project_command(method, params=None, timeout=30, use_reverse=True):
    """Send a project command to the reverse-pipe daemon and print result.

    Exits non-zero on any failure so callers (and CI) get a truthful exit code,
    matching the daemon-command contract in _daemon_command().
    """
    try:
        resp = send_command_reverse(method, params or {}, timeout=timeout)
    except ConnectionError as e:
        _print_error("Cannot connect to daemon: {0}".format(e))
        sys.exit(1)
    except RuntimeError as e:
        _print_error("Command error: {0}".format(e))
        sys.exit(1)

    if resp.get("ok"):
        data = resp.get("data", {})
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        _print_error(resp.get("error", "unknown error"))
        sys.exit(1)


# -- Batch helper -------------------------------------------------------------

_BATCH_SIZE = 500


def _batch(method, key, items, timeout):
    """Send items to a daemon batch method in chunks. Returns {name: result}."""
    out = {}
    for i in range(0, len(items), _BATCH_SIZE):
        part = items[i : i + _BATCH_SIZE]
        resp = send_command_reverse(method, {key: part}, timeout=timeout)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", method + " failed"))
        for r in resp.get("data", {}).get("results", []):
            out[r["name"]] = r
    return out


# -- Direct engine_cli invocation --------------------------------------------


def cmd_direct(args: list[str]) -> NoReturn:
    """Run engine_cli directly (blocking, no daemon)."""
    if not ENGINE_CLI.exists():
        _print_error("engine_cli.py not found: {0}".format(ENGINE_CLI))
        sys.exit(1)
    # Strip any --timeout that was accepted at the top-level parser for
    # consistency; the offline engine has no daemon to time out.
    filtered = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--timeout":
            skip_next = True
            continue
        if arg.startswith("--timeout="):
            continue
        filtered.append(arg)
    cmd = [sys.executable, str(ENGINE_CLI)] + filtered
    _print_info("Running: {0}".format(" ".join(cmd)))
    proc = subprocess.Popen(cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\nInterrupted.")
        sys.exit(1)
    sys.exit(proc.returncode)
