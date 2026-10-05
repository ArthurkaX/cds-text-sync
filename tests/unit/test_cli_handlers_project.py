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

from cds_cli import _cli_handlers_project as h


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
    h.dispatch_project(_args(project_action="info"))
    assert calls["cmd_project_info"] == {}


def test_tree_forwards_depth(calls):
    h.dispatch_project(_args(project_action="tree", depth=3))
    assert calls["cmd_project_tree"] == {"depth": 3}


def test_read_forwards_path_name_guid(calls):
    h.dispatch_project(
        _args(project_action="read", path="p", name="n", guid="g")
    )
    assert calls["cmd_project_read"] == {"path": "p", "name": "n", "guid": "g"}


def test_compare_forwards_against(calls):
    h.dispatch_project(_args(project_action="compare", against="HEAD"))
    assert calls["cmd_compare"] == {"against": "HEAD"}


def test_compare_sends_sync_compare_to_the_daemon(monkeypatch):
    """`compare` is the CRC alias; the snapshot compare is `sync_compare`."""
    from cds_cli import _cli_io

    seen = {}

    def _fake_send(method, params, timeout=30):
        seen["method"] = method
        seen["params"] = params
        return {"ok": True, "data": {}}

    monkeypatch.setattr(_cli_io, "send_command_reverse", _fake_send)
    h.cmd_compare(against="snap/latest.xml")
    assert seen["method"] == "sync_compare"
    # A HOST path: the daemon opens it inside CODESYS, so it is made absolute
    # before it crosses the pipe (see _daemon_path).
    assert seen["params"] == {"against": os.path.abspath("snap/latest.xml")}


def test_compare_without_against_asks_for_the_latest_snapshot(monkeypatch):
    """`--against` is optional: the daemon falls back to the newest in .dump/."""
    from cds_cli import _cli_io

    seen = {}

    def _fake_send(method, params, timeout=30):
        seen["method"] = method
        seen["params"] = params
        return {"ok": True, "data": {}}

    monkeypatch.setattr(_cli_io, "send_command_reverse", _fake_send)
    h.cmd_compare()
    assert seen["method"] == "sync_compare"
    assert seen["params"] == {"against": ""}


def test_sync_compare_reaches_the_handler_that_reads_against():
    """Guard the CLI-side method against a host-side re-route [A1]."""
    from pathlib import Path

    bridge = (
        Path(__file__).resolve().parents[2]
        / "products"
        / "codesys-host"
        / "src"
        / "ide_bridge"
    )
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    import command_registry

    assert command_registry.DISPATCH_SPECS["sync_compare"] == (
        "direct",
        "_cmd_sync_compare",
    )


def test_unknown_action_is_noop(calls):
    h.dispatch_project(_args(project_action="does-not-exist"))
    assert calls == {}


def test_no_handler_keeps_the_dead_use_reverse_flag():
    """It was threaded through every handler and read by none of them."""
    import inspect

    from cds_cli import _cli_io

    assert "use_reverse" not in inspect.getfullargspec(_cli_io._project_command).args
    for name, member in vars(h).items():
        if name.startswith("cmd_") and callable(member):
            assert "use_reverse" not in inspect.getfullargspec(member).args, name


def test_pou_delete_routes(calls):
    h.dispatch_pou(_args(pou_action="delete", name="MyPou", app="App"))
    assert calls["cmd_pou_delete"] == {"name": "MyPou", "app": "App"}


# -- deprecation warnings -----------------------------------------------------


def test_duplicate_action_warns_with_replacement(calls, capsys):
    h.dispatch_project(_args(project_action="info"))
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "cts project info" in err
    assert "cts project-info" in err
    # still dispatches
    assert "cmd_project_info" in calls


def test_unique_action_does_not_warn(calls, capsys):
    h.dispatch_project(_args(project_action="list"))
    err = capsys.readouterr().err
    assert "[WARN]" not in err
    assert "cmd_project_list" in calls


def test_pou_delete_warns(calls, capsys):
    h.dispatch_pou(_args(pou_action="delete", name="X", app=""))
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "cts delete-pou" in err


def test_every_deprecated_action_maps_to_a_real_top_level_command():
    # Guard: the replacement strings must name commands that actually exist.
    from cds_cli._cli_parser import build_parser

    parser = build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    choices = set(sub.choices)
    for replacement in h._DEPRECATED_PROJECT_ACTIONS.values():
        cmd = replacement.split(" ", 1)[1]  # strip the "cts " prefix
        assert cmd in choices, "{0} is not a real top-level command".format(cmd)



# ── host paths are absolutised before they cross the pipe ──────────────────
#
# The daemon runs inside CODESYS.exe; a relative path it opens lands in the
# IDE's installation directory. `_daemon_path` is the one place the CLI fixes
# that, and every host path the daemon opens goes through it.


@pytest.fixture
def sent(monkeypatch):
    from cds_cli import _cli_io

    seen = {}

    def _fake_send(method, params, timeout=30):
        seen["method"] = method
        seen["params"] = params
        return {"ok": True, "data": {}}

    monkeypatch.setattr(_cli_io, "send_command_reverse", _fake_send)
    return seen


def test_project_open_sends_an_absolute_host_path(sent):
    h.cmd_project_open(path="projects/plant.project")
    assert sent["method"] == "project_open"
    assert sent["params"] == {"path": os.path.abspath("projects/plant.project")}


def test_project_snapshot_sends_an_absolute_output_path(sent):
    h.cmd_project_snapshot(path="snap/project.xml")
    assert sent["method"] == "export"
    assert sent["params"] == {"output": os.path.abspath("snap/project.xml")}


def test_project_snapshot_without_a_path_omits_output(sent):
    h.cmd_project_snapshot(path="")
    assert sent["method"] == "export"
    assert sent["params"] == {}


def test_an_absolute_host_path_is_left_alone(sent):
    absolute = os.path.join(os.sep, "work", "plant.project")
    h.cmd_project_open(path=absolute)
    h.cmd_compare(against=absolute)
    assert sent["params"] == {"against": absolute}
