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
from cts_shared import wire

try:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

# -- Public surface -----------------------------------------------------------

# main() pulls the handlers and helpers in from their own modules below; the
# names are module globals because main() calls them, not a re-export API.
# This list is the module's public surface: the entry point and the parser
# builder (tests import the rest from the module that defines them).
__all__ = [
    "main",
    "build_parser",
]

from cds_cli._cli_handlers_config import dispatch_config  # noqa: E402
from cds_cli._cli_handlers_daemon import dispatch_daemon  # noqa: E402
from cds_cli._cli_handlers_guide import dispatch_guide  # noqa: E402
from cds_cli._cli_handlers_menu import dispatch_menu  # noqa: E402
from cds_cli._cli_handlers_patch import dispatch_patch  # noqa: E402
from cds_cli._cli_handlers_plc_log import dispatch_plc_log  # noqa: E402
from cds_cli._cli_handlers_project import (  # noqa: E402
    cmd_discover,
    dispatch_pou,
    dispatch_project,
)
from cds_cli._cli_handlers_new_object import dispatch_new_object  # noqa: E402
from cds_cli._cli_handlers_snapshooter import dispatch_snapshooter  # noqa: E402
from cds_cli._cli_handlers_vars import (  # noqa: E402
    cmd_read_vars,
    cmd_variable_map,
    cmd_variable_restore,
    cmd_variable_snapshot,
)
from cds_cli._cli_handlers_visu import dispatch_visu  # noqa: E402
from cds_cli._cli_io import (  # noqa: E402
    _print_daemon_unreachable,
    _print_error,
    _print_rp_error,
    cmd_direct,
    cmd_rp_command,
    send_command_reverse,
)
from cds_cli._cli_parser import build_parser  # noqa: E402

_BATCH_SIZE = 500


# -- Help Header & Target Discovery ------------------------------------------


def _format_target_help_header(hello: Hello, advise: bool = True) -> str:
    """The "which IDE am I talking to" header.

    ``advise`` adds "Pass --target ... on every command." It is dropped when
    there is only one IDE: with nothing to choose between, telling the user to
    pass --target for the sole instance is advice they do not need (and the
    `cts raw` escape hatch repeated it on every help call).
    """
    prj = hello.project
    if prj and prj.get("name"):
        details = []
        if prj.get("path"):
            details.append(prj["path"])
        if prj.get("sync_folder"):
            details.append(f"sync: {prj['sync_folder']}")
        details_str = f" ({', '.join(details)})" if details else ""
        header = f"Target: {hello.id}  project {prj['name']}{details_str}"
    else:
        header = f"Target: {hello.id}  (no project open)"
    if advise:
        header += f"\nPass --target {hello.id} on every command."
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
            # One IDE: there is nothing to disambiguate, so no --target advice.
            print(_format_target_help_header(discovered[0], advise=False) + "\n")
        elif len(discovered) > 1:
            print(format_ambiguous(discovered) + "\n")
        else:
            print(f"Note: no IDE answered; help printed anyway.{_ssh_hint_suffix(discovered)}\n")


# -- Entry point -------------------------------------------------------------


def _parse_leading_flags():
    """Pre-parse --help/--target/--expect-project, before the full parser."""
    help_parser = argparse.ArgumentParser(add_help=False)
    help_parser.add_argument("--target", default=None)
    help_parser.add_argument("--expect-project", default=None)
    help_parser.add_argument("-h", "--help", action="store_true")
    pre_args, _ = help_parser.parse_known_args()
    return pre_args


def _print_help_and_exit(parser, pre_args):
    """Print the help header and parser help, then stop with status 0."""
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


def _validate_target(args):
    """Reject a malformed --target before any command runs."""
    if getattr(args, "target", None):
        try:
            parse_target(args.target)
        except ValueError as exc:
            _print_error(str(exc))
            sys.exit(2)


def _output_format(args):
    """Resolve --output/--pretty into the format handed to every handler."""
    output_fmt = getattr(args, "output", "json")
    if getattr(args, "pretty", False):
        output_fmt = "text"
    return output_fmt


