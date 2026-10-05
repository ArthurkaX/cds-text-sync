# -*- coding: utf-8 -*-
"""Characterization grid for ``cds_cli.main.main()`` -- the CLI entry contract.

``main()`` is the composition root of ``cts``: it parses argv, validates the
target, configures the reverse pipe, then routes to exactly one command
handler.  This grid pins that contract -- the exit status, stdout/stderr, which
boundary got called with which arguments, and the order of the side effects --
so the body can be decomposed into named stages without moving any behaviour.

Every external boundary is faked: ``configure``/``discover`` (config + IDE
discovery), the passthrough dispatchers (menu/guide/daemon/patch/config/plc_log)
and every concrete command handler.  The tests therefore describe what
``main()`` does, not what the handlers do with their arguments; the handlers
have their own suites.
"""

import json
import sys

import pytest

import cds_cli.main as cli_main
from cds_text_sync import __version__
from cds_text_sync.engine.pipe_targets import TargetError
from cds_text_sync.visu.commands import VisuCommandError


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _Harness(object):
    """Install recording fakes on ``main``'s boundaries and drive ``main()``."""

    _PASSTHROUGH = (
        "dispatch_menu",
        "dispatch_guide",
        "dispatch_daemon",
        "dispatch_patch",
        "dispatch_config",
        "dispatch_plc_log",
    )
    _CONCRETE = (
        "cmd_direct",
        "cmd_rp_command",
        "dispatch_project",
        "dispatch_pou",
        "cmd_discover",
        "cmd_read_vars",
        "cmd_variable_map",
        "cmd_variable_snapshot",
        "cmd_variable_restore",
        "dispatch_visu",
    )

    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.calls = []

    def _recorder(self, label, result, raises):
        def _fake(*args, **kwargs):
            self.calls.append((label, args, kwargs))
            if raises is not None:
                raise raises
            return result
        return _fake

    def install_main(self, name, result=None, raises=None):
        self.mp.setattr(cli_main, name, self._recorder(name, result, raises))
        return self

    def install_path(self, dotted, label=None, result=None, raises=None):
        """Patch a lazy-import target by dotted path (imported on demand)."""
        self.mp.setattr(
            dotted, self._recorder(label or dotted.rsplit(".", 1)[-1], result, raises)
        )
        return self

    def setup(self):
        self.install_main("configure")
        self.install_main("discover", result=[])
        self.install_main("_print_help_header")
        self.install_main("send_command_reverse", result={"ok": True, "data": {}})
        for name in self._CONCRETE:
            self.install_main(name)
        for name in self._PASSTHROUGH:
            self.install_main(name, result=False)
        return self

    def run(self, argv):
        self.mp.setattr(sys, "argv", list(argv))
        return cli_main.main()

    # -- assertions helpers -------------------------------------------------

    def names(self):
        return [name for name, _, _ in self.calls]

    def calls_of(self, label):
        return [(args, kwargs) for name, args, kwargs in self.calls if name == label]

    def last(self, label):
        found = self.calls_of(label)
        assert found, "no call to %r; calls were %r" % (label, self.names())
        return found[-1]

    def assert_not_called(self, label):
        assert self.calls_of(label) == [], (
            "%s should not have been called: %r" % (label, self.calls_of(label))
        )


@pytest.fixture
def cli(monkeypatch):
    return _Harness(monkeypatch).setup()


# ---------------------------------------------------------------------------
# Help / version / parse errors
# ---------------------------------------------------------------------------


