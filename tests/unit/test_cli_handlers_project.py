# -*- coding: utf-8 -*-
"""
test_cli_handlers_project.py -- Tests for the project/pou subcommand dispatch.

dispatch_project / dispatch_pou were extracted verbatim from main(). These
tests pin the routing: each project_action calls the matching cmd_* handler
and forwards the relevant argparse attributes.
"""

import argparse
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli import _cli_handlers_project as h


@pytest.fixture
def calls(monkeypatch):
    """Record cmd_* invocations instead of hitting the daemon."""
    recorded = {}

    def _stub(name):
        def _fn(**kwargs):
            recorded[name] = kwargs

        return _fn

    for fn_name in (
        "cmd_project_info",
        "cmd_project_tree",
        "cmd_project_read",
        "cmd_project_open",
        "cmd_project_list",
        "cmd_compare",
        "cmd_pou_delete",
    ):
        monkeypatch.setattr(h, fn_name, _stub(fn_name))
    return recorded


def _args(**kwargs):
    return argparse.Namespace(**kwargs)


def test_info_routes_to_cmd_project_info(calls):
    h.dispatch_project(_args(project_action="info"), use_reverse=True)
    assert calls["cmd_project_info"] == {"use_reverse": True}


def test_tree_forwards_depth(calls):
    h.dispatch_project(_args(project_action="tree", depth=3), use_reverse=True)
    assert calls["cmd_project_tree"] == {"depth": 3, "use_reverse": True}


def test_read_forwards_path_name_guid(calls):
    h.dispatch_project(
        _args(project_action="read", path="p", name="n", guid="g"), use_reverse=False
    )
    assert calls["cmd_project_read"] == {
        "path": "p",
        "name": "n",
        "guid": "g",
        "use_reverse": False,
    }


def test_compare_forwards_against(calls):
    h.dispatch_project(_args(project_action="compare", against="HEAD"), use_reverse=True)
    assert calls["cmd_compare"] == {"against": "HEAD", "use_reverse": True}


def test_unknown_action_is_noop(calls):
    h.dispatch_project(_args(project_action="does-not-exist"), use_reverse=True)
    assert calls == {}


def test_pou_delete_routes(calls):
    h.dispatch_pou(_args(pou_action="delete", name="MyPou", app="App"), use_reverse=True)
    assert calls["cmd_pou_delete"] == {
        "name": "MyPou",
        "app": "App",
        "use_reverse": True,
    }


# -- deprecation warnings -----------------------------------------------------


def test_duplicate_action_warns_with_replacement(calls, capsys):
    h.dispatch_project(_args(project_action="info"), use_reverse=True)
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "cts project info" in err
    assert "cts project-info" in err
    # still dispatches
    assert "cmd_project_info" in calls


def test_unique_action_does_not_warn(calls, capsys):
    h.dispatch_project(_args(project_action="list"), use_reverse=True)
    err = capsys.readouterr().err
    assert "[WARN]" not in err
    assert "cmd_project_list" in calls


def test_pou_delete_warns(calls, capsys):
    h.dispatch_pou(_args(pou_action="delete", name="X", app=""), use_reverse=True)
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "cts delete-pou" in err


def test_every_deprecated_action_maps_to_a_real_top_level_command():
    # Guard: the replacement strings must name commands that actually exist.
    from cli._cli_parser import build_parser

    parser = build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    choices = set(sub.choices)
    for replacement in h._DEPRECATED_PROJECT_ACTIONS.values():
        cmd = replacement.split(" ", 1)[1]  # strip the "cts " prefix
        assert cmd in choices, "{0} is not a real top-level command".format(cmd)

