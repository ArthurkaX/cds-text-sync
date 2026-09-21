# -*- coding: utf-8 -*-
"""
main.py - CLI for cds-text-sync.

Universal entry point for CODESYS project sync.
Communicates with daemon inside CODESYS via Named Pipe.

Usage:
  cds-text-sync --help
  cds-text-sync status
  cds-text-sync export|import|compare
  cds-text-sync raw <daemon-method> [--key value ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

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
# -- Re-exports from submodules (used by main() and kept accessible) ----------

__all__ = [
    # from cds_cli._cli_io
    "_print_error",
    "_print_info",
    "_print_ok",
    "_format_output",
    "_print_rp_error",
    "_parse_key_value_args",
    "_load_project_config",
    "_find_codesys",
    "_launch_codesys",
    "_project_command",
    "cmd_rp_command",
    "cmd_daemon",
    "cmd_direct",
    "send_command_reverse",
    "ENGINE_CLI",
    "DAEMON_SCRIPT",
    "_CODESYS_CANDIDATES",
    # from cds_cli._cli_parser
    "build_parser",
    # from cds_cli._cli_handlers_*
    "cmd_discover",
    "dispatch_project",
    "dispatch_pou",
    "dispatch_daemon",
    "dispatch_menu",
    "dispatch_patch",
    "_resolve_project_view",
    "_build_map_rows",
    "_write_csv",
    "cmd_read_vars",
    "cmd_variable_map",
    "cmd_variable_snapshot",
    "cmd_variable_restore",
    "dispatch_visu",
]

from cds_cli._cli_handlers_daemon import dispatch_daemon  # noqa: E402
from cds_cli._cli_handlers_menu import dispatch_menu  # noqa: E402
from cds_cli._cli_handlers_patch import dispatch_patch  # noqa: E402
from cds_cli._cli_handlers_project import (  # noqa: E402
    cmd_discover,
    dispatch_pou,
    dispatch_project,
)
from cds_cli._cli_handlers_vars import (  # noqa: E402
    _build_map_rows,
    _resolve_project_view,
    _write_csv,
    cmd_read_vars,
    cmd_variable_map,
    cmd_variable_restore,
    cmd_variable_snapshot,
)
from cds_cli._cli_handlers_visu import dispatch_visu  # noqa: E402
from cds_cli._cli_io import (  # noqa: E402
    _CODESYS_CANDIDATES,
    DAEMON_SCRIPT,
    ENGINE_CLI,
    _find_codesys,
    _format_output,
    _launch_codesys,
    _load_project_config,
    _parse_key_value_args,
    _print_error,
    _print_info,
    _print_ok,
    _print_rp_error,
    _project_command,
    cmd_daemon,
    cmd_direct,
    cmd_rp_command,
    send_command_reverse,
)
from cds_cli._cli_parser import build_parser  # noqa: E402

_BATCH_SIZE = 500


# -- Entry point -------------------------------------------------------------


def main():
    parser = build_parser()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    if len(sys.argv) == 2 and ("--help" in sys.argv or "-h" in sys.argv):
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    use_reverse = True

    # Determine output format
    output_fmt = getattr(args, "output", "json")
    if getattr(args, "pretty", False):
        output_fmt = "text"

    if args.command == "engine":
        if not args.engine_args:
            _print_error(
                "Specify an engine command: export, import, compare, validate, resources"
            )
            sys.exit(1)
        cmd_direct(args.engine_args)
        return

    if dispatch_menu(args, output_fmt):
        return

    if dispatch_daemon(args, output_fmt):
        return

    if dispatch_patch(args, output_fmt):
        return

    if args.command in ("raw", "rp"):
        cmd_rp_command(
            args.cmd_args, timeout=getattr(args, "timeout", 15), output_fmt=output_fmt
        )

    elif args.command == "project":
        dispatch_project(args, use_reverse=use_reverse)

    elif args.command == "pou":
        dispatch_pou(args, use_reverse=use_reverse)

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
        try:
            dispatch_visu(args)
        except Exception as exc:
            # Visu library commands expose failures as values; this is the
            # process boundary where they become CLI diagnostics and status.
            from cds_text_sync.visu.commands import VisuCommandError

            if not isinstance(exc, VisuCommandError):
                raise
            _print_error(str(exc))
            sys.exit(exc.exit_code)

    elif args.command == "analyze":
        from cds_static_analyzer import cli as analyze_cli

        code = analyze_cli.dispatch_analyze(args)
        if code:
            sys.exit(code)

    elif args.command == "verify":
        from cds_cli.verify import run_verify

        code = run_verify(args, output_fmt)
        if code:
            sys.exit(code)

    elif args.command == "plc-crc-headless":
        from cds_cli.headless_crc import run_headless_crc, run_headless_crc_watch

        try:
            payload, code = (
                run_headless_crc_watch(args) if args.watch else run_headless_crc(args)
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            payload, code = {
                "ok": False,
                "error": {"code": "invalid_request", "message": str(exc)},
                "results": [],
            }, 2
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if code:
            sys.exit(code)

    elif args.command == "ui":
        from cds_text_sync.ui import launch

        code = launch(getattr(args, "workspace", ""))
        if code:
            sys.exit(code)

    elif args.command == "fsm":
        from cds_text_sync.fsm.cli import dispatch_fsm

        code = dispatch_fsm(args)
        if code:
            sys.exit(code)

    elif args.command == "docs":
        from cds_text_sync.docgen import (
            _resolve_doc_paths, check_docs, generate_docs, validate_bundle,
        )

        workspace = getattr(args, "workspace", "") or "."
        if getattr(args, "validate", False):
            output = getattr(args, "output", "") or None
            if output is None:
                _project_view, output_path = _resolve_doc_paths(workspace)
                output = str(output_path)
            diagnostics = validate_bundle(output)
            result = {"ok": not any(item.get("severity") == "error" for item in diagnostics),
                      "diagnostics": diagnostics}
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if not result["ok"]:
                sys.exit(1)
            return
        if getattr(args, "check", False):
            result = check_docs(workspace, output=getattr(args, "output", "") or None)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if result.get("exit_code"):
                sys.exit(result["exit_code"])
            return
        if getattr(args, "daemon", False):
            try:
                resp = send_command_reverse("generate_docs", {}, timeout=args.timeout)
            except RuntimeError as e:
                _print_error("Reverse pipe error: {0}".format(e))
                sys.exit(1)

            if not resp.get("ok"):
                _print_rp_error(resp, "generate_docs")
                sys.exit(1)
            workspace = resp.get("data", {}).get("sync_folder") or workspace

        result = generate_docs(
            workspace,
            library_path=getattr(args, "library_path", "") or None,
            output=getattr(args, "output", "") or None,
        )
        print(result["output"])

    elif args.command == "visu-lint":
        from visu_lint.cli import cmd_visu_lint

        code = cmd_visu_lint(args)
        if code:
            sys.exit(code)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
