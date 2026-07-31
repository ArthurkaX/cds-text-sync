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

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPT_DIR / "external_engine"
if _ENGINE_DIR.exists() and str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# -- Re-exports from submodules (used by main() and kept accessible) ----------

from cli._cli_io import (  # noqa: E402
    _print_error,
    _print_info,
    _print_ok,
    _format_output,
    _print_rp_error,
    _parse_key_value_args,
    _load_project_config,
    _find_codesys,
    _launch_codesys,
    _project_command,
    cmd_rp_command,
    cmd_daemon,
    cmd_direct,
    send_command_reverse,
    ENGINE_CLI,
    DAEMON_SCRIPT,
    _CODESYS_CANDIDATES,
)

from cli._cli_parser import build_parser  # noqa: E402

from cli._cli_handlers_project import (  # noqa: E402
    cmd_discover,
    dispatch_project,
    dispatch_pou,
)

from cli._cli_handlers_daemon import dispatch_daemon  # noqa: E402

from cli._cli_handlers_menu import dispatch_menu  # noqa: E402

from cli._cli_handlers_vars import (  # noqa: E402
    _resolve_project_view,
    _build_map_rows,
    _write_csv,
    cmd_read_vars,
    cmd_variable_map,
    cmd_variable_snapshot,
    cmd_variable_restore,
)

from cli._cli_handlers_visu import dispatch_visu  # noqa: E402

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
        dispatch_visu(args)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