def _dispatch_engine(args):
    """`cts engine ...` runs the offline engine directly. True if handled."""
    if args.command != "engine":
        return False
    if not args.engine_args:
        _print_error(
            "Specify an engine command: export, import, compare, validate, resources"
        )
        sys.exit(1)
    cmd_direct(args.engine_args)
    return True


def _dispatch_passthrough_handlers(args, output_fmt):
    """Offer the command to each dispatcher that may own it, in order.

    True as soon as one takes it; False lets the command router below
    decide.
    """
    if dispatch_menu(args, output_fmt):
        return True

    if dispatch_guide(args, output_fmt):
        return True

    if dispatch_daemon(args, output_fmt):
        return True

    if dispatch_patch(args, output_fmt):
        return True

    if dispatch_config(args, output_fmt):
        return True

    if dispatch_plc_log(args, output_fmt):
        return True
    return False


def _dispatch_pipe_command(args, output_fmt):
    if args.command not in ("raw", "rp"):
        return False
    cmd_rp_command(
        args.cmd_args, timeout=getattr(args, "timeout", 15), output_fmt=output_fmt
    )
    return True


def _dispatch_project_command(args):
    if args.command == "project":
        dispatch_project(args)
    elif args.command == "pou":
        dispatch_pou(args)
    elif args.command == "discover":
        cmd_discover()
    else:
        return False
    return True


def _dispatch_variable_command(args, output_fmt):
    command = args.command
    if command == "read-vars":
        _run_read_vars_command(args, output_fmt)
    elif command == "variable-map":
        _run_variable_map_command(args, output_fmt)
    elif command == "variable-snapshot":
        _run_variable_snapshot_command(args, output_fmt)
    elif command == "variable-restore":
        _run_variable_restore_command(args, output_fmt)
    else:
        return False
    return True


def _run_read_vars_command(args, output_fmt):
    cmd_read_vars(
        names=args.names,
        file_path=args.file,
        timeout=args.timeout,
        output_fmt=output_fmt,
    )


def _run_variable_map_command(args, output_fmt):
    cmd_variable_map(
        path_filter=args.path,
        out=args.out,
        sync_folder=args.sync_folder,
        include_programs=not args.globals_only,
        output_fmt=output_fmt,
    )


def _run_variable_snapshot_command(args, output_fmt):
    cmd_variable_snapshot(
        path_filter=args.path,
        out=args.out,
        sync_folder=args.sync_folder,
        include_programs=not args.globals_only,
        timeout=args.timeout,
        output_fmt=output_fmt,
    )


def _run_variable_restore_command(args, output_fmt):
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


def _dispatch_visu_command(args):
    """Run `cts visu`; turn its command errors into diagnostics and status."""
    if args.command != "visu":
        return False
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
    return True


def _run_analyze_command(args):
    from cds_static_analyzer import cli as analyze_cli

    code = analyze_cli.dispatch_analyze(args)
    if code:
        sys.exit(code)


def _run_verify_command(args, output_fmt):
    from cds_cli.verify import run_verify

    code = run_verify(args, output_fmt)
    if code:
        sys.exit(code)


def _run_headless_crc_command(args):
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


def _run_ui_command(args):
    from cds_text_sync.ui import launch

    code = launch(getattr(args, "workspace", ""))
    if code:
        sys.exit(code)


def _run_fsm_command(args):
    from cds_text_sync.fsm.cli import dispatch_fsm

    code = dispatch_fsm(args)
    if code:
        sys.exit(code)


def _run_visu_lint_command(args):
    from visu_lint.cli import cmd_visu_lint

    code = cmd_visu_lint(args)
    if code:
        sys.exit(code)


def _run_docs_command(args):
    """`cts docs`: validate/check/daemon submodes, else generate a bundle."""
    from cds_text_sync.docgen import generate_docs

    workspace = getattr(args, "workspace", "") or "."
    if getattr(args, "validate", False):
        _run_docs_validate(args, workspace)
        return
    if getattr(args, "check", False):
        _run_docs_check(args, workspace)
        return
    if getattr(args, "daemon", False):
        workspace = _run_docs_daemon(args, workspace)

    result = generate_docs(
        workspace,
        library_path=getattr(args, "library_path", "") or None,
        output=getattr(args, "docs_output", "") or None,
    )
    print(result["output"])


