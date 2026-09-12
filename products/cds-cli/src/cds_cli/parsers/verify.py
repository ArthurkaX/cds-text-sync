"""Argument registration for ``cts verify`` -- the one-command gate."""

import argparse


def register(subparsers):
    parser = subparsers.add_parser(
        "verify",
        help="Run every applicable check and return one verdict",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Runs the offline checks, then the compiler if the CODESYS "
        "daemon is answering, and reduces everything to one verdict with one "
        "exit code. Offline stages are read-only; --with-test executes the "
        "selected test plans against the configured target.",
        epilog="""
    Exit codes:
      0  pass
      1  fail -- a stage found real problems
      2  verify could not start (no sync folder / no project-view/)
      3  incomplete run, with --incomplete error

    Stages that could not run are reported as ``skipped`` and leave the
    verdict alone -- an agent with no IDE open is never told it broke the
    project. Use --incomplete error in CI when a partial run is not enough.

    Examples:
      cts --pretty verify --sync-folder C:\\Projects\\Plant
      cts verify --only analyze,visu-sketch
      cts verify --with-test          # also run the .test/ plans on the PLC
    """,
    )
    parser.add_argument(
        "--sync-folder",
        dest="sync_folder",
        default="",
        help="Sync folder or project-view/ (default: search up from cwd)",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated stages to run: analyze, visu-sketch, build, test",
    )
    parser.add_argument(
        "--with-test",
        dest="with_test",
        action="store_true",
        help="Also run the .test/ plans (connects to the PLC and starts code)",
    )
    parser.add_argument(
        "--test-file",
        dest="test_file",
        default="",
        help="Single test plan to run instead of every plan in .test/",
    )
    parser.add_argument(
        "--incomplete",
        choices=["warn", "error", "ignore"],
        default="warn",
        help="What an incomplete run means (default: warn)",
    )
    parser.add_argument(
        "--probe-timeout",
        dest="probe_timeout",
        type=float,
        default=2.0,
        help="Seconds to wait for the daemon ping probe (default: 2.0)",
    )
    parser.add_argument(
        "--build-timeout",
        dest="build_timeout",
        type=float,
        default=None,
        help="Daemon timeout for the build stage in seconds (default: 120)",
    )
    parser.add_argument(
        "--test-timeout",
        dest="test_timeout",
        type=float,
        default=None,
        help="Daemon timeout for the test stage in seconds (default: 120)",
    )


__all__ = ["register"]
