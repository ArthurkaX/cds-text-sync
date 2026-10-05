"""Argument registration for PLC value presets (``cts snapshooter``)."""

import argparse

from cds_cli.parsers._common import add_timeout

# take/diff/restore read every selected leaf, and the first call on a big
# project also exports .dump/IDE.xml and builds variable_tree.json through the
# CPython engine -- the same work that routinely needs 2-3 minutes at import.
# The daemon's startup timeout profile is sized for a single command, which is
# too tight here, so the default carries the margin.
DEFAULT_TIMEOUT = 300

# The root help. Kept out of register() so the prose cannot crowd the wiring.
_DESCRIPTION = (
    "Drive the Project_snapshooter backend without the CODESYS dialog.\n"
    "\n"
    "Unlike variable-snapshot/variable-restore (CSV via the offline engine),\n"
    "snapshooter works with the dialog's own JSON preset format: a document of\n"
    "{path, type, value, read_ok} entries with a meta block, saved by take and\n"
    "read back by diff/restore. It needs a project open in the IDE.\n"
    "\n"
    "Actions and the online session they need:\n"
    "  tree      list leaf variables (path, type), optionally by prefix\n"
    "            no PLC session: reads the exported declarations only\n"
    "  take      read the selected variables into a preset document\n"
    "  diff      compare a preset against the live PLC (never writes)\n"
    "  restore   validate a preset, writing only with --apply\n"
    "            take/diff/restore all read live values, so they need an\n"
    "            existing online session: cts connect, or log in in the\n"
    "            CODESYS UI (the daemon adopts a session but never logs in\n"
    "            itself). Without one they answer \"Not connected\".\n"
    "  ui-check  build the dialog without showing it, drive a scripted run\n"
    "            the form itself needs no online session; its save, diff and\n"
    "            restore steps read live values, so without one they are\n"
    "            reported as failed steps (all_steps_ok=false)\n"
    "\n"
    "Timeout: every action defaults to --timeout 300. The first call on a\n"
    "project also exports .dump/IDE.xml and builds\n"
    ".dump/snapshots/variable_tree.json through the CPython engine; on a\n"
    "project with tens of thousands of leaves that alone can exceed a minute.\n"
    "\n"
    "Output: one JSON object per action (--pretty for a text rendering).\n"
    "  tree       {action, app, path, count, leaves[{path,type}]}\n"
    "  take       {action, app, label, count, document{meta,variables}, saved_to?}\n"
    "  diff       {action, app, count,\n"
    "              report{same,missing,type_changed,value_changed}}\n"
    "  restore    {action, app, applied,\n"
    "              result{written,skipped,warnings,would_write,details}}\n"
    "  ui-check   {action, report{ok,failed_steps,all_steps_ok,steps,\n"
    "              windows,files,checked_leaves,leaf_count,parents}}\n"
    "\n"
    "Diagnostics: <sync-folder>/.dump/snapshooter.log gets lines only while\n"
    "the project option \"Save detailed engine logs in .dump\" (verbose_logging)\n"
    "is enabled -- with it off the file is empty or absent. When no sync folder\n"
    "resolves, the lines go to the system temp directory instead."
)

_EPILOG = (
    "Examples:\n"
    "  cts snapshooter tree --path GVL_HMI --pretty\n"
    "  cts snapshooter tree --path 'GVL_HMI.'          # only that GVL's own leaves\n"
    "  cts snapshooter take --paths-file selected.txt --label speed --out preset.json\n"
    "  cts snapshooter take --path GVL_HMI.xStart --path GVL_HMI.xStop --out start.json\n"
    "  cts snapshooter diff --input presets/before.json\n"
    "  cts snapshooter restore --input preset.json            # dry-run\n"
    "  cts snapshooter restore --input preset.json --apply\n"
    "  cts snapshooter ui-check\n"
    "\n"
    "--path on tree is a PREFIX match on the leaf path and is case-sensitive\n"
    "(CODESYS paths are). It is a plain string prefix, NOT a segment boundary:\n"
    "--path GVL matches GVL.a AND GVL_HMI.x. To pin one GVL, include the dot:\n"
    "--path 'GVL.'. It is not a glob -- no * or ? is expanded.\n"
    "--path on take is an exact path and is repeatable.\n"
    "\n"
    "File paths: --out and --input may be relative and are read from the\n"
    "directory you ran cts in (they are made absolute before they are sent:\n"
    "the daemon opens them inside CODESYS, whose working directory is the IDE\n"
    "installation). --paths-file is opened by cts itself, so it is relative to\n"
    "the same place. A relative --out/--input reaching the daemon is refused\n"
    "with \"path must be absolute\"."
)


