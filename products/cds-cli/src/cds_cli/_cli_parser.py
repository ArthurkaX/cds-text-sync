"""
_cli_parser.py - Argparse construction for the cds-text-sync CLI.

Exports build_parser().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cds_text_sync import __version__
from cds_cli.parsers._common import add_daemon_parser
from cds_cli.parsers.analyze import register as register_analyze
from cds_cli.parsers.utility import register as register_utility
from cds_cli.parsers.patch import register as register_patch
from cds_cli.parsers.project import register as register_project
from cds_cli.parsers.variables import register as register_variables
from cds_cli.parsers.visu import register as register_visu


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
  There is no override flag: import is refused while the IDE is online because
  an offline project patch applied online can silently create nothing.
  If the preflight still reports online after disconnect, end the online
  session in the CODESYS IDE itself, confirm with cts status, then import.

Connection state:
  cts ping and cts status include cached PLC state:
    connected, online, running, application_state, application
  They do not auto-connect to the PLC. If the daemon has not seen an online
  session yet, plc.known is false.

Timeouts:
  Commands that talk to the CODESYS daemon accept --timeout SECONDS.
  All daemon operations calculate their default timeout from the number of ST
  blocks counted once by the daemon at startup; pass --timeout explicitly to
  override that calculation.

Examples:
  cts ping
  cts status
  cts export
  cts compare
  cts import --dry-run
  cts build
  cts connect --ip 192.0.2.10
  cts plc-crc --build
  cts test --file arithmetic.json --timeout 120
  cts raw application_tree --flat --output C:\\Temp\\vars.json --timeout 120
  cts engine validate --project-root ./MyProject
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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

    # -- primary sync --------------------------------------------------------
    add_daemon_parser(subparsers, "ping", "Daemon liveness check with cached PLC state", None)
    add_daemon_parser(subparsers, "status", "Show daemon, project, sync-folder, and PLC state", None)
    # Sync timeouts are sized for real projects, not demo ones. A 70 MB
    # snapshot takes ~1 min to export and each engine pass reads it again, so
    # import routinely needs 2-3 min end to end. Timing out early does not stop
    # the daemon -- it only hides the result -- so these ceilings are generous.
    add_daemon_parser(subparsers, "export", "IDE -> disk: refresh project-view/", None)
    add_daemon_parser(subparsers, "compare", "IDE vs disk: compare against project-view/", None)
    p_import = add_daemon_parser(
        subparsers, "import", "disk -> IDE: apply project-view/ changes", None
    )
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what import would change without applying (runs compare)",
    )
    p_import.add_argument(
        "--save",
        action="store_true",
        help=(
            "Save the CODESYS project after a successful import. Off by "
            "default: saving also commits everything else open in the IDE, so "
            "it stays your call. Without it the import lives only in memory "
            "until you save in the IDE."
        ),
    )
    p_import.add_argument(
        "--no-refresh",
        dest="no_refresh",
        action="store_true",
        help=(
            "Do not re-baseline project-view/ and manifest.json from the IDE "
            "after a successful import. Without the refresh, compare keeps "
            "reporting the changes you just imported."
        ),
    )

    # -- build / PLC lifecycle ---------------------------------------------
    p_build = subparsers.add_parser(
        "build", help="Compile the active CODESYS application"
    )
    p_build.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Timeout in seconds. By default it is calculated by the daemon "
            "from ST blocks counted at its startup."
        ),
    )
    p_connect = add_daemon_parser(subparsers, "connect", "Login/connect to PLC", None)
    p_connect.add_argument("--ip", default="", help="PLC IP address")
    p_connect.add_argument(
        "--gateway", default="Gateway-1", help="Gateway name (default: Gateway-1)"
    )
    add_daemon_parser(subparsers, "disconnect", "Logout from PLC", None)
    p_download = add_daemon_parser(subparsers, "download", "Force full download to PLC", None)
    p_download.add_argument(
        "--start",
        choices=["0", "1"],
        default=None,
        help="Start after download: 1 yes, 0 no",
    )
    add_daemon_parser(subparsers, "start", "Start PLC application", None)
    add_daemon_parser(subparsers, "stop", "Stop PLC application", None)
    add_daemon_parser(subparsers, "app-state", "Show application online state", None)
    p_crc = add_daemon_parser(subparsers, "plc-crc", "Compare PLC CRC with local build output", None)
    p_crc.add_argument(
        "--build",
        action="store_true",
        help="Build the project first, then compare CRCs",
    )

    # -- variables ----------------------------------------------------------
    p_read = add_daemon_parser(subparsers, "read", "Read one PLC variable/expression", None)
    p_read.add_argument("name", help="Variable/expression name")
    p_write = add_daemon_parser(subparsers, "write", "Write one PLC variable/expression", None)
    p_write.add_argument("name", help="Variable/expression name")
    p_write.add_argument("value", help="Value to write")

    # -- tests --------------------------------------------------------------
    p_test = add_daemon_parser(
        subparsers,
        "test",
        "Run JSON test plans from .test/ (see TEST_FORMAT.md)",
        None,
    )
    p_test.add_argument(
        "--file", default="", help="Test plan file (relative to .test/)"
    )

    # -- project/object tools ----------------------------------------------
    add_daemon_parser(subparsers, "project-info", "Show open project metadata", None)
    p_ptree = add_daemon_parser(subparsers, "project-tree", "Show CODESYS project tree", None)
    p_ptree.add_argument(
        "--depth", type=int, default=0, help="Tree depth, 0 = unlimited"
    )
    p_robj = add_daemon_parser(
        subparsers,
        "read-object",
        "Read one project object by name/path/GUID (prefer --name)",
        None,
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
    p_upou = add_daemon_parser(subparsers, "update-pou", "Update one POU from an .st file", None)
    p_upou.add_argument("--name", required=True, help="Object name")
    p_upou.add_argument(
        "--st-path", dest="st_path", required=True, help="Path to .st file"
    )
    p_upou.add_argument(
        "--app", default="", help="Application name (default: active application)"
    )
    p_dpou = add_daemon_parser(subparsers, "delete-pou", "Delete a POU/Function/FunctionBlock", None)
    p_dpou.add_argument("name", help="Object name")
    p_dpou.add_argument(
        "--app", default="", help="Application name (default: active application)"
    )
    p_log = add_daemon_parser(subparsers, "read-log", "Read CODESYS IDE messages", None)
    p_log.add_argument("--last", default="", help="Maximum messages to read")
    p_log.add_argument("--clear", action="store_true", help="Clear log after read")
    add_daemon_parser(subparsers, "permissions", "Show daemon permissions", None)

    # -- raw / engine / local utility commands -----------------------------
    register_utility(subparsers)

    # -- project and POU commands ------------------------------------------
    register_project(subparsers)

    # -- patch subcommand (compare -> shippable text files) ----------------
    register_patch(subparsers)

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

    # -- variable commands --------------------------------------------------
    register_variables(subparsers)

    # -- visu subcommand (offline) ------------------------------------------
    register_visu(subparsers)

    # -- analyze subcommand (offline static analysis) ----------------------
    register_analyze(subparsers)

    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if action.help is not argparse.SUPPRESS
    ]

    return parser