def test_no_args_prints_help_and_exits_zero(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts"])

    assert exc.value.code == 0
    assert cli.last("_print_help_header") == ((), {"target": None})
    assert "usage:" in capsys.readouterr().out


def test_help_flag_prints_help_and_exits_zero(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--help"])

    assert exc.value.code == 0
    assert cli.last("_print_help_header") == ((), {"target": None})
    assert "usage:" in capsys.readouterr().out


def test_help_flag_passes_the_target_to_the_header(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--target", "ide-42", "--help"])

    assert exc.value.code == 0
    assert cli.last("_print_help_header") == ((), {"target": "ide-42"})


def test_help_for_a_known_command_shows_that_commands_help(cli, capsys):
    """`cts build --help` must not be swallowed by the top-level header."""
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--target", "ide-1", "build", "--help"])

    assert exc.value.code == 0
    assert cli.last("_print_help_header") == ((), {"target": "ide-1"})
    out = capsys.readouterr().out
    assert "--install" in out
    assert "positional arguments:" not in out


def test_version_prints_the_version_and_exits_zero(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--version"])

    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_unknown_command_is_a_parse_error(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "frobnicate"])

    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    cli.assert_not_called("configure")


def test_a_missing_command_is_a_parse_error(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--target", "ide-1"])

    assert exc.value.code == 2
    assert "command" in capsys.readouterr().err
    cli.assert_not_called("configure")


def test_a_missing_required_option_is_a_parse_error(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "visu-lint"])  # --xml is required

    assert exc.value.code == 2
    assert "--xml" in capsys.readouterr().err
    cli.assert_not_called("configure")


# ---------------------------------------------------------------------------
# Target validation / configure
# ---------------------------------------------------------------------------


def test_invalid_target_is_reported_and_exits_two(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--target", "garbage", "status"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "[ERROR]" in err
    assert "Invalid target 'garbage'" in err
    cli.assert_not_called("configure")


def test_valid_target_and_expect_project_reach_configure(cli):
    cli.run(["cts", "--target", "ide-42", "--expect-project", "VKO", "status"])

    assert cli.last("configure") == (
        (),
        {"target": "ide-42", "expect_project": "VKO"},
    )


def test_configure_runs_before_any_command_handler(cli):
    cli.run(["cts", "discover"])

    names = cli.names()
    assert names.index("configure") < names.index("cmd_discover")


# ---------------------------------------------------------------------------
# Output format resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags,expected",
    [
        ([], "json"),
        (["--pretty"], "text"),
        (["--output", "text"], "text"),
        (["--output", "json"], "json"),
    ],
)
def test_output_format_is_forwarded_to_the_handler(cli, flags, expected):
    cli.run(["cts"] + flags + ["read-vars", "GVL.a"])

    assert cli.last("cmd_read_vars")[1]["output_fmt"] == expected


# ---------------------------------------------------------------------------
# The passthrough dispatcher chain
# ---------------------------------------------------------------------------


def test_the_first_handled_passthrough_wins(cli):
    cli.install_main("dispatch_menu", result=False)
    cli.install_main("dispatch_guide", result=True)
    cli.install_main("dispatch_daemon", result=True)

    cli.run(["cts", "status"])

    assert cli.names() == ["configure", "dispatch_menu", "dispatch_guide"]


def test_passthrough_handlers_are_tried_in_a_fixed_order(cli, capsys):
    cli.run(["cts", "status"])  # every passthrough declines it

    handled = [n for n in cli.names() if n in _Harness._PASSTHROUGH]
    assert handled == list(_Harness._PASSTHROUGH)
    # Nothing left in the router handles it either -> the parser's own help.
    assert "usage:" in capsys.readouterr().out


def test_passthrough_handlers_receive_the_output_format(cli):
    cli.run(["cts", "--output", "text", "status"])

    for name in _Harness._PASSTHROUGH:
        assert cli.last(name)[0][1] == "text"


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


def test_engine_without_a_subcommand_is_an_error(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "engine"])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[ERROR]" in err
    assert "Specify an engine command" in err
    cli.assert_not_called("cmd_direct")


def test_engine_with_arguments_runs_cmd_direct(cli):
    result = cli.run(["cts", "engine", "export"])

    assert result is None
    assert cli.last("cmd_direct")[0] == (["export"],)
    # engine is handled before the passthrough chain.
    assert not [n for n in cli.names() if n in _Harness._PASSTHROUGH]


# ---------------------------------------------------------------------------
# raw / rp
# ---------------------------------------------------------------------------


def test_raw_dispatches_to_cmd_rp_command(cli):
    cli.run(["cts", "raw", "ping"])

    args, kwargs = cli.last("cmd_rp_command")
    assert args == (["ping"],)
    assert kwargs == {"timeout": 15, "output_fmt": "json"}
    cli.assert_not_called("dispatch_project")


def test_rp_is_an_alias_for_raw(cli):
    cli.run(["cts", "rp", "status"])

    args, kwargs = cli.last("cmd_rp_command")
    assert args == (["status"],)
    assert kwargs["timeout"] == 15


def test_raw_forwards_an_explicit_timeout(cli):
    cli.run(["cts", "raw", "--timeout", "9", "ping"])

    assert cli.last("cmd_rp_command")[1]["timeout"] == 9.0


# ---------------------------------------------------------------------------
# project / pou / discover
# ---------------------------------------------------------------------------


def test_project_dispatches_to_dispatch_project(cli):
    cli.run(["cts", "project", "info"])

    args, kwargs = cli.last("dispatch_project")
    assert args[0].command == "project"
    assert kwargs == {}


def test_pou_dispatches_to_dispatch_pou(cli):
    cli.run(["cts", "pou", "delete", "MAIN"])

    assert cli.last("dispatch_pou")[0][0].name == "MAIN"


def test_discover_dispatches_to_cmd_discover(cli):
    cli.run(["cts", "discover"])

    assert cli.last("cmd_discover") == ((), {})


# ---------------------------------------------------------------------------
# variable commands
# ---------------------------------------------------------------------------


def test_read_vars_forwards_every_argument(cli):
    cli.run(["cts", "read-vars", "GVL.a", "GVL.b", "--file", "vars.txt", "--timeout", "7"])

    assert cli.last("cmd_read_vars") == (
        (),
        {
            "names": ["GVL.a", "GVL.b"],
            "file_path": "vars.txt",
            "timeout": 7.0,
            "output_fmt": "json",
        },
    )


def test_variable_map_forwards_every_argument(cli):
    cli.run(
        [
            "cts",
            "variable-map",
            "--path",
            "GVL_HMI",
            "--out",
            "map.csv",
            "--sync-folder",
            "S:/P",
            "--globals-only",
        ]
    )

    assert cli.last("cmd_variable_map") == (
        (),
        {
            "path_filter": "GVL_HMI",
            "out": "map.csv",
            "sync_folder": "S:/P",
            "include_programs": False,
            "output_fmt": "json",
        },
    )


def test_variable_snapshot_forwards_every_argument(cli):
    cli.run(["cts", "variable-snapshot", "--path", "GVL_HMI", "--timeout", "11"])

    assert cli.last("cmd_variable_snapshot") == (
        (),
        {
            "path_filter": "GVL_HMI",
            "out": "",
            "sync_folder": "",
            "include_programs": True,
            "timeout": 11.0,
            "output_fmt": "json",
        },
    )


def test_variable_restore_forwards_every_argument(cli):
    cli.run(
        [
            "cts",
            "variable-restore",
            "--input",
            "snap.csv",
            "--report",
            "rep.csv",
            "--path",
            "GVL",
            "--apply",
            "--force",
            "--timeout",
            "5",
        ]
    )

    assert cli.last("cmd_variable_restore") == (
        (),
        {
            "input_path": "snap.csv",
            "report": "rep.csv",
            "path_filter": "GVL",
            "do_apply": True,
            "force": True,
            "sync_folder": "",
            "timeout": 5.0,
            "output_fmt": "json",
        },
    )


# ---------------------------------------------------------------------------
# visu (with its own error boundary)
# ---------------------------------------------------------------------------


def test_visu_dispatches_to_dispatch_visu(cli):
    cli.run(["cts", "visu", "types"])

    assert cli.last("dispatch_visu")[0][0].visu_action == "types"


def test_visu_command_error_becomes_diagnostics_and_exit_code(cli, capsys):
    cli.install_main("dispatch_visu", raises=VisuCommandError("screen missing", exit_code=3))

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "visu", "check"])

    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "[ERROR]" in err
    assert "screen missing" in err


