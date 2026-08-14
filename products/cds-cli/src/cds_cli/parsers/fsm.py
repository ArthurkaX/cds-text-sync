"""Argument registration for the offline FSM command."""


def register(subparsers):
    parser = subparsers.add_parser(
        "fsm",
        help="Scan an exported workspace for FSMs and render them offline",
        description=(
            "Offline FSM search and rendering over project-view/. Never talks "
            "to the daemon. Scan reports every machine; show renders one "
            "file's machine as JSON, mermaid, or SVG."
        ),
        epilog="""
Subcommands:
  cts fsm scan [options]              scan the workspace and report FSMs
  cts fsm show [options]              render one file's machine

Exit codes:
  0 - output produced, including "no FSM found" (absence is reported in the
      payload, never through the exit status)
  2 - invalid workspace, invalid/traversing path, bad machine index, or a
      read/parse failure
""",
    )
    nested = parser.add_subparsers(dest="fsm_action", metavar="SUBCOMMAND")

    scan = nested.add_parser(
        "scan",
        help="Scan the workspace and report every FSM found",
        description=(
            "Analyse every matching project-view .st file and report the "
            "machines. A workspace with no FSM still exits 0."
        ),
    )
    scan.add_argument("--workspace", required=True,
                      help="Sync folder containing project-view/")
    scan.add_argument("--query", default="",
                      help="Only scan files whose relative path contains this "
                           "case-insensitive substring")
    scan.add_argument("--workers", type=int, default=None,
                      help="Worker process count (default: min(6, cpu_count))")
    scan.add_argument("--json", action="store_true",
                      help="Emit exactly one JSON document to stdout")

    show = nested.add_parser(
        "show",
        help="Render one file's machine as JSON, mermaid, or SVG",
        description=(
            "Analyse a single project-view .st file and render the chosen "
            "machine. The file path is always relative to project-view."
        ),
    )
    show.add_argument("--workspace", required=True,
                      help="Sync folder containing project-view/")
    show.add_argument("--file", required=True,
                      help="Path relative to project-view, e.g. "
                           "Application/PLC_PRG.st")
    show.add_argument("--machine", type=int, default=0,
                      help="Machine index in the file (default: 0)")
    show.add_argument("--format", choices=["json", "mermaid", "svg"],
                      default="json",
                      help="Output format (default: json)")


__all__ = ["register"]
