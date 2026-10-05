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
from cds_text_sync.engine.reverse_pipe_client import (
    get_last_context,
    get_last_instance,
    send_command_reverse,
)
from cts_shared import wire

# -- Config ------------------------------------------------------------------

ENGINE_CLI = _ENGINE_DIR / "engine_cli.py"
_ENGINE_MODULE = "cds_text_sync.engine.engine_cli"
_PRODUCT_SRC = _SCRIPT_DIR / "products" / "cds-text-sync" / "src"
_SHARED_SRC = _SCRIPT_DIR / "shared" / "src"


def _engine_subprocess_env():
    """Environment for the offline engine child.

    PYTHONPATH pins the source checkout's packages, so the child imports the
    same tree the CLI is running from. (The working directory is kept off
    sys.path by ``-P`` in cmd_direct, not by this.)
    """
    parts = [str(path) for path in (_PRODUCT_SRC, _SHARED_SRC) if path.is_dir()]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    env = dict(os.environ)
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    return env
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


#: One extra line after a reverse-pipe failure. It says only what is true of
#: every such failure -- the daemon/IDE did not answer -- without guessing why.
_DAEMON_UNREACHABLE = "The IDE/daemon is not answering (is CODESYS running with the daemon started?)."


def _print_daemon_unreachable():
    _print_info(_DAEMON_UNREACHABLE)


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
    last_inst = get_last_instance()
    last_ctx = get_last_context()

    if fmt != "text":
        merged = _hoist_envelope(data, last_inst, last_ctx)
        return json.dumps(merged, indent=2, ensure_ascii=False)

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

    lines.extend(_footer_lines(last_inst, last_ctx))
    return "\n".join(lines)


def _hoist_envelope(data, last_inst, last_ctx):
    """Add ``instance``/``context`` to a dict payload for the printed JSON.

    Only when the payload does not already carry the key, so a caller that
    built its own block is not overwritten.
    """
    if not isinstance(data, dict):
        return data
    extra = {}
    if "instance" not in data and last_inst is not None:
        extra["instance"] = last_inst
    if "context" not in data and last_ctx is not None:
        extra["context"] = last_ctx
    if not extra:
        return data
    merged = dict(data)
    merged.update(extra)
    return merged


def _footer_lines(last_inst, last_ctx):
    """The trailing line(s): the ``[ctx]`` line, or the legacy instance line."""
    context_line = _context_line(last_ctx)
    if context_line:
        return [context_line]
    if last_inst is None:
        return []
    inst_id = last_inst.get("id", "")
    prj = last_inst.get("project")
    prj_name = prj.get("name") if (prj and isinstance(prj, dict)) else None
    return [f"{inst_id} · {prj_name}" if prj_name else f"{inst_id} · no project"]


def _context_line(context):
    """The one-line ``[ctx] ...`` footer, or "" when there is no context.

    Built only from the block the daemon sent; a missing field degrades to a
    placeholder rather than inventing a value. An older daemon sends no
    context, and then the legacy ``ide · project`` line still renders.
    """
    if not isinstance(context, dict):
        return ""
    plc = context.get("plc") if isinstance(context.get("plc"), dict) else {}
    online = plc.get("online")
    if online is True:
        plc_text = "online"
    elif online is False:
        plc_text = "offline"
    else:
        plc_text = "unknown"
    state = plc.get("state")
    if state:
        plc_text = f"{plc_text}/{state}"
    edits = "blocked" if context.get("edits_allowed") is False else "allowed"
    line = "[ctx] project={0} ide={1} plc={2} edits={3}".format(
        context.get("project") or "?", context.get("ide") or "?", plc_text, edits
    )
    hint_short = context.get("hint_short")
    if hint_short and edits == "blocked":
        line += f" ({hint_short})"
    return line


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
    """Load cds-text-sync.json and the profile it selects.

    The CLI's one reader for that file. The settings come from the engine's
    reader, so the file has one interpretation whether it is read here, by the
    engine, or by the CODESYS host, and the search is that module's shared
    walk-up rule, so ``cts`` run from a subdirectory finds the same file as
    ``cts`` run from the sync root.

    Returns ``(settings, profile)`` or ``(settings, None)``. A missing file is
    normal: the defaults are the settings and the default profile is the
    profile. A file that exists but cannot be read is reported and yields the
    same minus the app defaults -- the command still runs, but the user is told
    the profile was ignored instead of having it dropped behind their back.
    """
    from cds_text_sync.engine._project_profiles import PROFILES_DIR, load_profile
    from cds_text_sync.engine._project_settings import (
        SETTINGS_INVALID,
        find_settings_root,
        read_project_settings,
    )

    try:
        root = find_settings_root(os.getcwd()) or os.getcwd()
    except OSError:
        root = os.getcwd()
    settings, status, error = read_project_settings(root, warn=False)
    if status == SETTINGS_INVALID:
        _print_error(
            "{0}; the profile's app/app_dir defaults were not applied".format(error)
        )
        return settings, None
    return settings, load_profile(settings.get("profile"), PROFILES_DIR)


