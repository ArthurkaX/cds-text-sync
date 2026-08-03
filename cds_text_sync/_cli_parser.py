"""
_cli_parser.py - Argparse construction for the cds-text-sync CLI.

Exports build_parser().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .install_menu import add_menu_arguments


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

    def add_timeout(p, default):
        p.add_argument(
            "--timeout",
            type=float,
            default=default,
            help=f"Timeout in seconds (default: {default})",
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

    # -- local desktop UI ---------------------------------------------------
    p_ui = subparsers.add_parser(
        "ui",
        help="Open the local static-analysis desktop interface",
        description=(
            "Open the offline static-analysis interface. Requires the optional "
            "UI dependency: pip install 'cds-text-sync[ui]'."
        ),
    )
    p_ui.add_argument(
        "--workspace",
        default="",
        help="Initial sync folder containing project-view/ (optional)",
    )

    p_visu_lint = subparsers.add_parser(
        "visu-lint",
        help="Machine-only validation of generated visualization XML",
        description="JSON-only validator for the SVG-to-XML generation pipeline.",
    )
    p_visu_lint.add_argument("--xml", required=True, help="Generated visualization XML file")

    # -- local install commands (no daemon, no CODESYS) ----------------------
    p_menu = subparsers.add_parser(
        "install-menu",
        help="Write the CODESYS Tools>Scripting stubs into ScriptDir",
        description=(
            "Generate the Project_*.py menu stubs in <ScriptDir>/cds-text-sync, "
            "pointed at this installation. Only the public entry points are "
            "written, so the IDE menu stays clean."
        ),
    )
    add_menu_arguments(p_menu)

    p_where = subparsers.add_parser(
        "where",
        help="Show where the tool and its CODESYS menu stubs live",
        description="Report the install layout: tool folder, ScriptDir, menu status.",
    )
    p_where.add_argument("--body", default="", help=argparse.SUPPRESS)
    p_where.add_argument(
        "--script-dir", dest="script_dir", default="", help=argparse.SUPPRESS
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

  Prefer a semantic class over a colour. class="..." expands through
  cds_text_sync/visu/stylesheet.css (override it with a project-level visu.css):
    surfaces   panel card divider
    type       h1 h2 value label caption   (the whole scale: 22/16/28/12/11)
    emphasis   muted inverse
    status     ok warn alarm
    P&ID       pipe-water metal

  CSS variables (set in a :root block, or use the class above):
    --screen       generated screen background
    --background   style background
    --surface      panel/background fill default
    --panel        sub-panel fill
    --card         inner surface, one step down from panel
    --border       --frame stroke default
    --divider      separator line
    --text         font colour
    --text-muted   muted/secondary font colour
    --primary      accent/highlight
    --secondary    secondary accent
    --success      green/ok
    --warning      orange/caution
    --error        red/alarm
    --water        pipe/fluid
    --water-dim    pipe/fluid outline
    --metal        structural elements

  Color rules for SVG attributes:
    - <text fill="..."> controls font colour (compiles to uint literal)
    - <rect fill="..."> controls background fill
    - <rect stroke="..."> controls frame/border colour
    - <button> and <textfield> colours: SVG fill/stroke controls
      browser preview but is IGNORED by the transpiler. These
      elements inherit the CODESYS project visual style.
      For coloured button-like shapes use plain <rect> + <text>.

  Look before you import:
    cts visu preview --svg screen.svg        # resolved SVG + PNG
    cts visu lint --svg screen.svg [--fix]   # grid, type scale, overflow

  Unsupported in v1: polygon, polyline, image, transform,
    gradients, filters, masks, animation, viewBox scaling,
    Table, ComboBox, TabControl, GroupBox, Checkbox, etc.
""",
    )
    p_visu.add_argument(
        "visu_action",
        choices=[
            "new",
            "create-screen",
            "add",
            "list",
            "check",
            "types",
            "describe",
            "from-svg",
            "to-svg",
            "preview",
            "lint",
            "capture-frame",
        ],
        help="new - scaffold an editable SVG sketch from the seed template\n"
        "create-screen - create a new empty screen\n"
        "add - add an element to a screen\n"
        "list - list elements in a screen\n"
        "check - validate a screen\n"
        "types - list available element types\n"
        "describe - describe a type or element\n"
        "from-svg - compile SVG to CODESYS screen XML\n"
        "to-svg - decompile CODESYS screen XML to SVG\n"
        "preview - render an SVG sketch to a viewable SVG/PNG (resolved colours)\n"
        "lint - check an SVG sketch for layout/typography problems\n"
        "capture-frame - capture a VisuFbFrame instance as golden template + catalog",
    )
    p_visu.add_argument(
        "--sync-folder", default="", help="Sync folder or project-view dir"
    )
    p_visu.add_argument(
        "--name", default="", help="Screen name (for new, create-screen)"
    )
    p_visu.add_argument(
        "--folder",
        default="",
        help="CODESYS folder path e.g. Runtime/PLC Logic/Application/HMI",
    )
    p_visu.add_argument(
        "--width", type=int, default=800, help="Screen width (for new, create-screen)"
    )
    p_visu.add_argument(
        "--height",
        type=int,
        default=480,
        help="Screen height (for new, create-screen)",
    )
    p_visu.add_argument(
        "--start-visu",
        action="store_true",
        help="Set as start visualization (for create-screen)",
    )
    p_visu.add_argument("--screen", default="", help="Screen name or path")
    p_visu.add_argument("--visu", default="", help="Sub-visu name (for capture-frame)")
    p_visu.add_argument("--type", default="", help="Element type (for add, describe)")
    p_visu.add_argument("--x", type=int, help="X position (for add)")
    p_visu.add_argument("--y", type=int, help="Y position (for add)")
    p_visu.add_argument(
        "--w", type=int, help="Width (for add; also overrides --width for new)"
    )
    p_visu.add_argument(
        "--h", type=int, help="Height (for add; also overrides --height for new)"
    )
    p_visu.add_argument(
        "--shape",
        default="",
        help="Shape variant: rectangle|ellipse|rounded|line (for add)",
    )
    p_visu.add_argument(
        "--fill", default="", help="Fill color, 0xAARRGGBB or name (for add)"
    )
    p_visu.add_argument("--frame", default="", help="Frame color (for add)")
    p_visu.add_argument("--corner-radius", type=int, help="Corner radius (for add)")
    p_visu.add_argument("--border-width", type=int, help="Border width (for add)")
    p_visu.add_argument("--angle", type=int, help="Rotation angle (for add)")
    p_visu.add_argument("--tooltip", default="", help="Tooltip text (for add)")
    p_visu.add_argument(
        "--svg", default="", help="SVG file path (for from-svg, preview, lint)"
    )
    p_visu.add_argument(
        "--elem", type=int, help="Element index (for describe --screen --elem)"
    )
    p_visu.add_argument(
        "--theme",
        default="flat-style",
        help=(
            "CODESYS style preset (for from-svg, preview, lint): "
            "flat-style|basic-style|default|white-style|style-2..."
        ),
    )
    p_visu.add_argument(
        "--out",
        default="",
        help="Output path (for new, from-svg, to-svg, preview)",
    )
    p_visu.add_argument(
        "--create-screen",
        action="store_true",
        help="Create a new screen when compiling SVG (for from-svg)",
    )
    p_visu.add_argument(
        "--screen-name", default="", help="Screen name when --create-screen is used"
    )
    p_visu.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Recompile an existing screen from the sketch, keeping its object "
            "Guid (for from-svg --create-screen)"
        ),
    )
    p_visu.add_argument(
        "--gvl",
        default="",
        help="GVL name for auto-generated declarations (e.g. VisuVars)",
    )
    p_visu.add_argument(
        "--gvl-file",
        default="",
        help="Explicit GVL .st file path",
    )
    p_visu.add_argument(
        "--background",
        default="",
        help=(
            "Screen background (for from-svg, preview, lint): "
            "auto (curated neutral, default) | style (the project style's own "
            "background) | #RRGGBB"
        ),
    )
    p_visu.add_argument(
        "--scheme",
        default="",
        choices=["", "light", "dark"],
        help=(
            "Colour scheme (for new, from-svg, preview, lint): light (default) "
            "| dark. 'visu new' records it as data-cds-scheme on the sketch; "
            "elsewhere it overrides that attribute for a single render"
        ),
    )
    p_visu.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip writing the .preview.svg/.png next to the compiled screen (for from-svg)",
    )
    p_visu.add_argument(
        "--no-png",
        action="store_true",
        help="Write only the preview SVG, do not rasterise (for preview)",
    )
    p_visu.add_argument(
        "--grid",
        type=int,
        default=0,
        help="Overlay a grid of this spacing on the preview, in px (for preview)",
    )
    p_visu.add_argument(
        "--fix",
        action="store_true",
        help="Rewrite the mechanically fixable findings in place (for lint)",
    )
    p_visu.add_argument(
        "--strict",
        action="store_true",
        help="Treat any lint finding as fatal (for lint, from-svg)",
    )

    # -- analyze subcommand (offline static analysis) ----------------------
    p_analyze = subparsers.add_parser(
        "analyze",
        help="Static analysis of the exported project-view (offline)",
        description=(
            "Project static analysis over project-view/. Never talks to the "
            "daemon and never reads .dump/. Works fully offline."
        ),
        epilog="""
Subcommands:
  cts analyze [options]                    run the analysis
  cts analyze rules                        list registered rules
  cts analyze explain CTS0001              rule documentation
  cts analyze selftest                     run every rule on its own docs
  cts analyze baseline create|update|check baseline management
  cts analyze triage --apply decisions.json  scriptable triage

Exit codes:
  0 - quality policy passed
  1 - unsuppressed findings at or above --fail-on
  2 - configuration error or analysis cannot start
  3 - incomplete analysis with --incomplete=error
""",
    )

    def add_analyze_common(parser):
        parser.add_argument(
            "--workspace",
            default="",
            help="Sync folder containing project-view/ (default: nearest "
            "ancestor with cts-analyze.toml + project-view)",
        )
        parser.add_argument(
            "--project-view",
            dest="project_view",
            default="",
            help="Explicit project-view directory",
        )
        parser.add_argument(
            "--format",
            choices=["json", "text", "sarif", "md"],
            default="json",
            help="Output format (default: json; --pretty forces text)",
        )
        parser.add_argument(
            "--rule",
            action="append",
            default=[],
            metavar="CTSxxxx",
            help="Restrict analysis to one rule id (repeatable)",
        )
        parser.add_argument(
            "--fail-on",
            choices=["danger", "suspicious", "style"],
            default=None,
            help="Exit 1 when findings at/above this severity exist "
            "(default: suspicious)",
        )
        parser.add_argument(
            "--incomplete",
            choices=["warn", "error", "ignore"],
            default=None,
            help="Policy for incomplete analysis (default: warn; error exits 3)",
        )
        parser.add_argument(
            "--apply",
            default="",
            help="decisions.json path for 'triage --apply'",
        )
        parser.add_argument(
            "--pretty",
            "-p",
            action="store_true",
            help="Shortcut for --format text",
        )

    add_analyze_common(p_analyze)

    # Nested subcommands: run (default, when no subcommand is given),
    # rules, explain, selftest, baseline, triage.
    p_analyze_sub = p_analyze.add_subparsers(
        dest="analyze_action",
        metavar="SUBCOMMAND",
    )

    p_analyze_run = p_analyze_sub.add_parser(
        "run",
        help="Run the analysis (this is also the default without a subcommand)",
    )
    add_analyze_common(p_analyze_run)
    p_analyze_rules = p_analyze_sub.add_parser(
        "rules",
        help="List registered rules",
    )
    add_analyze_common(p_analyze_rules)
    p_analyze_selftest = p_analyze_sub.add_parser(
        "selftest",
        help="Run every rule against its own documentation examples",
    )
    add_analyze_common(p_analyze_selftest)
    p_analyze_explain = p_analyze_sub.add_parser(
        "explain",
        help="Show one rule's documentation",
    )
    add_analyze_common(p_analyze_explain)
    p_analyze_explain.add_argument(
        "rule_id",
        help="Rule id, e.g. CTS0001",
    )
    p_analyze_baseline = p_analyze_sub.add_parser(
        "baseline",
        help="Baseline management",
    )
    add_analyze_common(p_analyze_baseline)
    p_analyze_baseline.add_argument(
        "baseline_action",
        choices=["create", "update", "check"],
        help="create - snapshot current findings\n"
        "update - rewrite the baseline\n"
        "check - report new and stale baseline entries",
    )
    p_analyze_triage = p_analyze_sub.add_parser(
        "triage",
        help="Convert findings into suppress/fix-later decisions",
    )
    add_analyze_common(p_analyze_triage)

    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if action.help is not argparse.SUPPRESS
    ]

    return parser
