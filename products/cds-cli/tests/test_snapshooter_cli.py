# -*- coding: utf-8 -*-
"""``cts snapshooter`` -- parser and handler contract.

The parser turns ``cts snapshooter <action>`` into an ``action`` payload the
daemon's ``snapshooter`` method understands; the handler sends that payload
over the reverse pipe and prints the daemon's data.  ``send_command_reverse``
is faked here, so these tests pin the wire payload (action, params, timeout)
and the CLI's error handling, not the daemon's behaviour.
"""

import json

import pytest


import cds_cli._cli_handlers_snapshooter as handler
from cds_cli.main import build_parser


class Recorder(object):
    def __init__(self, response=None, raises=None):
        self.calls = []
        self.response = response if response is not None else {"ok": True, "data": {"action": "tree"}}
        self.raises = raises

    def __call__(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        if self.raises is not None:
            raise self.raises
        return self.response


def _args(argv):
    return build_parser().parse_args(argv)


@pytest.fixture
def pipe(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(handler, "send_command_reverse", recorder)
    return recorder


# ── Parser ──────────────────────────────────────────────────────────────────


def test_the_actions_are_registered():
    for action in ("tree", "take", "diff", "restore", "ui-check"):
        args = _args(["snapshooter", action] + (["--input", "p.json"] if action in ("diff", "restore") else []))
        assert args.snap_action == action


def test_a_missing_action_is_a_parse_error():
    with pytest.raises(SystemExit) as exc:
        _args(["snapshooter"])

    assert exc.value.code == 2


def test_the_default_timeout_leaves_room_for_a_big_project():
    assert _args(["snapshooter", "tree"]).timeout == handler.DEFAULT_TIMEOUT == 300


# ── Handler: routing and payloads ───────────────────────────────────────────


def test_a_foreign_command_is_declined(pipe):
    assert handler.dispatch_snapshooter(_args(["ping"])) is False
    assert pipe.calls == []


def test_tree_sends_the_prefix_and_timeout(pipe):
    handler.dispatch_snapshooter(_args(["snapshooter", "tree", "--path", "GVL_HMI", "--timeout", "42"]))

    method, params, timeout = pipe.calls[0]
    assert method == "snapshooter"
    assert params == {"action": "tree", "path": "GVL_HMI"}
    assert timeout == 42.0


def test_take_collects_explicit_and_file_paths(pipe, tmp_path):
    paths_file = tmp_path / "selected.txt"
    paths_file.write_text("# comment\nGVL.b\n\n  GVL.c  \n", encoding="utf-8")

    handler.dispatch_snapshooter(
        _args(
            [
                "snapshooter", "take",
                "--path", "GVL.a",
                "--paths-file", str(paths_file),
                "--label", "speed",
                "--out", "preset.json",
            ]
        )
    )

    _method, params, _timeout = pipe.calls[0]
    assert params == {
        "action": "take",
        "paths": ["GVL.a", "GVL.b", "GVL.c"],
        "label": "speed",
        "out": "preset.json",
    }


def test_take_without_paths_omits_the_key(pipe):
    handler.dispatch_snapshooter(_args(["snapshooter", "take"]))

    _method, params, _timeout = pipe.calls[0]
    assert params == {"action": "take"}


def test_a_missing_paths_file_exits_with_an_error(pipe, capsys):
    with pytest.raises(SystemExit) as exc:
        handler.dispatch_snapshooter(_args(["snapshooter", "take", "--paths-file", "/nope.txt"]))

    assert exc.value.code == 1
    assert "File not found" in capsys.readouterr().err
    assert pipe.calls == []


def test_diff_sends_the_preset_path(pipe):
    handler.dispatch_snapshooter(_args(["snapshooter", "diff", "--input", "preset.json"]))

    _method, params, _timeout = pipe.calls[0]
    assert params == {"action": "diff", "input": "preset.json"}


def test_restore_is_dry_run_by_default_and_applies_on_flag(pipe):
    handler.dispatch_snapshooter(_args(["snapshooter", "restore", "--input", "p.json"]))
    _method, params, _timeout = pipe.calls[0]
    assert params == {"action": "restore", "input": "p.json", "apply": False}

    handler.dispatch_snapshooter(_args(["snapshooter", "restore", "--input", "p.json", "--apply"]))
    _method, params, _timeout = pipe.calls[1]
    assert params == {"action": "restore", "input": "p.json", "apply": True}


def test_ui_check_sends_the_app_and_script(pipe):
    handler.dispatch_snapshooter(
        _args(["snapshooter", "ui-check", "--app", "MainApp", "--script", "save, load"])
    )

    _method, params, _timeout = pipe.calls[0]
    assert params == {"action": "ui_check", "app": "MainApp", "script": ["save", "load"]}


def test_ui_check_without_script_omits_the_key(pipe):
    handler.dispatch_snapshooter(_args(["snapshooter", "ui-check"]))

    _method, params, _timeout = pipe.calls[0]
    assert params == {"action": "ui_check", "app": "Application"}


# ── Handler: output and failures ────────────────────────────────────────────


def test_a_successful_response_is_printed_as_json(pipe, capsys):
    pipe.response = {"ok": True, "data": {"action": "tree", "count": 2, "leaves": []}}

    assert handler.dispatch_snapshooter(_args(["snapshooter", "tree"])) is True

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["count"] == 2
    assert payload["action"] == "tree"


def test_text_output_is_honoured(pipe, capsys):
    pipe.response = {"ok": True, "data": {"action": "tree", "count": 2}}

    handler.dispatch_snapshooter(_args(["snapshooter", "tree"]), output_fmt="text")

    assert "── snapshooter ──" in capsys.readouterr().out


def test_a_daemon_error_exits_one(pipe, capsys):
    pipe.response = {"ok": False, "error": "No project is open in this IDE."}

    with pytest.raises(SystemExit) as exc:
        handler.dispatch_snapshooter(_args(["snapshooter", "tree"]))

    assert exc.value.code == 1
    assert "No project is open" in capsys.readouterr().err


def test_a_pipe_failure_exits_one(pipe, capsys):
    pipe.raises = RuntimeError("no IDE answered")

    with pytest.raises(SystemExit) as exc:
        handler.dispatch_snapshooter(_args(["snapshooter", "tree"]))

    assert exc.value.code == 1
    assert "no IDE answered" in capsys.readouterr().err
