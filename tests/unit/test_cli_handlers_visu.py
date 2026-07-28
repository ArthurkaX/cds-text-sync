# -*- coding: utf-8 -*-
"""
test_cli_handlers_visu.py -- Tests for ``cli._cli_handlers_visu.dispatch_visu``.

The visu subcommand dispatch was extracted verbatim from the main() CLI
dispatcher. These tests pin the routing contract: which cli.visu.commands
function each visu_action calls, the --add param mapping, and the
required-argument error paths.
"""

import argparse
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli import _cli_handlers_visu
from cli.visu import commands as visu_cmds


@pytest.fixture
def calls(monkeypatch):
    """Record calls to cli.visu.commands functions instead of running them.

    Also stub _resolve_project_view so no project-view directory is touched.
    """
    recorded = {}

    def _stub(name):
        def _fn(**kwargs):
            recorded[name] = kwargs

        return _fn

    for fn_name in (
        "list_types",
        "new_svg",
        "create_screen",
        "add_element",
        "list_screen",
        "check_screen",
        "describe",
        "from_svg",
        "to_svg",
        "capture_frame",
    ):
        monkeypatch.setattr(visu_cmds, fn_name, _stub(fn_name))

    monkeypatch.setattr(
        _cli_handlers_visu,
        "_resolve_project_view",
        lambda sync_folder, **kw: ("PV", None),
    )
    return recorded


def _args(**kwargs):
    return argparse.Namespace(**kwargs)


def test_types_routes_to_list_types(calls):
    _cli_handlers_visu.dispatch_visu(_args(visu_action="types", sync_folder=""))
    assert "list_types" in calls


def test_add_maps_params_and_skips_blanks(calls):
    _cli_handlers_visu.dispatch_visu(
        _args(
            visu_action="add",
            sync_folder="",
            screen="Screen1",
            type="button",
            folder="",
            x="10",
            y="20",
            w="100",
            h="",
            shape=None,
            fill="red",
            frame=None,
            corner_radius=None,
            border_width=None,
            angle=None,
            tooltip=None,
        )
    )
    params = calls["add_element"]["params"]
    # w -> width; blank h and None fields are dropped.
    assert params == {"x": "10", "y": "20", "width": "100", "fill": "red"}
    assert calls["add_element"]["project_view_dir"] == "PV"


def test_add_requires_screen(calls):
    with pytest.raises(SystemExit) as exc:
        _cli_handlers_visu.dispatch_visu(
            _args(visu_action="add", sync_folder="", screen="", type="button")
        )
    assert exc.value.code == 1
    assert "add_element" not in calls


def test_to_svg_requires_screen(calls):
    with pytest.raises(SystemExit):
        _cli_handlers_visu.dispatch_visu(
            _args(visu_action="to-svg", sync_folder="", screen="", folder="", out="")
        )


def test_a_screen_named_with_name_is_pointed_at_screen(calls, capsys):
    """`check --name X` must say which flag carries the screen name.

    --name belongs to screen *creation*; the subcommands that work on an
    existing screen ignore it. Answering `check --name T_Sensors` with a bare
    "--screen is required" leaves an author looking at the name they just
    typed and a message saying they gave none.
    """
    with pytest.raises(SystemExit) as exc:
        _cli_handlers_visu.dispatch_visu(
            _args(
                visu_action="check",
                sync_folder="",
                screen="",
                name="T_Sensors",
                folder="",
            )
        )
    assert exc.value.code == 1
    assert "check_screen" not in calls
    err = capsys.readouterr().err
    assert "--screen T_Sensors" in err
    assert "--name" in err


# -- Offline sketch commands ---------------------------------------------------
#
# `lint` and `preview` grade a file. They consult the daemon only to pick up an
# optional project-level visu.css, so with no IDE running they must come back
# promptly and say nothing about it -- these are the first commands a new user
# runs, usually before CODESYS is even open.


def _no_daemon(monkeypatch, record):
    """Make the daemon call fail the way an absent IDE does, recording timeout."""
    from cli import _cli_handlers_vars

    def _fail(method, params, timeout=30):
        record["timeout"] = timeout
        raise RuntimeError("Timeout ({0}s) waiting for IDE to connect".format(timeout))

    monkeypatch.setattr(_cli_handlers_vars, "send_command_reverse", _fail)


def test_optional_project_view_is_silent_without_daemon(monkeypatch, capsys):
    _no_daemon(monkeypatch, {})
    assert _cli_handlers_visu._optional_project_view("") is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_optional_project_view_does_not_wait_the_full_daemon_timeout(monkeypatch):
    record = {}
    _no_daemon(monkeypatch, record)
    _cli_handlers_visu._optional_project_view("")
    # The project commands wait 10s; a sketch command must not.
    assert record["timeout"] <= 3


def test_project_commands_still_report_a_missing_daemon(monkeypatch, capsys):
    """The quiet path is opt-in: the default still explains itself."""
    from cli import _cli_handlers_vars

    _no_daemon(monkeypatch, {})
    with pytest.raises(SystemExit):
        _cli_handlers_vars._resolve_project_view("")
    assert "Could not get sync folder from daemon" in capsys.readouterr().err
