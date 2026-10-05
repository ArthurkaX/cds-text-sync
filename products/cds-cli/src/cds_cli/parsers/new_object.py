"""Argument registration for ``cts new`` -- create a project-view object."""

import argparse

_DESCRIPTION = (
    "Create a GVL, POU or DUT in the project view, offline.\n"
    "\n"
    "This writes the object's ``.st`` into project-view/ and stops there. It\n"
    "does not touch the IDE and does not need a daemon: the file is the\n"
    "authored copy, and the usual order carries it into CODESYS.\n"
    "\n"
    "  cts new gvl GVL_HMI --text 'xStart : BOOL;'\n"
    "  cts compare      # reports the new object as added\n"
    "  cts import       # CODESYS creates it (CreateTextObjects)\n"
    "  # make it reachable, then download -- see the warning below\n"
    "\n"
    "No manifest entry is written, and none is needed: an unmanaged ``.st``\n"
    "under the view root is discovered by the reader from its own declaration\n"
    "keyword (VAR_GLOBAL / PROGRAM / FUNCTION_BLOCK / FUNCTION / TYPE).\n"
    "\n"
    "WARNING -- a new object reaches the PLC only if BOTH hold:\n"
    "  1. it is reachable from a block the task calls. CODESYS loads only\n"
    "     objects in the task's call tree, so an object nothing references is\n"
    "     compiled out. For an I/O GVL, mention it in MAIN or another called\n"
    "     block, e.g. add the line:   GVL_HMI.xStart;\n"
    "     or assign it:               xLocal := GVL_HMI.xStart;\n"
    "  2. a FULL download runs after that. `cts download` is the full download;\n"
    "     an import or an online change leaves the symbol table stale.\n"
    "Without both, every read of the object fails with\n"
    '  "Invalid expression: \'GVL.x\' is not exported to the online application.\n'
    '   It may be a struct/array, not declared as a symbol, or not compiled\n'
    '   into the PLC."\n'
    "\n"
    "What can be created (and what cannot):\n"
    "  gvl    Global variable list                    yes\n"
    "  pou    PROGRAM, FUNCTION, FUNCTION_BLOCK       yes\n"
    "  dut    STRUCT, UNION, ENUM, ALIAS              yes\n"
    "  --     methods, actions, properties           use the <POU>.<Member>.st\n"
    "         naming and --parent <the POU> option    file convention instead\n"
    "  --     SFC/FBD/LD (graphical) POUs            no -- textual only\n"
    "  --     visualizations, devices, tasks, alarms no -- export them from\n"
    "         the IDE; the created object is always a textual one\n"
)

_EPILOG = (
    "Examples:\n"
    "  cts new gvl GVL_HMI --text $'xStart : BOOL;\\nxStop : BOOL;'\n"
    "  cts new gvl GVL_HMI --text-file decls.txt --parent 'Runtime/PLC Logic/Application'\n"
    "  cts new pou PRG_Control --kind program\n"
    "  cts new pou FC_Scale --kind function --return-type REAL --text 'FC_Scale := 1.0;'\n"
    "  cts new pou FB_Motor --kind function-block\n"
    "  cts new dut ST_Motor --kind struct --text $'speed : REAL;\\nstate : INT;'\n"
    "  cts new dut E_State --kind enum --text $'Idle := 0,\\nRun := 1'\n"
    "  cts new dut T_Count --kind alias --base-type UINT\n"
    "\n"
    "--parent is a project-tree path under project-view/, the same spelling\n"
    "``cts visu --folder`` takes. It defaults to the active application folder\n"
    "recovered from .dump/manifest.json (the entry path through its\n"
    "'Application' segment), so the object lands where its siblings live.\n"
    "\n"
    "--text is the body: for a GVL the inside of the VAR_GLOBAL block (or the\n"
    "whole block, which is passed through), for a POU the statements below the\n"
    "'// --- implementation ---' marker, for a DUT the member list between the\n"
    "STRUCT/UNION/ENUM brackets. --text-file reads the same from a file.\n"
    "\n"
    "--text is used verbatim: there is no escape processing. A literal \\n\n"
    "inside single quotes stays a backslash-n, not a line break -- use bash\n"
    "ANSI-C quoting ($'...') or --text-file when the body is multi-line.\n"
    "\n"
    "An existing name is refused rather than overwritten: CODESYS answers a\n"
    "duplicate create with a modal dialog the daemon cannot dismiss, so the\n"
    "check happens here first, against both the files on disk and the\n"
    "manifest."
)


def register(subparsers):
    parser = subparsers.add_parser(
        "new",
        help="Create a GVL/POU/DUT in the project view (offline)",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = parser.add_subparsers(dest="new_kind", required=True, metavar="kind")
    _add_gvl(actions)
    _add_pou(actions)
    _add_dut(actions)


def _add_common(parser):
    """Options every ``cts new`` subcommand shares."""
    parser.add_argument("name", metavar="NAME", help="Object name (an IEC identifier)")
    parser.add_argument(
        "--parent",
        default="",
        help="Project-tree folder for the object (default: the active application)",
    )
    parser.add_argument("--text", default="", help="Body text (see the command help)")
    parser.add_argument(
        "--text-file",
        dest="text_file",
        default="",
        help="Read the body from this file instead of --text",
    )
    parser.add_argument(
        "--sync-folder",
        default="",
        help="Sync folder or project-view dir (default: search upwards from cwd)",
    )
    return parser


def _add_gvl(actions):
    parser = _add_common(
        actions.add_parser(
            "gvl",
            help="Create a global variable list",
            description=(
                "Write <view>/<parent>/<Name>.st with a VAR_GLOBAL block. "
                "--text is the declaration list (or a whole VAR_GLOBAL block)."
            ),
        )
    )
    return parser


def _add_pou(actions):
    parser = _add_common(
        actions.add_parser(
            "pou",
            help="Create a PROGRAM, FUNCTION or FUNCTION_BLOCK",
            description=(
                "Write <view>/<parent>/<Name>.st with the POU header, an empty "
                "VAR block, the '// --- implementation ---' marker and --text "
                "below it."
            ),
        )
    )
    parser.add_argument(
        "--kind",
        dest="pou_kind",
        required=True,
        choices=["program", "function", "function-block"],
        help="Which POU keyword the header uses",
    )
    _add_pou_type_options(parser)
    return parser


def _add_pou_type_options(parser):
    parser.add_argument(
        "--return-type",
        dest="return_type",
        default="",
        help="Return type for --kind function (default: BOOL); ignored otherwise",
    )
    parser.add_argument(
        "--language",
        default="st",
        help="Only 'st' is supported: the import path creates textual objects",
    )


def _add_dut(actions):
    parser = _add_common(
        actions.add_parser(
            "dut",
            help="Create a STRUCT, UNION, ENUM or ALIAS",
            description=(
                "Write <view>/<parent>/<Name>.st with a TYPE ... END_TYPE "
                "declaration. --text is the member list."
            ),
        )
    )
    parser.add_argument(
        "--kind",
        dest="dut_kind",
        required=True,
        choices=["struct", "enum", "union", "alias"],
        help="Which DUT shape the declaration takes",
    )
    parser.add_argument(
        "--base-type",
        dest="base_type",
        default="",
        help="Target type for --kind alias, e.g. UINT (required for an alias)",
    )
    return parser


__all__ = ["register"]
