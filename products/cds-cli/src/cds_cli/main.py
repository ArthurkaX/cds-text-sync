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

import argparse
import json
import os
import sys
from pathlib import Path

from cds_text_sync.engine.pipe_targets import (
    Hello,
    TargetError,
    format_ambiguous,
    parse_target,
)
from cds_text_sync.engine.reverse_pipe_client import (
    configure,
    discover,
    ssh_dacl_hint,
)

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


# -- Help Header & Target Discovery ------------------------------------------


def _format_target_help_header(hello: Hello) -> str:
    prj = hello.project
    if prj and prj.get("name"):
        details = []
        if prj.get("path"):
            details.append(prj["path"])
        if prj.get("sync_folder"):
            details.append(f"sync: {prj['sync_folder']}")
        details_str = f" ({', '.join(details)})" if details else ""
        header = f"Target: {hello.id}  project {prj['name']}{details_str}\nPass --target {hello.id} on every command."
    else:
        header = f"Target: {hello.id}  (no project open)\nPass --target {hello.id} on every command."
    return header


def _ssh_hint_suffix(discovered) -> str:
    hint = "" if discovered else ssh_dacl_hint()
    return f"\n{hint}" if hint else ""


def _print_help_header(target: str | int | None = None) -> None:
    discovered = discover(1.0)
    target_pid = None
    if target:
        try:
            target_pid = parse_target(target)
        except ValueError:
            target_pid = None
    else:
        env_target = os.environ.get("CTS_TARGET")
        if env_target:
            try:
                target_pid = parse_target(env_target)
            except ValueError:
                target_pid = None

    if target_pid is not None:
        matching = [h for h in discovered if h.pid == target_pid]
        if matching:
            print(_format_target_help_header(matching[0]) + "\n")
        else:
            print(f"Note: target ide-{target_pid} not found among running IDEs.{_ssh_hint_suffix(discovered)}\n")
    else:
        if len(discovered) == 1:
            print(_format_target_help_header(discovered[0]) + "\n")
        elif len(discovered) > 1:
            print(format_ambiguous(discovered) + "\n")
        else:
            print(f"Note: no IDE answered; help printed anyway.{_ssh_hint_suffix(discovered)}\n")


# -- Entry point -------------------------------------------------------------


def main():
    parser = build_parser()

    # Pre-parse for --help / -h / --target / --expect-project
    help_parser = argparse.ArgumentParser(add_help=False)
    help_parser.add_argument("--target", default=None)
    help_parser.add_argument("--expect-project", default=None)
    help_parser.add_argument("-h", "--help", action="store_true")
    pre_args, _ = help_parser.parse_known_args()

    if pre_args.help or len(sys.argv) == 1:
        _print_help_header(target=pre_args.target)
        command_names: set[str] = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                command_names.update(action.choices)
        if pre_args.help and any(tok in command_names for tok in sys.argv[1:]):
            # `cts build --help`: let argparse print that command's own help.
            parser.parse_args()
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if getattr(args, "target", None):
        try:
            parse_target(args.target)
        except ValueError as exc:
            _print_error(str(exc))
            sys.exit(2)

    configure(target=args.target, expect_project=args.expect_project)

    use_reverse = True

    # Determine output format
    output_fmt = getattr(args, "output", "json")
    if getattr(args, "pretty", False):
        output_fmt = "text"

    try:
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

    except TargetError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