def _run_docs_validate(args, workspace):
    from cds_text_sync.docgen import _resolve_doc_paths, validate_bundle

    output = getattr(args, "docs_output", "") or None
    if output is None:
        _project_view, output_path = _resolve_doc_paths(workspace)
        output = str(output_path)
    diagnostics = validate_bundle(output)
    result = {"ok": not any(item.get("severity") == "error" for item in diagnostics),
              "diagnostics": diagnostics}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["ok"]:
        sys.exit(1)


def _run_docs_check(args, workspace):
    from cds_text_sync.docgen import check_docs

    result = check_docs(workspace, output=getattr(args, "docs_output", "") or None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("exit_code"):
        sys.exit(result["exit_code"])


def _run_docs_daemon(args, workspace):
    """Ask the daemon to generate docs; returns the workspace to use."""
    try:
        resp = send_command_reverse("generate_docs", {}, timeout=args.timeout)
    except RuntimeError as e:
        _print_error("Reverse pipe error: {0}".format(e))
        _print_daemon_unreachable()
        sys.exit(1)

    if not wire.response_ok(resp):
        _print_rp_error(resp, "generate_docs")
        sys.exit(1)
    return resp.get("data", {}).get("sync_folder") or workspace


def _dispatch_lazy_command(args, output_fmt):
    """Route the commands whose modules are imported only when they run."""
    command = args.command
    if command == "analyze":
        _run_analyze_command(args)
    elif command == "verify":
        _run_verify_command(args, output_fmt)
    elif command == "plc-crc-headless":
        _run_headless_crc_command(args)
    elif command == "ui":
        _run_ui_command(args)
    elif command == "fsm":
        _run_fsm_command(args)
    elif command == "docs":
        _run_docs_command(args)
    elif command == "visu-lint":
        _run_visu_lint_command(args)
    else:
        return False
    return True


def _dispatch_command(args, output_fmt, parser):
    """Route a parsed command to its stage; unknown commands print help."""
    if _dispatch_pipe_command(args, output_fmt):
        return
    if _dispatch_project_command(args):
        return
    if _dispatch_variable_command(args, output_fmt):
        return
    if dispatch_new_object(args, output_fmt):
        return
    if dispatch_snapshooter(args, output_fmt):
        return
    if _dispatch_visu_command(args):
        return
    if _dispatch_lazy_command(args, output_fmt):
        return
    parser.print_help()


#: Flags defined only on the top-level parser.  Deliberately excludes
#: ``--output``: subcommands reuse that name for their own option (``cts docs
#: --output DIR`` is a folder), so it is not unambiguous after a command.
_TOP_LEVEL_ONLY_FLAGS = ("--pretty", "-p", "--target", "--expect-project")


def _reject_misplaced_global_flags(extra, parser):
    """A global flag after the command is a clear error, not a stray token.

    ``cts status --pretty`` is the mistake the epilog warns about, and the
    default argparse wording ("unrecognized arguments: --pretty") never says
    where the flag belongs.  A genuinely unknown token still gets argparse's
    own error.
    """
    misplaced = [
        token for token in extra if token.split("=", 1)[0] in _TOP_LEVEL_ONLY_FLAGS
    ]
    if not misplaced:
        parser.error("unrecognized arguments: {0}".format(" ".join(extra)))
    command = next(
        (token for token in sys.argv[1:] if not token.startswith("-")), "<command>"
    )
    _print_error(
        "{0} is a global flag: it goes BEFORE the command, not after. "
        "Try: cts {1} {2}".format(" ".join(misplaced), " ".join(misplaced), command)
    )
    sys.exit(2)


def main():
    parser = build_parser()

    pre_args = _parse_leading_flags()
    if pre_args.help or len(sys.argv) == 1:
        _print_help_and_exit(parser, pre_args)

    args, extra = parser.parse_known_args()
    if extra:
        _reject_misplaced_global_flags(extra, parser)

    _validate_target(args)

    configure(target=args.target, expect_project=args.expect_project)

    output_fmt = _output_format(args)

    try:
        if _dispatch_engine(args):
            return
        if _dispatch_passthrough_handlers(args, output_fmt):
            return
        _dispatch_command(args, output_fmt, parser)

    except TargetError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(2)



if __name__ == "__main__":
    main()
