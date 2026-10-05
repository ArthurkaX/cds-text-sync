# -*- coding: utf-8 -*-
"""``cts new`` -- argument parsing, exit codes and the printed report.

The creation itself lives in ``cds_text_sync.engine.new_object`` and is covered
by ``tests/unit/test_new_object.py``. What is pinned here is the CLI's half:
which arguments reach the engine, that a ``project-view`` path is accepted the
way the sibling commands accept it, that a refusal is an error with a code
rather than a traceback, and that the report carries the ``next`` steps.

No daemon is involved anywhere: the command is offline by design, so these
tests need no pipe at all.
"""

import json
import os
import subprocess
import sys

import pytest

import cds_cli._cli_handlers_new_object as handler
from cds_cli.main import build_parser


APPLICATION = "Runtime/PLC Logic/Application"

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def _args(argv):
    return build_parser().parse_args(argv)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A sync folder with a view root, an Application folder and a manifest."""
    root = str(tmp_path)
    views = os.path.join(root, "project-view")
    os.makedirs(os.path.join(views, *APPLICATION.split("/")))
    os.makedirs(os.path.join(root, ".dump"))
    manifest = {
        "view_root": views,
        "ns": "",
        "entries": [
            {
                "guid": "g1",
                "name": "PLC_PRG",
                "xml_path": "{0}/PLC_PRG.xml".format(APPLICATION),
            }
        ],
    }
    with open(os.path.join(root, ".dump", "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    monkeypatch.chdir(root)
    return root


def _run(args, output_fmt="json"):
    """Run the handler and return ``(printed_dict, exit_code)``."""
    try:
        handled = handler.dispatch_new_object(args, output_fmt=output_fmt)
    except SystemExit as exc:
        return None, exc.code
    assert handled is True
    return None, 0


def _run_capture(capsys, args, output_fmt="json"):
    """``(payload, exit_code)`` with stdout parsed, for the JSON format."""
    code = 0
    try:
        handler.dispatch_new_object(args, output_fmt=output_fmt)
    except SystemExit as exc:
        code = exc.code
    out, err = capsys.readouterr()
    return out, err, code


# -- the parser ---------------------------------------------------------------


class TestParser:
    def test_the_three_kinds_are_registered(self):
        sub = build_parser()._subparsers._group_actions[0].choices["new"]
        choices = sub._subparsers._group_actions[0].choices
        assert sorted(choices) == ["dut", "gvl", "pou"]

    def test_a_missing_kind_is_a_parse_error(self):
        with pytest.raises(SystemExit) as excinfo:
            _args(["new"])
        assert excinfo.value.code == 2

    def test_gvl_parses_its_arguments(self):
        a = _args(["new", "gvl", "GVL_X", "--text", "a : INT;", "--parent", "A/B"])
        assert (a.command, a.new_kind, a.name) == ("new", "gvl", "GVL_X")
        assert (a.text, a.parent) == ("a : INT;", "A/B")

    def test_pou_requires_its_kind(self):
        with pytest.raises(SystemExit):
            _args(["new", "pou", "P"])
        a = _args(["new", "pou", "P", "--kind", "function", "--return-type", "REAL"])
        assert (a.pou_kind, a.return_type) == ("function", "REAL")

    def test_a_bad_pou_kind_is_rejected_by_argparse(self):
        with pytest.raises(SystemExit):
            _args(["new", "pou", "P", "--kind", "subroutine"])

    def test_dut_parses_its_base_type(self):
        a = _args(["new", "dut", "T", "--kind", "alias", "--base-type", "UINT"])
        assert (a.dut_kind, a.base_type) == ("alias", "UINT")

    def test_the_language_option_defaults_to_st(self):
        assert _args(["new", "pou", "P", "--kind", "program"]).language == "st"


# -- routing ------------------------------------------------------------------


class TestRouting:
    def test_a_foreign_command_is_declined(self, monkeypatch):
        assert handler.dispatch_new_object(_args(["ping"])) is False

    def test_the_command_is_reached_from_main(self, monkeypatch):
        """``main`` must route ``new`` here, not fall through to help."""
        from cds_cli import main as cli_main

        seen = {}

        def fake(args, fmt):
            seen["called"] = True
            return True

        monkeypatch.setattr(cli_main, "dispatch_new_object", fake)
        monkeypatch.setattr(cli_main, "_dispatch_pipe_command", lambda a, f: False)
        monkeypatch.setattr(cli_main, "_dispatch_project_command", lambda a: False)
        monkeypatch.setattr(cli_main, "_dispatch_variable_command", lambda a, f: False)
        monkeypatch.setattr(cli_main, "dispatch_snapshooter", lambda a, f: False)
        monkeypatch.setattr(cli_main, "_dispatch_visu_command", lambda a: False)
        monkeypatch.setattr(cli_main, "_dispatch_lazy_command", lambda a, f: False)

        cli_main._dispatch_command(_args(["new", "gvl", "GVL_X"]), "json", None)

        assert seen == {"called": True}


# -- syncing: where the sync folder comes from --------------------------------


class TestSyncFolderResolution:
    def test_the_current_directory_is_searched_upwards(self, project, capsys, monkeypatch):
        nested = os.path.join(project, "project-view", *APPLICATION.split("/"))
        monkeypatch.chdir(nested)

        _out, _err, code = _run_capture(capsys, _args(["new", "gvl", "GVL_A"]))

        assert code == 0
        assert os.path.isfile(
            os.path.join(project, "project-view", *APPLICATION.split("/"), "GVL_A.st")
        )

    def test_an_explicit_sync_folder_wins(self, project, capsys, tmp_path, monkeypatch):
        """Runs from outside any project and creates there, not in ``project``."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        sub = elsewhere / "other-project"
        os.makedirs(str(sub / "project-view" / APPLICATION))
        os.makedirs(str(sub / ".dump"))
        with open(str(sub / ".dump" / "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "view_root": str(sub / "project-view"),
                    "ns": "",
                    "entries": [
                        {"guid": "g", "xml_path": "{0}/X.xml".format(APPLICATION)}
                    ],
                },
                fh,
            )
        monkeypatch.chdir(elsewhere)

        _out, _err, code = _run_capture(
            capsys,
            _args(["new", "gvl", "GVL_A", "--sync-folder", str(sub)]),
        )

        assert code == 0
        assert os.path.isfile(str(sub / "project-view" / APPLICATION / "GVL_A.st"))
        assert not os.path.exists(
            os.path.join(project, "project-view", *APPLICATION.split("/"), "GVL_A.st")
        )

    def test_a_project_view_path_resolves_to_its_parent(self, project, capsys):
        views = os.path.join(project, "project-view")

        _out, _err, code = _run_capture(
            capsys, _args(["new", "gvl", "GVL_A", "--sync-folder", views])
        )

        assert code == 0

    def test_a_missing_sync_folder_is_exit_2(self, capsys):
        _out, err, code = _run_capture(
            capsys, _args(["new", "gvl", "GVL_A", "--sync-folder", "/nope"])
        )

        assert code == 2
        assert "No such folder" in err

    def test_a_relative_sync_folder_is_reported_absolutely(self, tmp_path, capsys, monkeypatch):
        """So a reader can tell which folder was meant, not which was typed."""
        monkeypatch.chdir(tmp_path)

        _out, err, code = _run_capture(
            capsys, _args(["new", "gvl", "GVL_A", "--sync-folder", "missing"])
        )

        assert code == 2
        assert str(tmp_path / "missing") in err

    def test_a_relative_project_view_parent_is_resolved(self, project, capsys, monkeypatch):
        views = os.path.join(project, "project-view")
        parent = os.path.dirname(views)
        monkeypatch.chdir(parent)

        _out, _err, code = _run_capture(
            capsys, _args(["new", "gvl", "GVL_A", "--sync-folder", "project-view"])
        )

        assert code == 0
        assert os.path.isfile(
            os.path.join(views, *APPLICATION.split("/"), "GVL_A.st")
        )

    def test_a_tree_without_a_project_view_is_exit_2(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)

        _out, err, code = _run_capture(capsys, _args(["new", "gvl", "GVL_A"]))

        assert code == 2
        assert "No project-view/ found here" in err


