# -*- coding: utf-8 -*-
"""
cds_text_sync.py - CLI for cds-text-sync.

Universal entry point for CODESYS project sync.
Communicates with daemon inside CODESYS via Named Pipe.

Usage:
    cds-text-sync --help
    cds-text-sync status
    cds-text-sync export|import|compare
    cds-text-sync raw <daemon-method> [--key value ...]
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
    _project_command(
        "export", {"output": path} if path else {}, use_reverse=use_reverse
    )


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
    _project_command(
        "write_variable", {"name": name, "value": value}, use_reverse=use_reverse
    )


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
    ordered = [
        results.get(
            name, {"name": name, "read_ok": False, "read_error": "no result returned"}
        )
        for name in exprs
    ]
    print(
        _format_output(
            {"results": ordered, "count": len(ordered)},
            fmt=output_fmt,
            title="read_variables",
        )
    )


def cmd_simulate(enable="on", use_reverse=False):
    """Enable/disable simulation mode."""
    _project_command("set_simulation_mode", {"enable": enable}, use_reverse=use_reverse)


def cmd_set_credentials(username, password="", use_reverse=False):
    """Set PLC login credentials."""
    _project_command(
        "set_credentials",
        {"username": username, "password": password},
        use_reverse=use_reverse,
    )


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
    _project_command(
        "compare", {"against": against}, timeout=120, use_reverse=use_reverse
    )


# -- POU commands -----------------------------------------------------------


def cmd_pou_delete(name="", app="", use_reverse=False):
    """Delete a POU from the project."""
    if not name:
        _print_error("POU name is required")
        return
    params = {"name": name}
    if app:
        params["app"] = app
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
    if os.path.basename(os.path.normpath(base)) == "project-view" and os.path.isdir(
        base
    ):
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
        part = items[i : i + _BATCH_SIZE]
        resp = send_command_reverse(method, {key: part}, timeout=timeout)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", method + " failed"))
        for r in resp.get("data", {}).get("results", []):
            out[r["name"]] = r
    return out


def cmd_variable_map(
    path_filter="", out="", sync_folder="", include_programs=True, output_fmt="json"
):
    """Build an offline variable map (CSV) from project-view declarations."""
    rows, stats, base, vm = _build_map_rows(path_filter, sync_folder, include_programs)
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


def cmd_variable_snapshot(
    path_filter="",
    out="",
    sync_folder="",
    include_programs=True,
    timeout=120,
    output_fmt="json",
):
    """Snapshot current online values for mapped leaves (CSV)."""
    import snapshot_engine as se

    rows, stats, base, vm = _build_map_rows(path_filter, sync_folder, include_programs)
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
    summary = {
        "output": out,
        "rows": len(rows),
        "read_ok": rstats["read_ok"],
        "read_failed": rstats["read_failed"],
        "failures": rstats.get("failures", []),
    }
    print(_format_output(summary, fmt=output_fmt, title="variable_snapshot"))


def cmd_variable_restore(
    input_path="",
    report="",
    path_filter="",
    do_apply=False,
    force=False,
    sync_folder="",
    timeout=120,
    output_fmt="json",
):
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

    eligible, skipped = se.plan_restore(
        snap_rows, force=force, enum_registry=enum_registry
    )

    base = sync_folder
    if not base:
        _, base = _resolve_project_view(sync_folder)
    if not report:
        report = os.path.join(base, "variable-restore-report.csv")

    if not do_apply:
        se.mark_dry_run(eligible)
        report_rows = eligible + skipped
        _write_csv(report, se.RESTORE_REPORT_COLUMNS, report_rows)
        summary = {
            "mode": "dry-run",
            "report": report,
            "would_write": len(eligible),
            "skipped": len(skipped),
            "hint": "re-run with --apply to write",
        }
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
    summary = {
        "mode": "apply",
        "report": report,
        "written": wstats["written"],
        "failed": wstats["failed"],
        "skipped": len(skipped),
    }
    print(_format_output(summary, fmt=output_fmt, title="variable_restore"))


# -- Direct engine_cli invocation -------------------------------------------


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


# -- Parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    prog = Path(sys.argv[0]).stem or "cts"
    if prog == "cds_text_sync":
        prog = "cts"
    parser = argparse.ArgumentParser(
        prog=prog,
        description="CODESYS text sync CLI. Talks to Project_daemon.py running inside CODESYS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
How to use:
  cts can run from any folder, but works best from the exported project folder.
  If project-view/ is available, treat the folder as the single source of truth.
  Prefer full imports: edit folder -> cts import -> cts build -> cts download/connect.

State model:
  There are three independent states: folder, CODESYS IDE, and PLC.
  Data moves in one direction during deployment: folder -> IDE -> PLC.
  CODESYS cannot safely edit/import project structure while the IDE is online
  with the PLC. Before folder -> IDE import, run:
    cts disconnect --timeout 15
  If the online preflight still fails after disconnect, use:
    cts import --force-online --timeout 120
  or:
    cts raw sync_import_text force_online=true --timeout 120

Connection state:
  cts ping and cts status include cached PLC state:
    connected, online, running, application_state, application
  They do not auto-connect to the PLC. If the daemon has not seen an online
  session yet, plc.known is false.

Examples:
  cts ping --timeout 10
  cts status --timeout 10
  cts export --timeout 60
  cts compare --timeout 60
  cts import --dry-run --timeout 60
  cts import --force-online --timeout 120
  cts build --timeout 120
  cts connect --ip 192.0.2.10 --timeout 60
  cts plc-crc --build --timeout 120
  cts test --file arithmetic.json --timeout 120
  cts raw application_tree --flat --output C:\\Temp\\vars.json --timeout 120
  cts engine validate --project-root ./MyProject
        """,
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format: json (default, LLM/script-friendly) or text (human-readable)",
    )
    parser.add_argument(
        "--pretty",
        "-p",
        action="store_true",
        help="Shortcut for --output text",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="command",
    )

    def add_timeout(p, default):
        p.add_argument(
            "--timeout",
            type=float,
            default=default,
            help="Timeout in seconds (default: {0})".format(default),
        )
        return p

    def add_daemon_parser(name, help_text, timeout):
        return add_timeout(subparsers.add_parser(name, help=help_text), timeout)

    # -- primary sync --------------------------------------------------------
    add_daemon_parser("ping", "Daemon liveness check with cached PLC state", 10)
    add_daemon_parser("status", "Show daemon, project, sync-folder, and PLC state", 10)
    add_daemon_parser("export", "IDE -> disk: refresh project-view/", 60)
    add_daemon_parser("compare", "IDE vs disk: compare against project-view/", 60)
    p_import = add_daemon_parser(
        "import", "disk -> IDE: apply project-view/ changes", 120
    )
    p_import.add_argument(
        "--force-online",
        action="store_true",
        help="Skip the 'application must be offline' preflight check",
    )
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what import would change without applying (runs compare)",
    )

    # -- build / PLC lifecycle ---------------------------------------------
    add_daemon_parser("build", "Compile the active CODESYS application", 120)
    p_connect = add_daemon_parser("connect", "Login/connect to PLC", 60)
    p_connect.add_argument("--ip", default="", help="PLC IP address")
    p_connect.add_argument(
        "--gateway", default="Gateway-1", help="Gateway name (default: Gateway-1)"
    )
    add_daemon_parser("disconnect", "Logout from PLC", 15)
    p_download = add_daemon_parser("download", "Force full download to PLC", 120)
    p_download.add_argument(
        "--start",
        choices=["0", "1"],
        default=None,
        help="Start after download: 1 yes, 0 no",
    )
    add_daemon_parser("start", "Start PLC application", 25)
    add_daemon_parser("stop", "Stop PLC application", 25)
    add_daemon_parser("app-state", "Show application online state", 10)
    p_crc = add_daemon_parser("plc-crc", "Compare PLC CRC with local build output", 30)
    p_crc.add_argument(
        "--build",
        action="store_true",
        help="Build the project first, then compare CRCs",
    )

    # -- variables ----------------------------------------------------------
    p_read = add_daemon_parser("read", "Read one PLC variable/expression", 25)
    p_read.add_argument("name", help="Variable/expression name")
    p_write = add_daemon_parser("write", "Write one PLC variable/expression", 25)
    p_write.add_argument("name", help="Variable/expression name")
    p_write.add_argument("value", help="Value to write")

    # -- tests --------------------------------------------------------------
    p_test = add_daemon_parser(
        "test",
        "Run JSON test plans from .test/ (see TEST_FORMAT.md)",
        120,
    )
    p_test.add_argument(
        "--file", default="", help="Test plan file (relative to .test/)"
    )

    # -- project/object tools ----------------------------------------------
    add_daemon_parser("project-info", "Show open project metadata", 10)
    p_ptree = add_daemon_parser("project-tree", "Show CODESYS project tree", 30)
    p_ptree.add_argument(
        "--depth", type=int, default=0, help="Tree depth, 0 = unlimited"
    )
    p_robj = add_daemon_parser(
        "read-object",
        "Read one project object by name/path/GUID (prefer --name)",
        30,
    )
    p_robj.add_argument(
        "--path",
        default="",
        help=(
            "Object path in IDE tree, e.g. 'Application/MAIN' or "
            "'Application/Globals/GVL_HMI' (use forward slashes)"
        ),
    )
    p_robj.add_argument("--name", default="", help="Object name, e.g. MAIN or GVL_HMI")
    p_robj.add_argument(
        "--guid", default="", help="Object GUID (rarely matches IDE GUID)"
    )
    p_upou = add_daemon_parser("update-pou", "Update one POU from an .st file", 25)
    p_upou.add_argument("--name", required=True, help="Object name")
    p_upou.add_argument(
        "--st-path", dest="st_path", required=True, help="Path to .st file"
    )
    p_upou.add_argument(
        "--app", default="", help="Application name (default: active application)"
    )
    p_dpou = add_daemon_parser("delete-pou", "Delete a POU/Function/FunctionBlock", 10)
    p_dpou.add_argument("name", help="Object name")
    p_dpou.add_argument(
        "--app", default="", help="Application name (default: active application)"
    )
    p_log = add_daemon_parser("read-log", "Read CODESYS IDE messages", 10)
    p_log.add_argument("--last", default="", help="Maximum messages to read")
    p_log.add_argument("--clear", action="store_true", help="Clear log after read")
    add_daemon_parser("permissions", "Show daemon permissions", 5)

    # -- raw / engine escape hatches ---------------------------------------
    p_raw = subparsers.add_parser(
        "raw",
        help="Send a daemon method directly",
        description=(
            "Compatibility/debug escape hatch for daemon methods. "
            "Useful overrides include force_online=true for sync_import_text "
            "and timeout=SECONDS. Run 'cts raw help' for the method list."
        ),
    )
    p_raw.add_argument(
        "cmd_args", nargs=argparse.REMAINDER, metavar="<method> [--key value ...]"
    )
    p_raw.add_argument(
        "--timeout",
        type=float,
        default=15,
        help="Timeout in seconds waiting for IDE response (default: 15)",
    )

    p_engine = subparsers.add_parser(
        "engine",
        help="Run engine_cli.py directly without CODESYS",
        description="Direct offline engine access. Does not talk to the daemon.",
    )
    p_engine.add_argument(
        "engine_args",
        nargs=argparse.REMAINDER,
        metavar="<export|import|compare|validate|resources> ...",
    )
    p_engine.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Accepted for consistency; ignored by the offline engine",
    )

    # -- project subcommand --------------------------------------------------
    p_project = subparsers.add_parser(
        "project",
        help=argparse.SUPPRESS,
        description="Project command interface via Project_daemon.py reverse-pipe mode.",
    )
    p_project.add_argument(
        "project_action",
        choices=[
            "info",
            "tree",
            "read",
            "open",
            "close",
            "list",
            "snapshot",
            "build",
            "list-devices",
            "compare",
            "device-status",
            "connect",
            "disconnect",
            "read-var",
            "write-var",
            "simulate",
            "set-credentials",
            "application-state",
            "diagnose-online",
        ],
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
        "application-state - get online application state\n",
    )
    p_project.add_argument(
        "--path",
        default="",
        help="Object path (for read) or project path (for open) or output (for snapshot)",
    )
    p_project.add_argument(
        "--name",
        default="",
        help="Object name (for read) or variable name (for read-var, write-var)",
    )
    p_project.add_argument(
        "--enable",
        default="on",
        help="Enable/disable simulation (on|off, for simulate)",
    )
    p_project.add_argument("--guid", default="", help="Object GUID (for read)")
    p_project.add_argument(
        "--depth", type=int, default=0, help="Tree depth, 0 = unlimited"
    )
    p_project.add_argument("--against", default="", help="Path to snapshot for compare")
    p_project.add_argument(
        "--device", default="", help="Device name filter (for device-status)"
    )
    p_project.add_argument("--ip", default="", help="PLC IP address (for connect)")
    p_project.add_argument(
        "--gateway",
        default="Gateway-1",
        help="Gateway name (for connect, default: Gateway-1)",
    )
    p_project.add_argument(
        "--value", default=None, help="Value to write (for write-var)"
    )
    p_project.add_argument(
        "--username", default="", help="Username (for set-credentials)"
    )
    p_project.add_argument(
        "--password", default="", help="Password (for set-credentials)"
    )

    # -- pou subcommand (Object deletion) ----------------------------------------
    p_pou = subparsers.add_parser(
        "pou",
        help=argparse.SUPPRESS,
        description="Delete Program Organization Units, Functions, and Function Blocks from the project.",
    )
    p_pou.add_argument(
        "pou_action",
        choices=["delete"],
        help="delete - delete an object",
    )
    p_pou.add_argument(
        "name", help="Object name (e.g. MAIN, MyFunction, Globals, MyDataType)"
    )
    p_pou.add_argument(
        "--app", default="", help="Application name (default: active application)"
    )

    # -- rp subcommand (reverse pipe) --------------------------------------
    p_rp = subparsers.add_parser(
        "rp",
        help=argparse.SUPPRESS,
        description="Deprecated alias for raw.",
    )
    p_rp.add_argument(
        "cmd_args",
        nargs=argparse.REMAINDER,
        metavar="<command> [--key value ...]",
    )
    p_rp.add_argument(
        "--timeout",
        type=float,
        default=15,
        help="Timeout in seconds waiting for IDE response (default: 15)",
    )

    # -- discover subcommand -------------------------------------------------
    subparsers.add_parser(
        "discover",
        help=argparse.SUPPRESS,
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
    p_rv.add_argument(
        "names",
        nargs="*",
        metavar="EXPR",
        help="Variable/expression names, e.g. GVL.a App.PRG.b",
    )
    p_rv.add_argument(
        "--file",
        dest="file",
        default="",
        help="Read names from a file (one expression per line)",
    )
    p_rv.add_argument(
        "--timeout", type=float, default=30, help="Timeout in seconds (default: 30)"
    )

    # -- variable map / snapshot / restore -----------------------------------
    p_vmap = subparsers.add_parser(
        "variable-map",
        help="Build an offline variable map (CSV) from project-view",
        description="Parse project-view/*.st declarations and expand to "
        "readable scalar leaves. No PLC connection required.",
    )
    p_vmap.add_argument(
        "--path", default="", help="Subtree filter, e.g. GVL_HMI or Application.GVL_HMI"
    )
    p_vmap.add_argument(
        "--out", default="", help="Output CSV path (default: <sync>/variable-map.csv)"
    )
    p_vmap.add_argument(
        "--sync-folder",
        default="",
        help="Sync folder or project-view dir (default: from daemon)",
    )
    p_vmap.add_argument(
        "--globals-only",
        action="store_true",
        help="Only GVL globals; exclude Program-local variables",
    )

    p_vsnap = subparsers.add_parser(
        "variable-snapshot",
        help="Snapshot current online values for mapped leaves (CSV)",
        description="Read live PLC values for every mapped scalar leaf. "
        "Requires an online/logged-in daemon.",
    )
    p_vsnap.add_argument("--path", default="", help="Subtree filter")
    p_vsnap.add_argument(
        "--out", default="", help="Output CSV (default: <sync>/variable-snapshot.csv)"
    )
    p_vsnap.add_argument("--sync-folder", default="", help="Sync/project-view dir")
    p_vsnap.add_argument(
        "--globals-only",
        action="store_true",
        help="Only GVL globals; exclude Program-local",
    )
    p_vsnap.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="Per-batch daemon timeout (default: 120)",
    )

    p_vrest = subparsers.add_parser(
        "variable-restore",
        help="Restore PLC values from a snapshot CSV (dry-run unless --apply)",
        description="Write values from a variable-snapshot CSV back to the PLC.",
    )
    p_vrest.add_argument(
        "--input",
        default="",
        required=True,
        help="Snapshot CSV produced by variable-snapshot",
    )
    p_vrest.add_argument(
        "--report",
        default="",
        help="Report CSV (default: <sync>/variable-restore-report.csv)",
    )
    p_vrest.add_argument("--path", default="", help="Subtree filter")
    p_vrest.add_argument(
        "--apply", action="store_true", help="Actually write values (default: dry-run)"
    )
    p_vrest.add_argument(
        "--force",
        action="store_true",
        help="Restore even rows with read_ok!=true or empty value",
    )
    p_vrest.add_argument("--sync-folder", default="", help="Sync/project-view dir")
    p_vrest.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="Per-batch daemon timeout (default: 120)",
    )

    # -- visu subcommand (offline) ------------------------------------------
    p_visu = subparsers.add_parser(
        "visu",
        help="Generate and manage CODESYS visualization XML files",
        description="Offline commands to create screens and add elements. "
        "These write .xml files directly into project-view/ "
        "for later import via ``cts import``.",
        epilog="""
from-svg SVG contract:
  Supported elements: rect, circle, ellipse, line, text,
    rect[data-cds-type=button], text[data-cds-type=textfield]

  CSS variables (set in :root block):
    --background  screen background
    --surface     panel/background fill default
    --panel       sub-panel fill
    --border --frame  stroke default
    --text        font colour
    --text-muted  muted/secondary font colour
    --primary     accent/highlight
    --secondary   secondary accent
    --success     green/ok
    --warning     orange/caution
    --error       red/alarm
    --water       pipe/fluid
    --metal       structural elements

  Color rules for SVG attributes:
    - <text fill="..."> controls font colour (compiles to uint literal)
    - <rect fill="..."> controls background fill
    - <rect stroke="..."> controls frame/border colour
    - <button> and <textfield> colours: SVG fill/stroke controls
      browser preview but is IGNORED by the transpiler. These
      elements inherit the CODESYS project visual style.
      For coloured button-like shapes use plain <rect> + <text>.

  Unsupported in v1: polygon, polyline, image, transform,
    gradients, filters, masks, animation, viewBox scaling,
    Table, ComboBox, TabControl, GroupBox, Checkbox, etc.
""",
    )
    p_visu.add_argument(
        "visu_action",
        choices=[
            "create-screen",
            "add",
            "list",
            "check",
            "types",
            "describe",
            "from-svg",
            "to-svg",
        ],
        help="create-screen - create a new empty screen\n"
        "add - add an element to a screen\n"
        "list - list elements in a screen\n"
        "check - validate a screen\n"
        "types - list available element types\n"
        "describe - describe a type or element\n"
        "from-svg - compile SVG to CODESYS screen XML\n"
        "to-svg - decompile CODESYS screen XML to SVG",
    )
    p_visu.add_argument(
        "--sync-folder", default="", help="Sync folder or project-view dir"
    )
    p_visu.add_argument("--name", default="", help="Screen name (for create-screen)")
    p_visu.add_argument(
        "--folder",
        default="",
        help="CODESYS folder path e.g. Runtime/PLC Logic/Application/HMI",
    )
    p_visu.add_argument(
        "--width", type=int, default=800, help="Screen width (for create-screen)"
    )
    p_visu.add_argument(
        "--height",
        type=int,
        default=480,
        help="Screen height (for create-screen)",
    )
    p_visu.add_argument(
        "--start-visu",
        action="store_true",
        help="Set as start visualization (for create-screen)",
    )
    p_visu.add_argument("--screen", default="", help="Screen name or path")
    p_visu.add_argument("--type", default="", help="Element type (for add, describe)")
    p_visu.add_argument("--x", type=int, help="X position")
    p_visu.add_argument("--y", type=int, help="Y position")
    p_visu.add_argument("--w", type=int, help="Width")
    p_visu.add_argument("--h", type=int, help="Height")
    p_visu.add_argument(
        "--shape",
        default="",
        help="Shape variant: rectangle|ellipse|rounded|line (for add)",
    )
    p_visu.add_argument("--fill", default="", help="Fill color (0xAARRGGBB or name)")
    p_visu.add_argument("--frame", default="", help="Frame color")
    p_visu.add_argument("--corner-radius", type=int, help="Corner radius (for add)")
    p_visu.add_argument("--border-width", type=int, help="Border width (for add)")
    p_visu.add_argument("--angle", type=int, help="Rotation angle (for add)")
    p_visu.add_argument("--tooltip", default="", help="Tooltip text (for add)")
    p_visu.add_argument(
        "--elem", type=int, help="Element index (for describe --screen --elem)"
    )
    p_visu.add_argument("--svg", default="", help="SVG file path (for from-svg)")
    p_visu.add_argument(
        "--theme",
        default="dark",
        help="Theme name: dark|light|hi-contrast (for from-svg)",
    )
    p_visu.add_argument("--out", default="", help="Output path (for from-svg, to-svg)")
    p_visu.add_argument(
        "--create-screen",
        action="store_true",
        help="Create a new screen when compiling SVG (for from-svg)",
    )
    p_visu.add_argument(
        "--screen-name", default="", help="Screen name when --create-screen is used"
    )

    # -- deprecated proxy subcommands for engine_cli -------------------------
    for cmd_name in ("validate", "resources"):
        _p = subparsers.add_parser(
            cmd_name,
            help=argparse.SUPPRESS,
            add_help=False,
        )
        _p.add_argument(
            "--timeout",
            type=float,
            default=None,
            help="Accepted for consistency; ignored by the offline engine",
        )

    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if action.help is not argparse.SUPPRESS
    ]

    return parser