def _apply_profile_defaults(params, profile):
    """Fill in the profile's application defaults for params that omit them.

    An explicit --app / --app-dir always wins: a profile supplies a default,
    never an override. Both daemon entry points go through here so the rule
    lives in one place.
    """
    if not profile:
        return params
    if "default_app_name" in profile and "app" not in params:
        params["app"] = profile["default_app_name"]
    if "plc_app_path" in profile and "app_dir" not in params:
        params["app_dir"] = profile["plc_app_path"]
    return params


# -- Reverse-pipe output helpers ----------------------------------------------


def _daemon_path(value):
    """Make a path the daemon will use absolute, or return it unchanged.

    The daemon runs inside CODESYS.exe, whose working directory is the CODESYS
    installation (``C:\\Program Files (x86)\\...\\Common``), so a relative path
    a user typed here would be resolved *there* -- writing a preset next to the
    IDE rather than next to the shell, and failing outright when that directory
    is not writable.  Absolutising against this process's cwd is what makes
    ``--out snap.json`` mean what the user typed it to mean.

    Only the CLI can do this: the daemon cannot know where the command was run
    from.  ``""`` (an unset option) is passed through so callers keep omitting
    the parameter entirely.
    """
    if not value:
        return value
    return os.path.abspath(str(value))


def _print_rp_error(resp, command):
    """Print reverse-pipe error details."""
    inst = resp.get("instance") or get_last_instance()
    inst_suffix = ""
    if inst and isinstance(inst, dict):
        inst_id = inst.get("id", "")
        prj = inst.get("project")
        prj_name = prj.get("name") if (prj and isinstance(prj, dict)) else None
        if prj_name:
            inst_suffix = f" ({inst_id} · {prj_name})"
        elif inst_id:
            inst_suffix = f" ({inst_id} · no project)"

    # Empty default on purpose: no error text means "look at data instead"
    # (library install failures and message lists arrive with ok False and no
    # error), so this must not fall back to a generic "unknown error".
    err = wire.response_error(resp, "")
    data = resp.get("data")
    install_error = data.get("install_error") if isinstance(data, dict) else None
    if err is not None and err != "":
        _print_error(f"{err}{inst_suffix}")
    elif install_error:
        _print_error(f"library install failed: {install_error}{inst_suffix}")
    else:
        messages = resp.get("data", {}).get("messages")
        if isinstance(messages, list) and messages:
            errors = [m for m in messages if m.get("severity") in ("Error", "error")]
            if errors:
                for m in errors:
                    code = m.get("code", "")
                    text = m.get("text", "")
                    obj = m.get("object", "")
                    _print_error("[{0}] {1} (in {2}){3}".format(code, text, obj, inst_suffix))
            else:
                _print_error(
                    "{0} failed with {1} warnings{2}".format(command, len(messages), inst_suffix)
                )
        else:
            _print_error(f"unknown error{inst_suffix}")
    diag = resp.get("diagnostics")
    if diag:
        _print_info("Diagnostics: {0}".format(json.dumps(diag, ensure_ascii=False)))