def test_visu_unexpected_exception_propagates(cli):
    cli.install_main("dispatch_visu", raises=RuntimeError("kaboom"))

    with pytest.raises(RuntimeError, match="kaboom"):
        cli.run(["cts", "visu", "check"])


# ---------------------------------------------------------------------------
# lazily-imported subcommands
# ---------------------------------------------------------------------------


def test_analyze_propagates_a_nonzero_exit_code(cli):
    cli.install_path("cds_static_analyzer.cli.dispatch_analyze", result=2)

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "analyze"])

    assert exc.value.code == 2
    assert cli.last("dispatch_analyze")[0][0].command == "analyze"


def test_analyze_zero_returns_normally(cli):
    cli.install_path("cds_static_analyzer.cli.dispatch_analyze", result=0)

    assert cli.run(["cts", "analyze"]) is None


def test_verify_receives_the_output_format_and_propagates_its_code(cli):
    cli.install_path("cds_cli.verify.run_verify", result=1)

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "--pretty", "verify"])

    assert exc.value.code == 1
    assert cli.last("run_verify")[0][1] == "text"


def test_headless_crc_prints_its_payload(cli, capsys):
    payload = {"ok": True, "results": []}
    cli.install_path("cds_cli.headless_crc.run_headless_crc", result=(payload, 0))

    assert cli.run(["cts", "plc-crc-headless"]) is None

    assert json.loads(capsys.readouterr().out) == payload
    cli.assert_not_called("run_headless_crc_watch")


def test_headless_crc_propagates_its_exit_code(cli, capsys):
    cli.install_path("cds_cli.headless_crc.run_headless_crc", result=({"ok": True}, 2))

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "plc-crc-headless"])

    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_headless_crc_watch_uses_the_watch_runner(cli):
    cli.install_path("cds_cli.headless_crc.run_headless_crc_watch", result=({"ok": True}, 0))

    cli.run(["cts", "plc-crc-headless", "--watch"])

    assert cli.calls_of("run_headless_crc_watch")
    cli.assert_not_called("run_headless_crc")


