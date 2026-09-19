"""CLI registration tests for the documentation command."""

from cds_cli._cli_parser import build_parser


def test_docs_command_exposes_library_and_daemon_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "docs",
            "--workspace",
            "sync",
            "--libraries",
            r"C:\ProgramData\CODESYS",
            "--output",
            "out",
            "--daemon",
        ]
    )

    assert args.command == "docs"
    assert args.workspace == "sync"
    assert args.library_path == r"C:\ProgramData\CODESYS"
    assert args.output == "out"
    assert args.daemon is True
    assert args.check is False
    assert args.timeout == 120


def test_docs_command_accepts_check_mode():
    args = build_parser().parse_args(["docs", "--check", "--workspace", "sync"])

    assert args.command == "docs"
    assert args.check is True
    assert args.daemon is False