def _is_negative_number(token: str) -> bool:
    try:
        float(token)
        return token.startswith("-")
    except ValueError:
        return False


def _parse_key_value_args(args: list[str]) -> dict:
    params = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if i + 1 < len(args) and (not args[i + 1].startswith("--") or _is_negative_number(args[i + 1])):
                params[key] = args[i + 1]
                i += 2
            else:
                params[key] = True
                i += 1
        elif _is_negative_number(arg):
            _print_error(f"Unexpected positional argument: {arg}")
            sys.exit(1)
        else:
            _print_error(f"Unexpected positional argument: {arg}")
            sys.exit(1)
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
        _apply_profile_defaults(params, profile)
    except Exception as e:
        _print_info("Warning: could not load profile: {0}".format(e))
    if "timeout" in params:
        timeout = float(params.pop("timeout"))

    try:
        resp = send_command_reverse(command, params, timeout=timeout)
    except RuntimeError as e:
        _print_error("Reverse pipe error: {0}".format(e))
        _print_daemon_unreachable()
        sys.exit(1)

    if wire.response_ok(resp):
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
        _apply_profile_defaults(params, profile)
    except Exception as e:
        _print_info("Warning: could not load profile: {0}".format(e))

    try:
        resp = send_command_reverse(method, params, timeout=timeout)
    except RuntimeError as e:
        _print_error("Reverse pipe error: {0}".format(e))
        _print_daemon_unreachable()
        sys.exit(1)

    if wire.response_ok(resp):
        print(_format_output(resp.get("data", {}), fmt=output_fmt, title=method))
    else:
        _print_rp_error(resp, method)
        sys.exit(1)


# -- Legacy project command low-level -----------------------------------------


def _project_command(method, params=None, timeout=30):
    """Send a project command to the reverse-pipe daemon and print result.

    Exits non-zero on any failure so callers (and CI) get a truthful exit code,
    matching the daemon-command contract in _daemon_command().
    """
    try:
        resp = send_command_reverse(method, params or {}, timeout=timeout)
    except ConnectionError as e:
        _print_error("Cannot connect to daemon: {0}".format(e))
        _print_daemon_unreachable()
        sys.exit(1)
    except RuntimeError as e:
        _print_error("Command error: {0}".format(e))
        _print_daemon_unreachable()
        sys.exit(1)

    if wire.response_ok(resp):
        data = resp.get("data", {})
        print(_format_output(data, fmt="json", title=method))
    else:
        _print_rp_error(resp, method)
        sys.exit(1)


# -- Batch helper -------------------------------------------------------------

_BATCH_SIZE = 500


def _batch(method, key, items, timeout):
    """Send items to a daemon batch method in chunks. Returns {name: result}."""
    out = {}
    for i in range(0, len(items), _BATCH_SIZE):
        part = items[i : i + _BATCH_SIZE]
        resp = send_command_reverse(method, {key: part}, timeout=timeout)
        if not wire.response_ok(resp):
            raise RuntimeError(wire.response_error(resp, method + " failed"))
        for r in resp.get("data", {}).get("results", []):
            out[r["name"]] = r
    return out


# -- Direct engine_cli invocation --------------------------------------------


def cmd_direct(args: list[str]) -> NoReturn:
    """Run engine_cli directly (blocking, no daemon).

    Launched as ``python -m cds_text_sync.engine.engine_cli`` rather than by
    file path: as a script the module's relative imports would fail, and a
    ``sys.path`` shim to work around that would load every engine module a
    second time under its flat name.
    """
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
    # -P: ``-m`` would otherwise put the working directory first on the
    # child's sys.path, ahead of PYTHONPATH, and a ``cds_text_sync`` directory
    # there would shadow the engine.
    cmd = [sys.executable, "-P", "-m", _ENGINE_MODULE] + filtered
    _print_info("Running: {0}".format(" ".join(cmd)))
    proc = subprocess.Popen(cmd, env=_engine_subprocess_env())
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\nInterrupted.")
        sys.exit(1)
    sys.exit(proc.returncode)