def register(subparsers):
    parser = subparsers.add_parser(
        "snapshooter",
        help="PLC value presets (JSON): tree/take/diff/restore, or run the dialog headlessly",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = parser.add_subparsers(dest="snap_action", required=True, metavar="action")
    _add_tree(actions)
    _add_take(actions)
    _add_diff(actions)
    _add_restore(actions)
    _add_ui_check(actions)


def _add_tree(actions):
    tree = actions.add_parser(
        "tree",
        help="List leaf variables (path, type)",
        description="Build the Snapshooter variable tree and return its leaf variables. No PLC read.",
    )
    tree.add_argument(
        "--path",
        default="",
        help=(
            "Only variables whose path starts with this prefix (case-sensitive, "
            "a plain string prefix and not a segment boundary: GVL also matches "
            "GVL_HMI.x; use 'GVL.' to pin one GVL)"
        ),
    )
    tree.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Rebuild the variable tree instead of reusing the cache. The tree "
            "is rebuilt automatically after any project edit the daemon "
            "performs (import, update-pou, delete-pou); use --refresh to force "
            "it after an edit made directly in the CODESYS IDE"
        ),
    )
    add_timeout(tree, DEFAULT_TIMEOUT)


def _add_take(actions):
    take = actions.add_parser(
        "take",
        help="Read the selected variables into a JSON preset",
        description=(
            "Read live PLC values for the selected leaves (all leaves when none "
            "is given) and return a preset document. Needs an online session; "
            "without one the daemon answers \"Not connected\"."
        ),
    )
    take.add_argument(
        "--path",
        dest="path",
        action="append",
        default=[],
        metavar="PATH",
        help="An exact variable path (repeatable; an unknown one is attempted anyway)",
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


def _add_diff(actions):
    diff = actions.add_parser(
        "diff",
        help="Compare a preset against the live PLC",
        description=(
            "Read the preset's paths from the live PLC and report "
            "same/missing/type-changed/value-changed. Needs an online session; "
            "without one the daemon answers \"Not connected\". The read never "
            "writes anything to the PLC."
        ),
    )
    diff.add_argument("--input", default="", required=True, help="Preset .json produced by take")
    add_timeout(diff, DEFAULT_TIMEOUT)


def _add_restore(actions):
    restore = actions.add_parser(
        "restore",
        help="Validate a preset and (with --apply) write it back",
        description=(
            "Dry-run unless --apply: read the preset's paths from the live PLC, "
            "report what would be written, then write only if asked. Both modes "
            "read live values, so both need an online session.\n\n"
            "WARNING -- the offline/online gates contradict each other: "
            "writing is refused while a session is cached (\"Snapshot import is "
            "disabled while CODESYS is online\", project_snapshooter."
            "ensure_snapshot_import_allowed) and reading is refused without "
            "one (\"Not connected\", ide_online_helpers.require_online_session). "
            "--apply therefore only gets through in the narrow window where "
            "the IDE is online but the daemon has not cached the session yet. "
            "Not repaired here; see the command guide for how to probe it "
            "without changing PLC state."
        ),
    )
    restore.add_argument("--input", default="", required=True, help="Preset .json produced by take")
    restore.add_argument(
        "--apply",
        action="store_true",
        help="Actually write matching variables to the PLC (default: dry-run)",
    )
    add_timeout(restore, DEFAULT_TIMEOUT)


def _add_ui_check(actions):
    ui_check = actions.add_parser(
        "ui-check",
        help="Build the dialog without showing it and drive a scripted run",
        description=(
            "Headless smoke test of the Snapshooter window: build the form in "
            "memory (never shown), substitute recording MessageBox/file "
            "dialogs, then run the default scenario -- check the first leaf, "
            "search next/prev, save, load, diff, restore (dry-run). Returns "
            "which windows were shown, per-step exceptions, the checked and "
            "parent state, and failed_steps/all_steps_ok. Needs a session "
            "where WinForms can be created.\n\n"
            "What it does NOT check: the form is never shown, so window "
            "layout, fonts, resizing, focus, scrolling and mouse behaviour are "
            "not exercised; MessageBox and the file dialogs are answering "
            "fakes, so their real appearance and the values a person would "
            "type are not covered; and a step that fails is reported, not "
            "treated as a command failure (exit code stays 0).\n\n"
            "There is no --out: the Save and Load steps use a temporary "
            "preset the daemon picks (report.preset_file, under its TEMP "
            "directory), so this action cannot be pointed at your own preset."
        ),
    )
    ui_check.add_argument("--app", default="Application", help="Application name (default: Application)")
    ui_check.add_argument(
        "--script",
        default="",
        help="Comma-separated step names to run instead of the default scenario",
    )
    add_timeout(ui_check, 120)


__all__ = ["register"]
