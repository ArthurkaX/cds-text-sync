# -*- coding: utf-8 -*-
"""
cds_text_sync.py - CLI for cds-text-sync.

Universal entry point for CODESYS project sync.
Communicates with daemon inside CODESYS via Named Pipe.
Can auto-launch CODESYS if daemon is not running.

Usage:
    cds-text-sync --help
    cds-text-sync daemon status|stop
    cds-text-sync exec export [--project-root ...]
    cds-text-sync project info|tree|read
    cds-text-sync export --project-root ...  (direct, no daemon)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPT_DIR / "external_engine"
if _ENGINE_DIR.exists() and str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from daemon_pipe import send_command, pipe_name
from reverse_pipe_client import send_command_reverse, reverse_pipe_name


# -- Config ------------------------------------------------------------------

ENGINE_CLI = _ENGINE_DIR / "engine_cli.py"
DAEMON_SCRIPT = _SCRIPT_DIR.parent / "Project_daemon.py"

_CODESYS_CANDIDATES = [
    r"C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files\CODESYS 3.5.20.0\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files\CODESYS 3.5.18.0\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files (x86)\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files (x86)\CODESYS 3.5.20.0\CODESYS\Common\CODESYS.exe",
    r"C:\Program Files (x86)\CODESYS 3.5.18.0\CODESYS\Common\CODESYS.exe",
]


def _print_info(msg):
    print(f"[INFO] {msg}", file=sys.stderr)


def _print_ok(msg):
    print(f"[OK] {msg}", file=sys.stderr)


def _print_error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)


def _print_manual():
    """Print the user manual (MANUAL.md) and exit."""
    manual_path = os.path.join(os.path.dirname(__file__), "MANUAL.md")
    if os.path.exists(manual_path):
        with open(manual_path, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print("Manual not found at: " + manual_path)
    sys.exit(0)


def _format_output(data, fmt="json", title=None):
    """Format output as JSON (machine) or text (human)."""
    if fmt == "text":
        if data is None:
            return "None"
        if isinstance(data, dict):
            lines = []
            if title:
                lines.append(f"── {title} ──")
            for k, v in data.items():
                if isinstance(v, dict):
                    lines.append(f"{k}:")
                    for sk, sv in v.items():
                        if isinstance(sv, (list, tuple)) and len(sv) > 5:
                            sv = f"[{len(sv)} items]"
                        lines.append(f"  {sk}: {sv}")
                elif isinstance(v, (list, tuple)):
                    if len(v) > 5:
                        lines.append(f"{k}: [{len(v)} items]")
                    elif len(v) > 0:
                        lines.append(f"{k}:")
                        for item in v:
                            lines.append(f"  - {item}")
                    else:
                        lines.append(f"{k}: []")
                else:
                    lines.append(f"{k}: {v}")
            return "\n".join(lines)
        if isinstance(data, (list, tuple)):
            return "\n".join(f"- {item}" for item in data)
        return str(data)
    return json.dumps(data, indent=2, ensure_ascii=False)


# -- CODESYS launcher --------------------------------------------------------

def _find_codesys() -> str | None:
    """Find CODESYS executable on this system."""
    for candidate in _CODESYS_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    import glob
    for pattern in [r"C:\Program Files\CODESYS*\CODESYS\Common\CODESYS.exe",
                    r"C:\Program Files (x86)\CODESYS*\CODESYS\Common\CODESYS.exe"]:
        matches = glob.glob(pattern)
        for m in matches:
            if os.path.exists(m):
                return m
    return None


def _launch_codesys(project_path: str | None = None,
                    codesys_path: str | None = None,
                    script_path: str | None = None,
                    wait: bool = False) -> bool:
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


def _ensure_daemon(project_path: str | None = None,
                   codesys_path: str | None = None) -> bool:
    """Check if daemon is running; if not, try to launch CODESYS."""
    try:
        resp = send_command("ping", timeout=3)
        if resp.get("ok"):
            return True
    except ConnectionError:
        pass

    # Daemon not running — ask user
    print()
    _print_info("CODESYS daemon is not running.")
    if project_path:
        print("  Project: {0}".format(project_path))
    else:
        print()
    print("  Options:")
    if project_path:
        print("    1. Launch CODESYS + project + daemon (auto)")
    else:
        print("    1. Launch CODESYS + daemon (no project) (auto)")
    print("    2. Manual: open CODESYS and run Project_daemon.py")
    print("    3. Cancel")
    print()
    choice = input("  Choose [1/2/3] (default 1): ").strip() or "1"

    if choice == "1":
        if not _launch_codesys(project_path=project_path,
                               codesys_path=codesys_path,
                               script_path=str(DAEMON_SCRIPT)):
            return False
        _print_info("Waiting for daemon to start...")
        # Wait up to 30 seconds for daemon
        for i in range(60):
            time.sleep(0.5)
            try:
                resp = send_command("ping", timeout=2)
                if resp.get("ok"):
                    _print_ok("Daemon is ready.")
                    return True
            except ConnectionError:
                pass
        _print_error("Daemon did not start within 30 seconds.")
        return False
    elif choice == "2":
        _print_info("Go to CODESYS -> Tools -> Scripting -> Execute Script")
        _print_info("  -> Project_daemon.py")
        _print_info("Then run this command again.")
        return False
    else:
        _print_info("Cancelled.")
        return False


# -- Daemon commands ---------------------------------------------------------

def cmd_daemon_status(project_path: str | None = None,
                      codesys_path: str | None = None):
    """Check daemon status, auto-launch if needed."""
    try:
        resp = send_command("status", timeout=5)
        if resp.get("ok"):
            data = resp.get("data", {})
            _print_ok("Daemon is RUNNING (pid={0})".format(data.get("pid", "?")))
            print("  Started at: {0}".format(data.get("started_at", "?")))
            print("  Projects captured: {0}".format(data.get("projects_captured", False)))
            print("  System captured:   {0}".format(data.get("system_captured", False)))
            print("  Named pipe: {0}".format(pipe_name()))
        else:
            _print_error("Daemon error: {0}".format(resp.get("error")))
    except ConnectionError:
        _print_info("Daemon is NOT running.")
        if project_path:
            _ensure_daemon(project_path=project_path, codesys_path=codesys_path)


def cmd_daemon_stop():
    """Stop daemon."""
    try:
        resp = send_command("stop", timeout=5)
        if resp.get("ok"):
            _print_ok("Daemon stopping...")
        else:
            _print_error("Daemon stop failed: {0}".format(resp.get("error")))
    except ConnectionError as e:
        _print_error("Cannot connect to daemon: {0}".format(e))


# -- Exec command (through daemon) -------------------------------------------

def cmd_exec(args: list[str]):
    """Execute command through daemon."""
    if not args:
        _print_error("Specify a command: export, import, compare, validate, resources.")
        sys.exit(1)

    command = args[0]
    params = _parse_key_value_args(args[1:])

    _print_info("Sending to daemon: {0}".format(command))

    try:
        resp = send_command(command, params, timeout=600)
    except ConnectionError as e:
        _print_error("Cannot connect to daemon: {0}".format(e))
        sys.exit(1)

    if resp.get("ok"):
        data = resp.get("data", {})
        stdout = data.get("stdout", "") or resp.get("stdout", "")
        stderr = data.get("stderr", "") or resp.get("stderr", "")
        if stdout:
            print(stdout.rstrip())
        if stderr:
            print(stderr.rstrip(), file=sys.stderr)
        rc = data.get("returncode", 0) or resp.get("returncode", 0)
        sys.exit(rc)
    else:
        _print_error("Command '{0}' failed: {1}".format(command, resp.get("error", "unknown")))
        sys.exit(1)


def cmd_rp_command(args: list[str], timeout: float = 15, output_fmt: str = "json"):
    """Send a command via reverse-pipe daemon.
    
    Args:
        args: Command name followed by --key value pairs
        timeout: Timeout in seconds
        output_fmt: Output format ("json" or "text")
    """
    if not args:
        _print_error("Specify a command: ping, status, project_info, application_state, etc.")
        sys.exit(1)

    command = args[0]
    params = _parse_key_value_args(args[1:])
    # Apply profile defaults for app/app_dir
    try:
        from _project_profiles import load_profile, PROFILES_DIR
        config_path = os.path.join(os.getcwd(), 'cds-text-sync.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            profile_name = config.get('profile')
            if profile_name:
                profile = load_profile(profile_name, PROFILES_DIR)
                if profile:
                    if 'default_app_name' in profile and 'app' not in params:
                        params['app'] = profile['default_app_name']
                    if 'plc_app_path' in profile and 'app_dir' not in params:
                        params['app_dir'] = profile['plc_app_path']
    except Exception:
        pass
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
                    _print_error("Build failed with {0} warnings".format(len(messages)))
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


# -- Legacy project commands ------------------------------------------------



def _project_command(method, params=None, timeout=30, use_reverse=False):
    """Send a project command to daemon and print result."""
    try:
        if use_reverse:
            resp = send_command_reverse(method, params or {}, timeout=timeout)
        else:
            resp = send_command(method, params or {}, timeout=timeout)
        if resp.get("ok"):
            data = resp.get("data", {})
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            _print_error(resp.get("error", "unknown error"))
    except ConnectionError as e:
        _print_error("Cannot connect to daemon: {0}".format(e))
    except RuntimeError as e:
        _print_error("Command error: {0}".format(e))


def cmd_project_info(use_reverse=False):
    _project_command("project_info", use_reverse=use_reverse)


def cmd_project_tree(depth=0, use_reverse=False):
    _project_command("project_tree", {"depth": depth}, use_reverse=use_reverse)


def cmd_project_read(path="", name="", guid="", use_reverse=False):
    params = {}
    if path:
        params["path"] = path
    if name:
        params["name"] = name
    if guid:
        params["guid"] = guid
    _project_command("read_object", params, use_reverse=use_reverse)


def cmd_project_open(path="", use_reverse=False):
    """Open a project in CODESYS."""
    _project_command("project_open", {"path": path}, use_reverse=use_reverse)


def cmd_project_close(use_reverse=False):
    """Close the current project in CODESYS."""
    _project_command("project_close", use_reverse=use_reverse)


def cmd_project_list(use_reverse=False):
    """List all open projects in CODESYS."""
    _project_command("project_list", use_reverse=use_reverse)


def cmd_project_snapshot(path="", use_reverse=False):
    """Export project snapshot (full XML) via daemon."""
    _project_command("export", {"output": path} if path else {}, use_reverse=use_reverse)


def cmd_project_build(use_reverse=False):
    """Build (compile) the project via daemon."""
    _project_command("build", use_reverse=use_reverse)


def cmd_project_list_devices(use_reverse=False):
    """List devices in the project via daemon."""
    _project_command("list_devices", use_reverse=use_reverse)


def cmd_device_status(device="", use_reverse=False):
    """Check online/connection status of devices."""
    params = {}
    if device:
        params["device"] = device
    _project_command("device_status", params, use_reverse=use_reverse)


def cmd_connect(ip="", gateway="Gateway-1", use_reverse=False):
    """Connect to a real PLC device."""
    params = {"ipAddress": ip, "gatewayName": gateway}
    _project_command("connect_to_device", params, use_reverse=use_reverse)


def cmd_disconnect(use_reverse=False):
    """Disconnect from PLC device."""
    _project_command("disconnect_from_device", use_reverse=use_reverse)


def cmd_read_var(name, use_reverse=False):
    """Read a PLC variable."""
    _project_command("read_variable", {"name": name}, use_reverse=use_reverse)


def cmd_write_var(name, value, use_reverse=False):
    """Write a value to a PLC variable."""
    _project_command("write_variable", {"name": name, "value": value}, use_reverse=use_reverse)


def cmd_simulate(enable="on", use_reverse=False):
    """Enable/disable simulation mode."""
    _project_command("set_simulation_mode", {"enable": enable}, use_reverse=use_reverse)


def cmd_set_credentials(username, password="", use_reverse=False):
    """Set PLC login credentials."""
    _project_command("set_credentials", {"username": username, "password": password}, use_reverse=use_reverse)


def cmd_application_state(use_reverse=False):
    """Get application online state."""
    _project_command("application_state", use_reverse=use_reverse)



def cmd_diagnose_online(use_reverse=False):
    """Diagnose online connection."""
    _project_command("diagnose_online", use_reverse=use_reverse)


def cmd_discover(use_reverse=False):
    """Discover CODESYS installations and open projects via daemon."""
    _project_command("discover", use_reverse=use_reverse)


def cmd_compare(against="", use_reverse=False):
    """Compare live project against a snapshot."""
    if not against:
        _print_error("Specify --against <path> for compare")
        return
    _project_command("compare", {"against": against}, timeout=120, use_reverse=use_reverse)


# -- Direct engine_cli invocation -------------------------------------------

def cmd_direct(args: list[str]) -> NoReturn:
    """Run engine_cli directly (blocking, no daemon)."""
    if not ENGINE_CLI.exists():
        _print_error("engine_cli.py not found: {0}".format(ENGINE_CLI))
        sys.exit(1)
    cmd = [sys.executable, str(ENGINE_CLI)] + args
    _print_info("Running: {0}".format(" ".join(cmd)))
    proc = subprocess.Popen(cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\nInterrupted.")
        sys.exit(1)
    sys.exit(proc.returncode)


# -- Parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cds-text-sync",
        description="CODESYS project synchronization tool.\n"
                    "Communicates with daemon inside CODESYS IDE via Named Pipe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cds-text-sync --help
  cds-text-sync daemon status
  cds-text-sync daemon status --project ./MyProject.project
  cds-text-sync exec export
  cds-text-sync project info
  cds-text-sync project tree --depth 3
  cds-text-sync export --project-root ./MyProject --snapshot ./IDE.xml
        """,
    )
    parser.add_argument(
        "--reverse", action="store_true",
        help="Use reverse-pipe mode (IDE polls as client, CLI creates pipe server)",
    )
    parser.add_argument(
        "--project", default=None,
        help="Path to CODESYS project (.project or .projectxml)",
    )
    parser.add_argument(
        "--codesys-path", default=None,
        help="Path to CODESYS.exe (auto-detected if not specified)",
    )
    parser.add_argument(
        "--output", choices=["json", "text"], default="json",
        help="Output format: json (default, LLM/script-friendly) or text (human-readable)",
    )
    parser.add_argument(
        "--pretty", "-p", action="store_true",
        help="Shortcut for --output text",
    )
    parser.add_argument(
        "--manual", action="store_true",
        help="Print the user manual (MANUAL.md) and exit",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- daemon subcommand ---------------------------------------------------
    p_daemon = subparsers.add_parser("daemon", help="Manage daemon")
    p_daemon.add_argument(
        "daemon_action",
        choices=["status", "stop"],
        help="status - check daemon status (auto-launch if not running)\n"
             "stop   - ask daemon to shut down",
    )

    # -- project subcommand --------------------------------------------------
    p_project = subparsers.add_parser(
        "project",
        help="Legacy daemon commands - project info, tree, read objects, online PLC operations",
        description="Legacy project command interface via the CODESYS daemon.",
    )
    p_project.add_argument(
        "project_action",
        choices=["info", "tree", "read", "open", "close", "list",
                 "snapshot", "build", "list-devices", "compare",
                 "device-status",
                 "connect", "disconnect",
                 "read-var", "write-var",
                 "simulate", "set-credentials",
                 "application-state",
                 "diagnose-online"],
        help="info - project details\n"
             "tree - object tree\n"
             "read - read object source\n"
             "open - open a project\n"
             "close - close current project\n"
             "list - list open projects\n"
             "snapshot - export full XML snapshot\n"
             "build - build project\n"
             "list-devices - list devices\n"
             "compare - compare with snapshot\n"
             "device-status - get device status\n"
             "connect - connect to PLC (best: connect in CODESYS before daemon; else approve dialog within 2min)\n"
             "disconnect - disconnect from PLC\n"
             "read-var - read PLC variable\n"
             "write-var - write PLC variable\n"
             "simulate on|off - toggle simulation mode\n"
             "set-credentials - set PLC credentials\n"
             "application-state - get online application state\n"
             "build - compile project\n"
             "list-devices - enumerate devices\n"
             "device-status - check device online/connection status\n"
             "connect --ip IP --gateway NAME - connect to PLC\n"
             "disconnect - disconnect from PLC\n"
             "read-var --name VAR - read PLC variable\n"
             "write-var --name VAR --value VAL - write PLC variable\n"
             "simulate on|off - toggle simulation mode\n"
             "set-credentials --username USER --password PASS - set PLC login\n"
             "application-state - get online application state\n"
             "compare --against FILE - diff live project vs snapshot",
    )
    p_project.add_argument("--path", default="",
                           help="Object path (for read) or project path (for open) or output (for snapshot)")
    p_project.add_argument("--name", default="", help="Object name (for read) or variable name (for read-var, write-var)")
    p_project.add_argument("--enable", default="on",
                           help="Enable/disable simulation (on|off, for simulate)")
    p_project.add_argument("--guid", default="", help="Object GUID (for read)")
    p_project.add_argument("--depth", type=int, default=0,
                           help="Tree depth, 0 = unlimited")
    p_project.add_argument("--against", default="",
                           help="Path to snapshot for compare")
    p_project.add_argument("--device", default="",
                           help="Device name filter (for device-status)")
    p_project.add_argument("--ip", default="",
                           help="PLC IP address (for connect)")
    p_project.add_argument("--gateway", default="Gateway-1",
                           help="Gateway name (for connect, default: Gateway-1)")
    p_project.add_argument("--value", default=None,
                           help="Value to write (for write-var)")
    p_project.add_argument("--username", default="",
                           help="Username (for set-credentials)")
    p_project.add_argument("--password", default="",
                           help="Password (for set-credentials)")
    p_exec = subparsers.add_parser(
        "exec",
        help="Execute command through daemon",
        description="Send command to daemon inside CODESYS.",
    )
    p_exec.add_argument(
        "cmd_args",
        nargs=argparse.REMAINDER,
        metavar="<command> [--key value ...]",
    )

    # -- rp subcommand (reverse pipe) --------------------------------------
    p_rp = subparsers.add_parser(
        "rp",
        help="Send command via reverse-pipe daemon (IDE polls as client)",
        description="Send command to CODESYS using reverse-pipe protocol.",
    )
    p_rp.add_argument(
        "cmd_args",
        nargs=argparse.REMAINDER,
        metavar="<command> [--key value ...]",
    )
    p_rp.add_argument(
        "--timeout", type=float, default=15,
        help="Timeout in seconds waiting for IDE response (default: 15)",
    )

    # -- discover subcommand -------------------------------------------------
    subparsers.add_parser(
        "discover",
        help="Discover CODESYS installations and open projects",
        add_help=False,
    )

    # -- proxy subcommands for engine_cli ------------------------------------
    for cmd_name in ("export", "import", "compare", "validate", "resources"):
        subparsers.add_parser(
            cmd_name,
            help="Run {0} directly (calls engine_cli)".format(cmd_name),
            add_help=False,
        )

    return parser


# -- Entry point -------------------------------------------------------------

def main():
    parser = build_parser()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    if "--manual" in sys.argv:
        _print_manual()
        return

    if len(sys.argv) == 2 and ("--help" in sys.argv or "-h" in sys.argv):
        parser.print_help()
        sys.exit(0)

    args, unknown = parser.parse_known_args()

    # Set reverse-pipe mode globally
    use_reverse = getattr(args, 'reverse', False)

    # If reverse flag is not set, check if the active profile has daemon_mode == 'reverse_pipe'
    if not use_reverse:
        try:
            from _project_profiles import load_profile, PROFILES_DIR
            config_path = os.path.join(os.getcwd(), 'cds-text-sync.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                profile_name = config.get('profile')
                if profile_name:
                    profile = load_profile(profile_name, PROFILES_DIR)
                    if profile and profile.get('daemon_mode') == 'reverse_pipe':
                        use_reverse = True
        except Exception:
            pass

    # Determine output format
    output_fmt = getattr(args, 'output', 'json')
    if getattr(args, 'pretty', False):
        output_fmt = 'text'

    # Print manual if requested
    if getattr(args, 'manual', False):
        _print_manual()
        return

    # For proxy commands, pass through to engine_cli
    if args.command in ("export", "import", "compare", "validate", "resources"):
        full_args = [args.command] + unknown
        cmd_direct(full_args)
        return

    if args.command == "daemon":
        if args.daemon_action == "status":
            cmd_daemon_status(project_path=args.project,
                              codesys_path=args.codesys_path)
        elif args.daemon_action == "stop":
            cmd_daemon_stop()

    elif args.command == "exec":
        cmd_exec(args.cmd_args)

    elif args.command == "rp":
        cmd_rp_command(args.cmd_args, timeout=getattr(args, 'timeout', 15),
                       output_fmt=output_fmt)

    elif args.command == "project":
        if args.project_action == "info":
            cmd_project_info(use_reverse=use_reverse)
        elif args.project_action == "tree":
            cmd_project_tree(depth=args.depth, use_reverse=use_reverse)
        elif args.project_action == "read":
            cmd_project_read(path=args.path, name=args.name, guid=args.guid, use_reverse=use_reverse)
        elif args.project_action == "open":
            cmd_project_open(path=args.path, use_reverse=use_reverse)
        elif args.project_action == "close":
            cmd_project_close(use_reverse=use_reverse)
        elif args.project_action == "list":
            cmd_project_list(use_reverse=use_reverse)
        elif args.project_action == "snapshot":
            cmd_project_snapshot(path=args.path, use_reverse=use_reverse)
        elif args.project_action == "build":
            cmd_project_build(use_reverse=use_reverse)
        elif args.project_action == "list-devices":
            cmd_project_list_devices(use_reverse=use_reverse)
        elif args.project_action == "compare":
            cmd_compare(against=args.against, use_reverse=use_reverse)
        elif args.project_action == "device-status":
            cmd_device_status(device=args.device, use_reverse=use_reverse)
        elif args.project_action == "connect":
            cmd_connect(ip=args.ip, gateway=args.gateway, use_reverse=use_reverse)
        elif args.project_action == "disconnect":
            cmd_disconnect(use_reverse=use_reverse)
        elif args.project_action == "read-var":
            cmd_read_var(name=args.name, use_reverse=use_reverse)
        elif args.project_action == "write-var":
            cmd_write_var(name=args.name, value=args.value, use_reverse=use_reverse)
        elif args.project_action == "simulate":
            cmd_simulate(enable=args.enable, use_reverse=use_reverse)
        elif args.project_action == "set-credentials":
            cmd_set_credentials(username=args.username, password=args.password, use_reverse=use_reverse)
        elif args.project_action == "application-state":
            cmd_application_state(use_reverse=use_reverse)
        elif args.project_action == "diagnose-online":
            cmd_diagnose_online(use_reverse=use_reverse)

    elif args.command == "discover":
        cmd_discover(use_reverse=use_reverse)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
