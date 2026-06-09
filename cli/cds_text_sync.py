# -*- coding: utf-8 -*-
"""
cds_text_sync.py - CLI for cds-text-sync.

Universal entry point for CODESYS project sync.
Communicates with daemon inside CODESYS via Named Pipe.

Usage:
    cds-text-sync --help
    cds-text-sync rp status
    cds-text-sync project info|tree|read
    cds-text-sync export --project-root ...  (direct, no daemon)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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

from reverse_pipe_client import send_command_reverse


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
        from _project_profiles import load_profile, PROFILES_DIR
        profile = load_profile(profile_name, PROFILES_DIR)

    return config, profile


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
                _print_error("{0} failed with {1} warnings".format(command, len(messages)))
        else:
            _print_error("unknown error")
    diag = resp.get("diagnostics")
    if diag:
        _print_info("Diagnostics: {0}".format(json.dumps(diag, ensure_ascii=False)))


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
        _config, profile = _load_project_config()
        if profile:
            if 'default_app_name' in profile and 'app' not in params:
                params['app'] = profile['default_app_name']
            if 'plc_app_path' in profile and 'app_dir' not in params:
                params['app_dir'] = profile['plc_app_path']
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



def _project_command(method, params=None, timeout=30, use_reverse=True):
    """Send a project command to the reverse-pipe daemon and print result."""
    try:
        resp = send_command_reverse(method, params or {}, timeout=timeout)
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


def cmd_read_vars(names, file_path="", timeout=30, output_fmt="json"):
    """Batch-read multiple PLC variables/expressions.

    Names come from positional args and/or a --file (one expression per line,
    blank lines and #-comments ignored). Sends a proper JSON list to the
    daemon's read_variables, so this avoids the `rp read_variables` string
    pitfall where --names is passed as a raw string.
    """
    exprs = list(names or [])
    if file_path:
        if not os.path.exists(file_path):
            _print_error("File not found: {0}".format(file_path))
            sys.exit(1)
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    exprs.append(line)
    if not exprs:
        _print_error("No variable names given. Pass names as arguments or via --file.")
        sys.exit(1)

    try:
        results = _batch("read_variables", "names", exprs, timeout)
    except RuntimeError as e:
        _print_error("read-vars failed: {0}".format(e))
        sys.exit(1)

    # Preserve the requested order in the output.
    ordered = [results.get(name, {"name": name, "read_ok": False,
                                   "read_error": "no result returned"})
               for name in exprs]
    print(_format_output({"results": ordered, "count": len(ordered)},
                         fmt=output_fmt, title="read_variables"))


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


# -- POU commands -----------------------------------------------------------

def cmd_pou_delete(name="", app="CI_CD_Application", use_reverse=False):
    """Delete a POU from the project."""
    if not name:
        _print_error("POU name is required")
        return
    params = {"name": name, "app": app}
    _project_command("delete_pou", params, use_reverse=use_reverse)


# -- Variable map / snapshot / restore --------------------------------------

import csv as _csv

_BATCH_SIZE = 500


def _resolve_project_view(sync_folder):
    """Return (project_view_dir, sync_folder_base).

    Uses --sync-folder when given, else asks the daemon for sync_folder.
    """
    base = sync_folder
    if not base:
        try:
            resp = send_command_reverse("status", {}, timeout=10)
            if resp.get("ok"):
                base = resp.get("data", {}).get("sync_folder")
        except Exception as e:
            _print_error("Could not get sync folder from daemon: {0}".format(e))
            sys.exit(1)
    if not base:
        _print_error("No sync folder. Pass --sync-folder or start the daemon.")
        sys.exit(1)
    base = str(base)
    if os.path.basename(os.path.normpath(base)) == "project-view" \
            and os.path.isdir(base):
        return base, os.path.dirname(os.path.normpath(base))
    pv = os.path.join(base, "project-view")
    if not os.path.isdir(pv):
        _print_error("project-view not found under: {0}".format(base))
        sys.exit(1)
    return pv, base


def _build_map_rows(path_filter, sync_folder, include_programs):
    import variable_map as vm
    pv, base = _resolve_project_view(sync_folder)
    rows, stats = vm.build_map_from_dir(pv, include_programs=include_programs)
    if path_filter:
        rows = vm.filter_rows_by_path(rows, path_filter)
        if not rows:
            _print_error("Path filter matched nothing: {0}".format(path_filter))
            sys.exit(1)
    return rows, stats, base, vm


def _write_csv(path, columns, rows):
    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _batch(method, key, items, timeout):
    """Send items to a daemon batch method in chunks. Returns {name: result}."""
    out = {}
    for i in range(0, len(items), _BATCH_SIZE):
        part = items[i:i + _BATCH_SIZE]
        resp = send_command_reverse(method, {key: part}, timeout=timeout)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", method + " failed"))
        for r in resp.get("data", {}).get("results", []):
            out[r["name"]] = r
    return out


def cmd_variable_map(path_filter="", out="", sync_folder="",
                     include_programs=True, output_fmt="json"):
    """Build an offline variable map (CSV) from project-view declarations."""
    rows, stats, base, vm = _build_map_rows(path_filter, sync_folder,
                                            include_programs)
    if not out:
        out = os.path.join(base, "variable-map.csv")
    _write_csv(out, vm.MAP_COLUMNS, rows)
    summary = {
        "output": out,
        "rows": len(rows),
        "readable_leaves": sum(1 for r in rows if r.get("leaf")),
        "owners": stats.get("owners"),
    }
    print(_format_output(summary, fmt=output_fmt, title="variable_map"))


def cmd_variable_snapshot(path_filter="", out="", sync_folder="",
                          include_programs=True, timeout=120,
                          output_fmt="json"):
    """Snapshot current online values for mapped leaves (CSV)."""
    import snapshot_engine as se
    rows, stats, base, vm = _build_map_rows(path_filter, sync_folder,
                                            include_programs)
    read_fn = lambda exprs: _batch("read_variables", "names", exprs, timeout)
    try:
        rows, rstats = se.run_snapshot(rows, read_fn)
    except RuntimeError as e:
        _print_error("Snapshot read failed: {0}".format(e))
        sys.exit(1)

    if not out:
        out = os.path.join(base, "variable-snapshot.csv")
    cols = vm.MAP_COLUMNS + se.SNAPSHOT_COLUMNS
    _write_csv(out, cols, rows)
    summary = {"output": out, "rows": len(rows),
               "read_ok": rstats["read_ok"], "read_failed": rstats["read_failed"]}
    print(_format_output(summary, fmt=output_fmt, title="variable_snapshot"))


def cmd_variable_restore(input_path="", report="", path_filter="",
                         do_apply=False, force=False, sync_folder="",
                         timeout=120, output_fmt="json"):
    """Restore PLC values from a snapshot CSV. Dry-run unless --apply."""
    import snapshot_engine as se
    if not input_path:
        _print_error("Specify --input <snapshot.csv>")
        sys.exit(1)
    if not os.path.exists(input_path):
        _print_error("Snapshot not found: {0}".format(input_path))
        sys.exit(1)

    import variable_map as vm
    with open(input_path, "r", newline="", encoding="utf-8") as f:
        snap_rows = list(_csv.DictReader(f))
    if path_filter:
        snap_rows = vm.filter_rows_by_path(snap_rows, path_filter)

    # Determine the project-view base for enum registry
    _pd, _pb = _resolve_project_view(sync_folder)
    enum_base = sync_folder
    if not enum_base:
        enum_base = _pb

    # Build an enum registry from the project-view so we can translate
    # 'TYPE.member' (snapshot) into a numeric value acceptable to
    # set_prepared_value (CODESYS double-prefixes qualified enumerators).
    enum_registry = {}
    if enum_base and os.path.isdir(enum_base):
        try:
            enum_registry = vm.build_enum_registry(enum_base)
        except Exception:
            pass

    eligible, skipped = se.plan_restore(snap_rows, force=force,
                                        enum_registry=enum_registry)

    base = sync_folder
    if not base:
        _, base = _resolve_project_view(sync_folder)
    if not report:
        report = os.path.join(base, "variable-restore-report.csv")

    if not do_apply:
        se.mark_dry_run(eligible)
        report_rows = eligible + skipped
        _write_csv(report, se.RESTORE_REPORT_COLUMNS, report_rows)
        summary = {"mode": "dry-run", "report": report,
                   "would_write": len(eligible), "skipped": len(skipped),
                   "hint": "re-run with --apply to write"}
        print(_format_output(summary, fmt=output_fmt, title="variable_restore"))
        return

    write_fn = lambda items: _batch("write_variables", "items", items, timeout)
    try:
        eligible, wstats = se.apply_restore(eligible, write_fn)
    except RuntimeError as e:
        _print_error("Restore write failed: {0}".format(e))
        sys.exit(1)

    report_rows = eligible + skipped
    _write_csv(report, se.RESTORE_REPORT_COLUMNS, report_rows)
    summary = {"mode": "apply", "report": report,
               "written": wstats["written"], "failed": wstats["failed"],
               "skipped": len(skipped)}
    print(_format_output(summary, fmt=output_fmt, title="variable_restore"))


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
                    "Communicates with Project_daemon.py inside CODESYS using reverse-pipe mode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cds-text-sync --help
  cds-text-sync rp status
  cds-text-sync rp ping
  cds-text-sync variable-map --path GVL_HMI
  cds-text-sync variable-snapshot --path GVL_HMI --out snap.csv
  cds-text-sync variable-restore --input snap.csv --apply
  cds-text-sync rp application_tree --depth 100 --values --output C:\\Temp\\vars.json
  cds-text-sync project info
  cds-text-sync export --project-root ./MyProject --snapshot ./IDE.xml
        """,
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

    # -- project subcommand --------------------------------------------------
    p_project = subparsers.add_parser(
        "project",
        help="Project commands through the reverse-pipe daemon",
        description="Project command interface via Project_daemon.py reverse-pipe mode.",
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

    # -- pou subcommand (Object deletion) ----------------------------------------
    p_pou = subparsers.add_parser(
        "pou",
        help="Delete objects (POU, Function, FunctionBlock)",
        description="Delete Program Organization Units, Functions, and Function Blocks from the project.",
    )
    p_pou.add_argument(
        "pou_action",
        choices=["delete"],
        help="delete - delete an object",
    )
    p_pou.add_argument("name", help="Object name (e.g. MAIN, MyFunction, Globals, MyDataType)")
    p_pou.add_argument("--app", default="CI_CD_Application",
                       help="Application name (default: CI_CD_Application)")

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

    # -- read-vars subcommand (batch read) -----------------------------------
    p_rv = subparsers.add_parser(
        "read-vars",
        help="Batch-read multiple PLC variables/expressions",
        description="Read several variables/expressions in one call. Sends a "
                    "proper JSON list to the daemon (unlike `rp read_variables "
                    "--names`, which passes a raw string).",
    )
    p_rv.add_argument("names", nargs="*", metavar="EXPR",
                      help="Variable/expression names, e.g. GVL.a App.PRG.b")
    p_rv.add_argument("--file", dest="file", default="",
                      help="Read names from a file (one expression per line)")
    p_rv.add_argument("--timeout", type=float, default=30,
                      help="Timeout in seconds (default: 30)")

    # -- variable map / snapshot / restore -----------------------------------
    p_vmap = subparsers.add_parser(
        "variable-map",
        help="Build an offline variable map (CSV) from project-view",
        description="Parse project-view/*.st declarations and expand to "
                    "readable scalar leaves. No PLC connection required.",
    )
    p_vmap.add_argument("--path", default="",
                        help="Subtree filter, e.g. GVL_HMI or Application.GVL_HMI")
    p_vmap.add_argument("--out", default="",
                        help="Output CSV path (default: <sync>/variable-map.csv)")
    p_vmap.add_argument("--sync-folder", default="",
                        help="Sync folder or project-view dir (default: from daemon)")
    p_vmap.add_argument("--globals-only", action="store_true",
                        help="Only GVL globals; exclude Program-local variables")

    p_vsnap = subparsers.add_parser(
        "variable-snapshot",
        help="Snapshot current online values for mapped leaves (CSV)",
        description="Read live PLC values for every mapped scalar leaf. "
                    "Requires an online/logged-in daemon.",
    )
    p_vsnap.add_argument("--path", default="", help="Subtree filter")
    p_vsnap.add_argument("--out", default="",
                         help="Output CSV (default: <sync>/variable-snapshot.csv)")
    p_vsnap.add_argument("--sync-folder", default="", help="Sync/project-view dir")
    p_vsnap.add_argument("--globals-only", action="store_true",
                         help="Only GVL globals; exclude Program-local")
    p_vsnap.add_argument("--timeout", type=float, default=120,
                         help="Per-batch daemon timeout (default: 120)")

    p_vrest = subparsers.add_parser(
        "variable-restore",
        help="Restore PLC values from a snapshot CSV (dry-run unless --apply)",
        description="Write values from a variable-snapshot CSV back to the PLC.",
    )
    p_vrest.add_argument("--input", default="", required=True,
                         help="Snapshot CSV produced by variable-snapshot")
    p_vrest.add_argument("--report", default="",
                         help="Report CSV (default: <sync>/variable-restore-report.csv)")
    p_vrest.add_argument("--path", default="", help="Subtree filter")
    p_vrest.add_argument("--apply", action="store_true",
                         help="Actually write values (default: dry-run)")
    p_vrest.add_argument("--force", action="store_true",
                         help="Restore even rows with read_ok!=true or empty value")
    p_vrest.add_argument("--sync-folder", default="", help="Sync/project-view dir")
    p_vrest.add_argument("--timeout", type=float, default=120,
                         help="Per-batch daemon timeout (default: 120)")

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

    use_reverse = True

    # Determine output format
    output_fmt = getattr(args, 'output', 'json')
    if getattr(args, 'pretty', False):
        output_fmt = 'text'

    # For proxy commands, pass through to engine_cli
    if args.command in ("export", "import", "compare", "validate", "resources"):
        full_args = [args.command] + unknown
        cmd_direct(full_args)
        return

    if args.command == "rp":
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

    elif args.command == "pou":
        if args.pou_action == "delete":
            cmd_pou_delete(name=args.name, app=args.app, use_reverse=use_reverse)

    elif args.command == "discover":
        cmd_discover(use_reverse=use_reverse)

    elif args.command == "read-vars":
        cmd_read_vars(names=args.names, file_path=args.file,
                      timeout=args.timeout, output_fmt=output_fmt)

    elif args.command == "variable-map":
        cmd_variable_map(path_filter=args.path, out=args.out,
                         sync_folder=args.sync_folder,
                         include_programs=not args.globals_only,
                         output_fmt=output_fmt)

    elif args.command == "variable-snapshot":
        cmd_variable_snapshot(path_filter=args.path, out=args.out,
                              sync_folder=args.sync_folder,
                              include_programs=not args.globals_only,
                              timeout=args.timeout, output_fmt=output_fmt)

    elif args.command == "variable-restore":
        cmd_variable_restore(input_path=args.input, report=args.report,
                             path_filter=args.path, do_apply=args.apply,
                             force=args.force, sync_folder=args.sync_folder,
                             timeout=args.timeout, output_fmt=output_fmt)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