# -- the report ---------------------------------------------------------------


class TestReport:
    def test_the_json_report_names_the_file_and_the_next_steps(self, project, capsys):
        out, _err, code = _run_capture(capsys, _args(["new", "gvl", "GVL_HMI"]))

        assert code == 0
        payload = json.loads(out)
        assert payload["name"] == "GVL_HMI"
        assert payload["path"] == "{0}/GVL_HMI.st".format(APPLICATION)
        assert payload["files"] == [
            os.path.join(project, "project-view", *APPLICATION.split("/"), "GVL_HMI.st")
        ]
        assert payload["next"][0] == "cts compare"
        assert payload["next"][1] == "cts import"
        assert "the PLC never gets it" in payload["next"][2]
        assert "cts download" in payload["next"][3]
        assert "full download" in payload["next"][3]

    def test_the_text_rendering_is_available(self, project, capsys):
        out, _err, code = _run_capture(
            capsys, _args(["new", "gvl", "GVL_HMI"]), output_fmt="text"
        )

        assert code == 0
        assert "── new ──" in out
        assert "GVL_HMI" in out

    def test_a_duplicate_name_is_exit_1_with_a_message(self, project, capsys):
        _run_capture(capsys, _args(["new", "gvl", "GVL_HMI"]))

        _out, err, code = _run_capture(capsys, _args(["new", "gvl", "GVL_HMI"]))

        assert code == 1
        assert "already exists" in err
        assert "Traceback" not in err

    def test_an_invalid_name_is_exit_1(self, project, capsys):
        _out, err, code = _run_capture(capsys, _args(["new", "gvl", "1Bad"]))
        assert code == 1
        assert "identifier" in err

    def test_a_missing_parent_is_exit_1(self, project, capsys):
        _out, err, code = _run_capture(
            capsys, _args(["new", "gvl", "GVL_A", "--parent", "No/Such"])
        )
        assert code == 1
        assert "Parent folder does not exist" in err

    def test_a_refused_create_writes_nothing(self, project, capsys):
        _run_capture(capsys, _args(["new", "gvl", "GVL_A"]))
        views = os.path.join(project, "project-view", *APPLICATION.split("/"))
        before = sorted(os.listdir(views))

        _run_capture(capsys, _args(["new", "gvl", "GVL_A"]))

        assert sorted(os.listdir(views)) == before


# -- the command is genuinely offline -----------------------------------------


class TestOffline:
    def test_no_pipe_call_is_made(self, project, monkeypatch, capsys):
        """Asking the daemon for the sync folder would need a running IDE."""
        import cds_cli._cli_io as cli_io

        def boom(*args, **kwargs):
            raise AssertionError("cts new must not open the reverse pipe")

        monkeypatch.setattr(cli_io, "send_command_reverse", boom)

        _out, _err, code = _run_capture(capsys, _args(["new", "gvl", "GVL_A"]))

        assert code == 0

    def test_it_runs_without_a_daemon_at_all(self, project):
        """End to end through a real subprocess, with no server to talk to."""
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [
                os.path.join(REPO_ROOT, "products", "cds-cli", "src"),
                os.path.join(REPO_ROOT, "products", "cds-text-sync", "src"),
                os.path.join(REPO_ROOT, "shared", "src"),
            ]
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from cds_cli.main import main; main()",
                "new", "gvl", "GVL_SUB", "--text", "a : INT;",
            ],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )

        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["name"] == "GVL_SUB"
        assert os.path.isfile(
            os.path.join(project, "project-view", *APPLICATION.split("/"), "GVL_SUB.st")
        )