def test_headless_crc_invalid_request_becomes_an_error_payload(cli, capsys):
    cli.install_path(
        "cds_cli.headless_crc.run_headless_crc", raises=OSError("bad batch file")
    )

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "plc-crc-headless"])

    assert exc.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["results"] == []
    assert payload["error"] == {"code": "invalid_request", "message": "bad batch file"}


def test_ui_launches_with_the_workspace(cli):
    cli.install_path("cds_text_sync.ui.launch", result=0)

    assert cli.run(["cts", "ui", "--workspace", "S:/P"]) is None
    assert cli.last("launch")[0] == ("S:/P",)


def test_ui_propagates_a_nonzero_code(cli):
    cli.install_path("cds_text_sync.ui.launch", result=4)

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "ui"])

    assert exc.value.code == 4


def test_fsm_dispatches_and_propagates_its_code(cli):
    cli.install_path("cds_text_sync.fsm.cli.dispatch_fsm", result=0)
    assert cli.run(["cts", "fsm"]) is None
    assert cli.last("dispatch_fsm")[0][0].command == "fsm"

    cli.install_path("cds_text_sync.fsm.cli.dispatch_fsm", result=2)
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "fsm"])
    assert exc.value.code == 2


def test_visu_lint_dispatches_and_propagates_its_code(cli):
    cli.install_path("visu_lint.cli.cmd_visu_lint", result=0)
    assert cli.run(["cts", "visu-lint", "--xml", "s.xml"]) is None
    assert cli.last("cmd_visu_lint")[0][0].xml == "s.xml"

    cli.install_path("visu_lint.cli.cmd_visu_lint", result=2)
    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "visu-lint", "--xml", "s.xml"])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# docs
# ---------------------------------------------------------------------------


def test_docs_generate_prints_the_output_path(cli, capsys):
    cli.install_path("cds_text_sync.docgen.generate_docs", result={"output": "written"})

    assert cli.run(["cts", "docs"]) is None

    assert "written" in capsys.readouterr().out
    assert cli.last("generate_docs")[1]["output"] is None


def test_docs_validate_fails_on_error_diagnostics(cli, capsys):
    cli.install_path(
        "cds_text_sync.docgen.validate_bundle",
        result=[{"severity": "warning"}, {"severity": "error"}],
    )

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "docs", "--validate", "--output", "C:/out"])

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert len(payload["diagnostics"]) == 2


def test_docs_validate_passes_without_errors(cli, capsys):
    cli.install_path("cds_text_sync.docgen.validate_bundle", result=[])

    assert cli.run(["cts", "docs", "--validate", "--output", "C:/out"]) is None

    assert json.loads(capsys.readouterr().out)["ok"] is True
    cli.assert_not_called("generate_docs")


def test_docs_check_propagates_its_exit_code(cli, capsys):
    cli.install_path("cds_text_sync.docgen.check_docs", result={"ok": False, "exit_code": 4})

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "docs", "--check"])

    assert exc.value.code == 4
    cli.assert_not_called("generate_docs")


def test_docs_daemon_uses_the_pipe_sync_folder(cli):
    cli.install_main(
        "send_command_reverse", result={"ok": True, "data": {"sync_folder": "S:/from-daemon"}}
    )
    cli.install_path("cds_text_sync.docgen.generate_docs", result={"output": "written"})

    cli.run(["cts", "docs", "--daemon"])

    assert cli.last("send_command_reverse")[0] == ("generate_docs", {})
    assert cli.last("generate_docs")[0][0] == "S:/from-daemon"


def test_docs_daemon_reverse_pipe_failure_exits_one(cli, capsys):
    cli.install_main("send_command_reverse", result={"ok": False, "error": "no daemon"})

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "docs", "--daemon"])

    assert exc.value.code == 1
    assert "no daemon" in capsys.readouterr().err


def test_docs_daemon_runtime_error_exits_one(cli, capsys):
    cli.install_main("send_command_reverse", raises=RuntimeError("pipe gone"))

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "docs", "--daemon"])

    assert exc.value.code == 1
    assert "Reverse pipe error: pipe gone" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# TargetError boundary
# ---------------------------------------------------------------------------


def test_target_error_from_a_handler_is_reported_and_exits_two(cli, capsys):
    cli.install_main(
        "cmd_discover", raises=TargetError("ambiguous_target", "2 IDE instances, choose one")
    )

    with pytest.raises(SystemExit) as exc:
        cli.run(["cts", "discover"])

    assert exc.value.code == 2
    assert "2 IDE instances, choose one" in capsys.readouterr().err
