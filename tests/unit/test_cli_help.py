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
    assert "Several IDEs and projects:" in help_text
    assert "Copy button" in help_text
    assert "ambiguous_target" in help_text


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



def test_top_level_help_describes_library_workflow():
    help_text = build_parser().format_help()
    assert "Library projects:" in help_text
    assert "cts build --install" in help_text
    assert "System library repository" in help_text
    assert "Nothing is installed if the check reports errors" in help_text


def test_build_help_shows_install_flag():
    parser = build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices and "build" in a.choices)
    text = sub.choices["build"].format_help()
    assert "--install" in text
    assert "library repository" in text


def test_docs_output_flag_does_not_shadow_the_format_flag():
    parser = build_parser()

    args = parser.parse_args(["docs", "--output", "C:/docs/out"])
    assert args.docs_output == "C:/docs/out"
    assert args.output == "json"

    args = parser.parse_args(["--output", "text", "docs"])
    assert args.output == "text"
    assert args.docs_output == ""


def test_docs_output_reaches_generate_docs(monkeypatch):
    from cds_cli import main as cli_main
    import cds_text_sync.docgen as docgen

    seen = {}

    def _fake_generate(workspace, library_path=None, output=None):
        seen["output"] = output
        return {"output": "written"}

    monkeypatch.setattr(docgen, "generate_docs", _fake_generate)
    monkeypatch.setattr("sys.argv", ["cts", "docs", "--output", "C:/docs/out"])
    cli_main.main()
    assert seen["output"] == "C:/docs/out"


def test_docs_output_reaches_check_and_validate(monkeypatch):
    from cds_cli import main as cli_main
    import cds_text_sync.docgen as docgen

    seen = {}

    def _fake_check(workspace, output=None):
        seen["check"] = output
        return {"ok": True}

    def _fake_validate(output):
        seen["validate"] = output
        return []

    monkeypatch.setattr(docgen, "check_docs", _fake_check)
    monkeypatch.setattr(docgen, "validate_bundle", _fake_validate)

    monkeypatch.setattr("sys.argv", ["cts", "docs", "--check", "--output", "C:/docs/out"])
    cli_main.main()
    monkeypatch.setattr(
        "sys.argv", ["cts", "docs", "--validate", "--output", "C:/docs/out"]
    )
    cli_main.main()
    assert seen == {"check": "C:/docs/out", "validate": "C:/docs/out"}