# -- Entry point -------------------------------------------------------------


def main():
    parser = build_parser()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    if len(sys.argv) == 2 and ("--help" in sys.argv or "-h" in sys.argv):
        parser.print_help()
        sys.exit(0)

    args, unknown = parser.parse_known_args()

    use_reverse = True

    # Determine output format
    output_fmt = getattr(args, "output", "json")
    if getattr(args, "pretty", False):
        output_fmt = "text"

    # Deprecated direct engine aliases retained for compatibility.
    if args.command in ("validate", "resources"):
        full_args = [args.command] + unknown
        cmd_direct(full_args)
        return

    if args.command == "engine":
        if not args.engine_args:
            _print_error(
                "Specify an engine command: export, import, compare, validate, resources"
            )
            sys.exit(1)
        cmd_direct(args.engine_args)
        return

    daemon_methods = {
        "ping": "ping",
        "status": "status",
        "export": "sync_export_text",
        "import": "sync_import_text",
        "compare": "sync_compare_text",
        "build": "build",
        "disconnect": "disconnect_from_device",
        "download": "download",
        "start": "start_plc",
        "stop": "stop_plc",
        "app-state": "application_state",
        "plc-crc": "compare",
        "project-info": "project_info",
        "permissions": "permissions",
    }

    if args.command in daemon_methods:
        params = {}
        if args.command == "import":
            if getattr(args, "force_online", False):
                params["force_online"] = True
            if getattr(args, "dry_run", False):
                # Dry-run shows the same preview as compare.
                cmd_daemon(
                    "sync_compare_text",
                    {},
                    timeout=getattr(args, "timeout", 60),
                    output_fmt=output_fmt,
                )
                return
        if args.command == "download" and getattr(args, "start", None) is not None:
            params["start"] = args.start
        if args.command == "plc-crc" and getattr(args, "build", False):
            cmd_daemon("build", {}, timeout=args.timeout, output_fmt=output_fmt)
        cmd_daemon(
            daemon_methods[args.command],
            params,
            timeout=getattr(args, "timeout", 15),
            output_fmt=output_fmt,
        )
        return

    if args.command == "connect":
        params = {}
        if args.ip:
            params["ipAddress"] = args.ip
        if args.gateway:
            params["gatewayName"] = args.gateway
        cmd_daemon(
            "connect_to_device", params, timeout=args.timeout, output_fmt=output_fmt
        )
        return

    if args.command == "read":
        cmd_daemon(
            "read_variable",
            {"name": args.name},
            timeout=args.timeout,
            output_fmt=output_fmt,
        )
        return

    if args.command == "write":
        # Write and then read back so the caller can verify the value actually
        # took effect, returned in a single response.
        try:
            wr = send_command_reverse(
                "write_variable",
                {"name": args.name, "value": args.value},
                timeout=args.timeout,
            )
            if not wr.get("ok"):
                _print_rp_error(wr, "write_variable")
                sys.exit(1)
            rb = send_command_reverse(
                "read_variable", {"name": args.name}, timeout=args.timeout
            )
            read_back = rb.get("data", {}) if rb.get("ok") else {}
            print(
                _format_output(
                    {"written": True, "read_back": read_back},
                    fmt=output_fmt,
                    title="write",
                )
            )
        except RuntimeError as e:
            _print_error("Write failed: {0}".format(e))
            sys.exit(1)
        return

    if args.command == "test":
        params = {}
        if args.file:
            params["file"] = args.file
        cmd_daemon("cicd", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "project-tree":
        cmd_daemon(
            "project_tree",
            {"depth": args.depth},
            timeout=args.timeout,
            output_fmt=output_fmt,
        )
        return

    if args.command == "read-object":
        params = {}
        if args.path:
            params["path"] = args.path
        if args.name:
            params["name"] = args.name
        if args.guid:
            params["guid"] = args.guid
        cmd_daemon("read_object", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "update-pou":
        params = {
            "name": args.name,
            "st_path": args.st_path,
        }
        if args.app:
            params["app"] = args.app
        cmd_daemon("update_pou", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "delete-pou":
        params = {"name": args.name}
        if args.app:
            params["app"] = args.app
        cmd_daemon("delete_pou", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command == "read-log":
        params = {}
        if args.last:
            params["last"] = args.last
        if args.clear:
            params["clear"] = True
        cmd_daemon("read_log", params, timeout=args.timeout, output_fmt=output_fmt)
        return

    if args.command in ("raw", "rp"):
        cmd_rp_command(
            args.cmd_args, timeout=getattr(args, "timeout", 15), output_fmt=output_fmt
        )

    elif args.command == "project":
        if args.project_action == "info":
            cmd_project_info(use_reverse=use_reverse)
        elif args.project_action == "tree":
            cmd_project_tree(depth=args.depth, use_reverse=use_reverse)
        elif args.project_action == "read":
            cmd_project_read(
                path=args.path, name=args.name, guid=args.guid, use_reverse=use_reverse
            )
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
            cmd_set_credentials(
                username=args.username, password=args.password, use_reverse=use_reverse
            )
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
        cmd_read_vars(
            names=args.names,
            file_path=args.file,
            timeout=args.timeout,
            output_fmt=output_fmt,
        )

    elif args.command == "variable-map":
        cmd_variable_map(
            path_filter=args.path,
            out=args.out,
            sync_folder=args.sync_folder,
            include_programs=not args.globals_only,
            output_fmt=output_fmt,
        )

    elif args.command == "variable-snapshot":
        cmd_variable_snapshot(
            path_filter=args.path,
            out=args.out,
            sync_folder=args.sync_folder,
            include_programs=not args.globals_only,
            timeout=args.timeout,
            output_fmt=output_fmt,
        )

    elif args.command == "variable-restore":
        cmd_variable_restore(
            input_path=args.input,
            report=args.report,
            path_filter=args.path,
            do_apply=args.apply,
            force=args.force,
            sync_folder=args.sync_folder,
            timeout=args.timeout,
            output_fmt=output_fmt,
        )

    elif args.command == "visu":
        _root_dir = _SCRIPT_DIR.parent
        if str(_root_dir) not in sys.path:
            sys.path.insert(0, str(_root_dir))
        from cli.visu import commands as visu_cmds

        sync_folder = getattr(args, "sync_folder", "")

        if args.visu_action == "types":
            visu_cmds.list_types()
            return

        pv, _ = _resolve_project_view(sync_folder)

        if args.visu_action == "create-screen":
            if not args.name:
                _print_error("--name is required")
                sys.exit(1)
            visu_cmds.create_screen(
                project_view_dir=pv,
                name=args.name,
                folder=getattr(args, "folder", ""),
                width=args.width,
                height=args.height,
                start_visu=getattr(args, "start_visu", False),
            )
        elif args.visu_action == "add":
            if not args.screen:
                _print_error("--screen is required")
                sys.exit(1)
            if not args.type:
                _print_error("--type is required")
                sys.exit(1)
            params = {}
            _visu_map = {
                "x": "x",
                "y": "y",
                "w": "width",
                "h": "height",
                "shape": "shape",
                "fill": "fill",
                "frame": "frame",
                "corner_radius": "corner_radius",
                "border_width": "border_width",
                "angle": "angle",
                "tooltip": "tooltip",
            }
            for cli_key, params_key in _visu_map.items():
                raw = getattr(args, cli_key, None)
                if raw is not None and raw != "":
                    params[params_key] = raw
            visu_cmds.add_element(
                project_view_dir=pv,
                screen=args.screen,
                folder=getattr(args, "folder", ""),
                type_name=args.type,
                params=params,
            )
        elif args.visu_action == "list":
            if not args.screen:
                _print_error("--screen is required")
                sys.exit(1)
            visu_cmds.list_screen(
                project_view_dir=pv,
                screen=args.screen,
                folder=getattr(args, "folder", ""),
            )
        elif args.visu_action == "check":
            if not args.screen:
                _print_error("--screen is required")
                sys.exit(1)
            visu_cmds.check_screen(
                project_view_dir=pv,
                screen=args.screen,
                folder=getattr(args, "folder", ""),
            )
        elif args.visu_action == "describe":
            if not args.type:
                _print_error("--type is required")
                sys.exit(1)
            visu_cmds.describe(
                project_view_dir=pv,
                type_name=args.type,
                screen=getattr(args, "screen", ""),
                folder=getattr(args, "folder", ""),
                elem=getattr(args, "elem", None),
            )
        elif args.visu_action == "from-svg":
            if not args.svg:
                _print_error("--svg is required")
                sys.exit(1)
            visu_cmds.from_svg(
                project_view_dir=pv,
                svg_path=args.svg,
                screen=args.screen,
                folder=getattr(args, "folder", ""),
                theme_name=getattr(args, "theme", "dark"),
                out_path=getattr(args, "out", ""),
                create_screen=getattr(args, "create_screen", False),
                screen_name=getattr(args, "screen_name", ""),
            )
        elif args.visu_action == "to-svg":
            if not args.screen:
                _print_error("--screen is required")
                sys.exit(1)
            visu_cmds.to_svg(
                project_view_dir=pv,
                screen=args.screen,
                folder=getattr(args, "folder", ""),
                out_path=getattr(args, "out", ""),
            )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
