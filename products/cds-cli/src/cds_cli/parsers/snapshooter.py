"""Argument registration for PLC value presets (``cts snapshooter``)."""

import argparse

from cds_cli.parsers._common import add_timeout

# take/diff/restore read every selected leaf, and the first call on a big
# project also exports .dump/IDE.xml and builds variable_tree.json through the
# CPython engine -- the same work that routinely needs 2-3 minutes at import.
# The daemon's startup timeout profile is sized for a single command, which is
# too tight here, so the default carries the margin.
DEFAULT_TIMEOUT = 300


def register(subparsers):
    parser = subparsers.add_parser(
        "snapshooter",
        help="PLC value presets (JSON): tree/take/diff/restore",
        description=(
            "Drive the Project_snapshooter backend without the CODESYS dialog.\n\n"
            "Unlike variable-snapshot/variable-restore (CSV via the offline "
            "engine), snapshooter works with the dialog's own JSON preset "
            "format: a document of {path, type, value, read_ok} entries with a "
            "meta block, saved by take and read back by diff/restore. It needs "
            "a project open in the IDE.\n\n"
            "Actions:\n"
            "  tree      list leaf variables (path, type), optionally by prefix\n"
            "  take      read the selected variables into a preset document\n"
            "  diff      compare a preset against the live PLC\n"
            "  restore   validate a preset, writing only with --apply"
        ),
        epilog=(
            "Examples:\n"
            "  cts snapshooter tree --path GVL_HMI --pretty\n"
            "  cts snapshooter take --paths-file selected.txt --label speed --out preset.json\n"
            "  cts snapshooter diff --input preset.json\n"
            "  cts snapshooter restore --input preset.json            # dry-run\n"
            "  cts snapshooter restore --input preset.json --apply"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = parser.add_subparsers(dest="snap_action", required=True, metavar="action")

    tree = actions.add_parser(
        "tree",
        help="List leaf variables (path, type)",
        description="Build the Snapshooter variable tree and return its leaf variables. No PLC read.",
    )
    tree.add_argument("--path", default="", help="Only variables whose path starts with this prefix")
    add_timeout(tree, DEFAULT_TIMEOUT)

    take = actions.add_parser(
        "take",
        help="Read the selected variables into a JSON preset",
        description="Read live PLC values for the selected leaves (all leaves when none is given) and return a preset document.",
    )
    take.add_argument(
        "--path",
        dest="path",
        action="append",
        default=[],
        metavar="PATH",
        help="A variable path to include (repeatable)",
    )
    take.add_argument(
        "--paths-file",
        dest="paths_file",
        default="",
        help="Read paths from a file (one per line, # comments skipped)",
    )
    take.add_argument("--label", default="", help="Preset label stored in the document meta")
    take.add_argument("--out", default="", help="Also save the preset to this .json path")
    add_timeout(take, DEFAULT_TIMEOUT)

    diff = actions.add_parser(
        "diff",
        help="Compare a preset against the live PLC",
        description="Read the preset's paths from the live PLC and report same/missing/type-changed/value-changed.",
    )
    diff.add_argument("--input", default="", required=True, help="Preset .json produced by take")
    add_timeout(diff, DEFAULT_TIMEOUT)

    restore = actions.add_parser(
        "restore",
        help="Validate a preset and (with --apply) write it back",
        description="Dry-run unless --apply: report what would be written, then write only if asked.",
    )
    restore.add_argument("--input", default="", required=True, help="Preset .json produced by take")
    restore.add_argument(
        "--apply",
        action="store_true",
        help="Actually write matching variables to the PLC (default: dry-run)",
    )
    add_timeout(restore, DEFAULT_TIMEOUT)


__all__ = ["register"]
