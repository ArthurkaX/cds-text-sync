"""User-facing CLI help contracts."""

from cds_cli._cli_parser import build_parser


def test_top_level_help_marks_ide_interactive_commands():
    help_text = build_parser().format_help()

    assert "IDE-interactive PLC commands:" in help_text
    assert "[IDE interaction] Login/connect to PLC" in help_text
    assert "[IDE interaction] Download to PLC" in help_text
    assert "the CLI waits and cannot answer them for you" in help_text


def test_connect_help_warns_about_modal_ide_questions():
    parser = build_parser()._subparsers._group_actions[0].choices["connect"]
    help_text = " ".join(parser.format_help().split())

    assert "modal Login or connection dialog" in help_text
    assert "open CODESYS and approve or cancel the dialog" in help_text
    assert "complete Online -> Login before starting the daemon" in help_text


def test_download_help_warns_about_modal_ide_questions():
    parser = build_parser()._subparsers._group_actions[0].choices["download"]
    help_text = " ".join(parser.format_help().split())

    assert "modal Download, Online Change, Login, or safety confirmation" in help_text
    assert "open CODESYS and approve or cancel the dialog" in help_text