def test_subcommand_help_is_not_replaced_by_top_level_help(monkeypatch, capsys):
    import pytest
    from cds_cli import main as cli_main

    monkeypatch.setattr(cli_main, "_print_help_header", lambda target=None: None)
    monkeypatch.setattr("sys.argv", ["cts", "--target", "ide-1", "build", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli_main.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--install" in out
    assert "positional arguments:" not in out


def test_main_module_does_not_re_export_handler_helpers():
    """main() imports its helpers to call them, not to publish them [CLI4].

    The module used to list ~35 private names in __all__ under "kept
    accessible"; no consumer imported any of them from here, so the list is
    gone and the names come from the modules that define them.
    """
    from cds_cli import main as cli_main

    assert cli_main.__all__ == ["main", "build_parser"]
    assert not hasattr(cli_main, "_project_command")
    assert not hasattr(cli_main, "DAEMON_SCRIPT")
    # Still a module global: test_cli_handlers_daemon patches it by name here.
    assert callable(cli_main.send_command_reverse)


# -- snapshooter ---------------------------------------------------------------


def _snapshooter_help(monkeypatch, action=""):
    """Snapshooter help with a wide terminal, so prose is not line-wrapped."""
    monkeypatch.setenv("COLUMNS", "240")
    parser = build_parser()._subparsers._group_actions[0].choices["snapshooter"]
    if action:
        parser = parser._subparsers._group_actions[0].choices[action]
    return " ".join(parser.format_help().split())


def test_snapshooter_help_states_which_actions_need_an_online_session(monkeypatch):
    help_text = _snapshooter_help(monkeypatch)

    assert "no PLC session: reads the exported declarations only" in help_text
    assert "take/diff/restore all read live values" in help_text
    assert 'they answer "Not connected"' in help_text
    assert "the daemon adopts a session but never logs in itself" in help_text
    assert "all_steps_ok=false" in help_text


def test_snapshooter_help_lists_the_output_envelopes(monkeypatch):
    help_text = _snapshooter_help(monkeypatch)

    for envelope in (
        "document{meta,variables}",
        "report{same,missing,type_changed,value_changed}",
        "result{written,skipped,warnings,would_write,details}",
        "report{ok,failed_steps,all_steps_ok,steps,",
    ):
        assert envelope in help_text, envelope


def test_snapshooter_help_warns_about_the_first_call_and_the_timeout(monkeypatch):
    help_text = _snapshooter_help(monkeypatch)

    assert "every action defaults to --timeout 300" in help_text
    assert "tens of thousands of leaves" in help_text
    assert ".dump/snapshots/variable_tree.json" in help_text


def test_snapshooter_help_places_the_diagnostic_log(monkeypatch):
    help_text = _snapshooter_help(monkeypatch)

    assert ".dump/snapshooter.log" in help_text
    assert "Save detailed engine logs in .dump" in help_text
    assert "the file is empty or absent" in help_text


def test_snapshooter_tree_help_says_path_is_a_case_sensitive_prefix(monkeypatch):
    help_text = _snapshooter_help(monkeypatch, "tree")

    assert "starts with this prefix (case-sensitive" in help_text
    # The action help carries the rule (including the segment-boundary trap);
    # the root epilog spells out that it is neither an exact path nor a glob.
    assert "a plain string prefix and not a segment boundary" in help_text
    assert "use 'GVL.' to pin one GVL" in help_text
    assert "PREFIX match on the leaf path and is case-sensitive" in _snapshooter_help(monkeypatch)


def test_snapshooter_take_help_says_path_is_exact(monkeypatch):
    help_text = _snapshooter_help(monkeypatch, "take")

    assert "An exact variable path to include (repeatable)" in help_text


def test_snapshooter_restore_help_names_the_online_contradiction(monkeypatch):
    help_text = _snapshooter_help(monkeypatch, "restore")

    assert "Snapshot import is disabled while CODESYS is online" in help_text
    assert "Not connected" in help_text
    assert "Not repaired here" in help_text


def test_snapshooter_ui_check_help_says_what_it_does_not_check(monkeypatch):
    help_text = _snapshooter_help(monkeypatch, "ui-check")

    assert "the form is never shown" in help_text
    assert "answering fakes" in help_text
    assert "exit code stays 0" in help_text


def test_snapshooter_help_explains_that_the_prefix_is_not_a_segment_boundary(monkeypatch):
    help_text = _snapshooter_help(monkeypatch)

    assert "--path on tree is a PREFIX match on the leaf path and is case-sensitive" in help_text
    assert "NOT a segment boundary" in help_text
    assert "--path GVL matches GVL.a AND GVL_HMI.x" in help_text
    assert "--path 'GVL.'" in help_text
    assert "not a glob -- no * or ? is expanded" in help_text


def test_snapshooter_help_says_where_file_paths_are_resolved(monkeypatch):
    help_text = _snapshooter_help(monkeypatch)

    assert "--out and --input may be relative and are read from the" in help_text
    assert "the daemon opens them inside CODESYS" in help_text
    assert "--paths-file is opened by cts itself" in help_text
    assert 'with "path must be absolute"' in help_text


def test_snapshooter_help_examples_cover_every_action(monkeypatch):
    """The examples are the part people copy; each action needs one."""
    help_text = _snapshooter_help(monkeypatch)

    for action in ("tree", "take", "diff", "restore", "ui-check"):
        assert "cts snapshooter {0}".format(action) in help_text, action
    assert "cts snapshooter restore --input preset.json --apply" in help_text


def test_snapshooter_ui_check_help_says_there_is_no_out_option(monkeypatch):
    help_text = _snapshooter_help(monkeypatch, "ui-check")

    assert "There is no --out here" in help_text
    assert "temporary preset file the daemon picks itself" in help_text
    assert "under the daemon's TEMP directory" in help_text
