"""Argument registration for local and escape-hatch commands."""

import argparse

from cds_text_sync.install_menu import add_menu_arguments


def register(subparsers):
    raw = subparsers.add_parser(
        "raw",
        help="Send a daemon method directly",
        description=(
            "Compatibility/debug escape hatch for daemon methods. "
            "Useful for diagnostic parameters and timeout=SECONDS. "
            "Run 'cts raw help' for the method list."
        ),
    )
    raw.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="<method> [--key value ...]")
    raw.add_argument("--timeout", type=float, default=15, help="Timeout in seconds waiting for IDE response (default: 15)")

    engine = subparsers.add_parser(
        "engine",
        help="Run engine_cli.py directly without CODESYS",
        description="Direct offline engine access. Does not talk to the daemon.",
    )
    engine.add_argument("engine_args", nargs=argparse.REMAINDER, metavar="<export|import|compare|validate|resources> ...")
    engine.add_argument("--timeout", type=float, default=None, help="Accepted for consistency; ignored by the offline engine")

    ui = subparsers.add_parser(
        "ui",
        help="Open the local static-analysis desktop interface",
        description="Open the offline static-analysis interface. Requires the optional UI dependency: pip install 'cds-text-sync[ui]'.",
    )
    ui.add_argument("--workspace", default="", help="Initial sync folder containing project-view/ (optional)")

    visu_lint = subparsers.add_parser(
        "visu-lint",
        help="Validate a COMPILED visualization .xml (not the SVG: that is `cts visu lint`)",
        description="JSON-only validator for the SVG-to-XML generation pipeline. "
        "This checks the compiled CODESYS XML. To check an SVG sketch's layout "
        "and typography before compiling, use `cts visu lint --svg` instead.",
    )
    visu_lint.add_argument("--xml", required=True, help="Generated visualization XML file")

    menu = subparsers.add_parser(
        "install-menu",
        help="Write the CODESYS Tools>Scripting stubs into ScriptDir",
        description="Generate the Project_*.py menu stubs in <ScriptDir>/cds-text-sync, pointed at this installation. Only the public entry points are written, so the IDE menu stays clean.",
    )
    add_menu_arguments(menu)

    where = subparsers.add_parser(
        "where",
        help="Show where the tool and its CODESYS menu stubs live",
        description="Report the install layout: tool folder, ScriptDir, menu status.",
    )
    where.add_argument("--body", default="", help=argparse.SUPPRESS)
    where.add_argument("--script-dir", dest="script_dir", default="", help=argparse.SUPPRESS)

    guide = subparsers.add_parser(
        "guide",
        help="Read the shipped operating guides (workflow, commands, visu-svg)",
        description=(
            "Print the operating guides that ship inside this package, so they "
            "always match the installed CLI version. Topics: workflow (how to "
            "operate cts), commands (which command for which job), visu-svg "
            "(authoring HMI sketches). With no topic, list the topics and the "
            "guide directory. Text output prints the guide verbatim; the default "
            "JSON wraps it as {\"topic\", \"path\", \"text\"}. Needs no daemon or IDE."
        ),
        epilog=(
            "Examples:\n"
            "  cts guide\n"
            "  cts guide workflow --pretty\n"
            "  cts guide visu-svg --file examples/pid-schematic.svg"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    guide.add_argument(
        "topic",
        nargs="?",
        default="",
        help="workflow | commands | visu-svg (omit to list the topics)",
    )
    guide.add_argument(
        "--file",
        default="",
        help=(
            "with a topic, print one of its extra files instead, e.g. "
            "examples/pid-schematic.svg (visu-svg)"
        ),
    )


__all__ = ["register"]
