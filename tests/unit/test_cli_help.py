"""User-facing CLI help contracts."""

from cds_cli._cli_parser import build_parser


def test_top_level_help_marks_ide_interactive_commands():
    help_text = build_parser().format_help()

    assert "IDE-interactive PLC commands:" in help_text
    assert "[IDE interaction] Login/connect to PLC" in help_text
    assert "[IDE interaction] Download to PLC" in help_text
    assert "the CLI waits and cannot answer them for you" in help_text


def test_top_level_help_describes_advanced_headless_crc_probe():
    help_text = build_parser().format_help()

    assert "Advanced headless CRC probe:" in help_text
    assert "cts plc-crc-headless --help" in help_text
    assert "never downloads, updates, starts, or stops a PLC" in help_text


def test_headless_crc_help_explains_read_only_and_credentials():
    parser = build_parser()._subparsers._group_actions[0].choices["plc-crc-headless"]
    help_text = " ".join(parser.format_help().split())

    assert "never downloads, updates, starts, or stops the PLC" in help_text
    assert "CDS_CRC_PLC_USERNAME" in help_text
    assert "credentials.username_env" in help_text


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


def test_top_level_help_includes_target_and_expect_project():
    help_text = build_parser().format_help()
    assert "--target ID" in help_text
    assert "--expect-project NAME|PATH" in help_text
    assert "Several IDEs:" in help_text


def test_help_header_target_resolved(monkeypatch, capsys):
    from cds_cli import main as cli_main
    from cds_text_sync.engine.pipe_targets import Hello

    h = Hello(
        protocol=2,
        id="ide-3684",
        pid=3684,
        project={"name": "VKO", "path": r"S:\Projects\VKO\VKO.project", "sync_folder": r"S:\Active\VKO"},
    )
    monkeypatch.setattr(cli_main, "discover", lambda b=1.0: [h])

    cli_main._print_help_header(target="ide-3684")
    out = capsys.readouterr().out
    assert "Target: ide-3684  project VKO" in out
    assert "Pass --target ide-3684 on every command." in out


def test_help_header_single_instance_no_target(monkeypatch, capsys):
    from cds_cli import main as cli_main
    from cds_text_sync.engine.pipe_targets import Hello

    h = Hello(
        protocol=2,
        id="ide-3684",
        pid=3684,
        project={"name": "VKO", "path": r"S:\Projects\VKO\VKO.project", "sync_folder": r"S:\Active\VKO"},
    )
    monkeypatch.setattr(cli_main, "discover", lambda b=1.0: [h])

    cli_main._print_help_header(target=None)
    out = capsys.readouterr().out
    assert "Target: ide-3684  project VKO" in out
    assert "Pass --target ide-3684 on every command." in out


def test_help_header_multiple_instances_ambiguous(monkeypatch, capsys):
    from cds_cli import main as cli_main
    from cds_text_sync.engine.pipe_targets import Hello

    h1 = Hello(protocol=2, id="ide-100", pid=100, project={"name": "VKO"})
    h2 = Hello(protocol=2, id="ide-200", pid=200, project={"name": "Motion"})
    monkeypatch.setattr(cli_main, "discover", lambda b=1.0: [h1, h2])

    cli_main._print_help_header(target=None)
    out = capsys.readouterr().out
    assert "2 IDE instances, choose one:" in out
    assert "cts --target ide-100 ...   # VKO" in out
    assert "cts --target ide-200 ...   # Motion" in out


def test_help_header_none_answered(monkeypatch, capsys):
    from cds_cli import main as cli_main

    monkeypatch.setattr(cli_main, "discover", lambda b=1.0: [])

    cli_main._print_help_header(target=None)
    out = capsys.readouterr().out
    assert "Note: no IDE answered; help printed anyway." in out

