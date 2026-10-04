"""Argument registration for the PLC runtime log reader (``cts plc-log``)."""

import argparse

from cds_cli.parsers._common import add_timeout


def register(subparsers):
    parser = subparsers.add_parser(
        "plc-log",
        help="Read the PLC runtime log; extract CTS| event records",
        description=(
            "Read the PLC runtime log (CmpLog) over the online device. With "
            "no options it lists the log files on the PLC. --file selects one "
            "(default: codesyscontrol.log), --tail N prints the last N lines, "
            "and --output PATH saves the whole file.\n\n"
            "With --cts the command keeps only entries whose message carries "
            "the generated 'CTS|<level>|<CODE>|<TAG>|k=v;k=v' marker and "
            "returns them parsed as JSON records. --level and --code filter "
            "those records and imply --cts. A CTS line that does not parse is "
            "reported separately in a 'malformed' list with a 'parse_errors' "
            "count instead of being dropped.\n\n"
            "Parsing needs the file text, which the daemon returns only as a "
            "tail; for a plain --cts read the CLI asks the daemon to save the "
            "log into a temporary folder and reads the file there."
        ),
        epilog=(
            "Examples:\n"
            "  cts plc-log                                   # list log files\n"
            "  cts plc-log --tail 200                        # last 200 raw lines\n"
            "  cts plc-log --cts                             # parse the whole log\n"
            "  cts plc-log --cts --level M                   # minimal (always-on) events\n"
            "  cts plc-log --cts --code ALM_RAISE            # one event code\n"
            "  cts plc-log --output C:/Temp/log --cts        # keep the raw file too"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file",
        default="codesyscontrol.log",
        help="Which log file to read (default: codesyscontrol.log)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=0,
        help="Show/parse only the last N lines (0: no limit)",
    )
    # Own dest: the global --output/--pretty select the JSON/text output
    # format, and sharing the dest made the subparser default clobber it.
    parser.add_argument(
        "--output",
        "--out",
        dest="log_output",
        default="",
        help="Save the full log to this file or directory",
    )
    parser.add_argument(
        "--cts",
        action="store_true",
        help="Keep only CTS| entries and return them as parsed JSON records",
    )
    parser.add_argument(
        "--level",
        choices=["M", "V"],
        default="",
        help="Only records of this level (M minimal, V verbose); implies --cts",
    )
    parser.add_argument(
        "--code",
        default="",
        help="Only records with this event code; implies --cts",
    )
    add_timeout(parser, None)
