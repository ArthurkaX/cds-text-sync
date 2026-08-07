"""Argument registration for PLC variable commands."""


def register(subparsers):
    read_vars = subparsers.add_parser(
        "read-vars",
        help="Batch-read multiple PLC variables/expressions",
        description="Read several variables/expressions in one call. Sends a proper JSON list to the daemon.",
    )
    read_vars.add_argument("names", nargs="*", metavar="EXPR", help="Variable/expression names, e.g. GVL.a App.PRG.b")
    read_vars.add_argument("--file", dest="file", default="", help="Read names from a file (one expression per line)")
    read_vars.add_argument("--timeout", type=float, default=30, help="Timeout in seconds (default: 30)")

    variable_map = subparsers.add_parser(
        "variable-map",
        help="Build an offline variable map (CSV) from project-view",
        description="Parse project-view/*.st declarations and expand to readable scalar leaves. No PLC connection required.",
    )
    variable_map.add_argument("--path", default="", help="Subtree filter, e.g. GVL_HMI or Application.GVL_HMI")
    variable_map.add_argument("--out", default="", help="Output CSV path (default: <sync>/variable-map.csv)")
    variable_map.add_argument("--sync-folder", default="", help="Sync folder or project-view dir (default: from daemon)")
    variable_map.add_argument("--globals-only", action="store_true", help="Only GVL globals; exclude Program-local variables")

    snapshot = subparsers.add_parser(
        "variable-snapshot",
        help="Snapshot current online values for mapped leaves (CSV)",
        description="Read live PLC values for every mapped scalar leaf. Requires an online/logged-in daemon.",
    )
    snapshot.add_argument("--path", default="", help="Subtree filter")
    snapshot.add_argument("--out", default="", help="Output CSV (default: <sync>/variable-snapshot.csv)")
    snapshot.add_argument("--sync-folder", default="", help="Sync/project-view dir")
    snapshot.add_argument("--globals-only", action="store_true", help="Only GVL globals; exclude Program-local")
    snapshot.add_argument("--timeout", type=float, default=120, help="Per-batch daemon timeout (default: 120)")

    restore = subparsers.add_parser(
        "variable-restore",
        help="Restore PLC values from a snapshot CSV (dry-run unless --apply)",
        description="Write values from a variable-snapshot CSV back to the PLC.",
    )
    restore.add_argument("--input", default="", required=True, help="Snapshot CSV produced by variable-snapshot")
    restore.add_argument("--report", default="", help="Report CSV (default: <sync>/variable-restore-report.csv)")
    restore.add_argument("--path", default="", help="Subtree filter")
    restore.add_argument("--apply", action="store_true", help="Actually write values (default: dry-run)")
    restore.add_argument("--force", action="store_true", help="Restore even rows with read_ok!=true or empty value")
    restore.add_argument("--sync-folder", default="", help="Sync/project-view dir")
    restore.add_argument("--timeout", type=float, default=120, help="Per-batch daemon timeout (default: 120)")


__all__ = ["register"]
