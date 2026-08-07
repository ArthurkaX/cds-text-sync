"""Shared argparse fragments used by command-group registrations."""


def add_timeout(parser, default):
    parser.add_argument(
        "--timeout",
        type=float,
        default=default,
        help=f"Timeout in seconds (default: {default})",
    )
    return parser


def add_daemon_parser(subparsers, name, help_text, timeout):
    """Create a daemon-backed command parser with the standard timeout."""
    return add_timeout(subparsers.add_parser(name, help=help_text), timeout)


def add_analyze_common(parser):
    """Add options shared by every ``cts analyze`` subcommand."""
    parser.add_argument(
        "--workspace",
        default="",
        help="Sync folder containing project-view/ (default: nearest ancestor with cts-analyze.toml + project-view)",
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
        help="Exit 1 when findings at/above this severity exist (default: suspicious)",
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
    return parser
