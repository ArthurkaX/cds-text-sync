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
        _cli_handlers_visu, "_resolve_project_view", lambda sync_folder: ("PV", None)
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
