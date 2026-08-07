"""Argument registration for the offline static analyzer command."""

from ._common import add_analyze_common


def register(subparsers):
    parser = subparsers.add_parser(
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
    add_analyze_common(parser)
    nested = parser.add_subparsers(dest="analyze_action", metavar="SUBCOMMAND")

    run = nested.add_parser(
        "run",
        help="Run the analysis (this is also the default without a subcommand)",
    )
    add_analyze_common(run)
    for name, help_text in (
        ("rules", "List registered rules"),
        ("selftest", "Run every rule against its own documentation examples"),
    ):
        add_analyze_common(nested.add_parser(name, help=help_text))

    explain = nested.add_parser("explain", help="Show one rule's documentation")
    add_analyze_common(explain)
    explain.add_argument("rule_id", help="Rule id, e.g. CTS0001")

    baseline = nested.add_parser("baseline", help="Baseline management")
    add_analyze_common(baseline)
    baseline.add_argument(
        "baseline_action",
        choices=["create", "update", "check"],
        help="create - snapshot current findings\n"
        "update - rewrite the baseline\n"
        "check - report new and stale baseline entries",
    )

    add_analyze_common(
        nested.add_parser(
            "triage",
            help="Convert findings into suppress/fix-later decisions",
        )
    )


__all__ = ["register"]
