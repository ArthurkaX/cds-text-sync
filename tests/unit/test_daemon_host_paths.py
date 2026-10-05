# -*- coding: utf-8 -*-
"""Every host path the daemon opens is refused unless it is absolute.

The daemon runs inside CODESYS.exe, whose working directory is the IDE's
installation directory, so a relative path it opens silently lands next to the
IDE (or fails with an UnauthorizedAccessException).  ``_daemon_path`` in
``cds_cli._cli_io`` makes the CLI's host paths absolute before they cross the
pipe; ``ide_path_guards.host_path_error`` is the daemon's own answer for any
other client, and the two share the exact message.

The refusal is the *first* thing each handler does, so it is not buried under
"no project open" or "not connected": that is what these tests pin.
"""

import os
import sys

import pytest

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import ide_handlers_build as build_handlers  # noqa: E402
import ide_handlers_plc as plc_handlers  # noqa: E402
import ide_handlers_project as project_handlers  # noqa: E402
import ide_handlers_snapshooter as snapshooter_handlers  # noqa: E402
import ide_handlers_sync as sync_handlers  # noqa: E402
import ide_path_guards as guards  # noqa: E402


# ── the helper ──────────────────────────────────────────────────────────────


def test_relative_paths_are_named_in_the_error():
    error = guards.host_path_error({"out": "snap.json"}, "out")
    assert error == {"ok": False, "error": "path must be absolute: out snap.json"}


def test_absolute_paths_pass():
    absolute = os.path.join(os.sep, "work", "snap.json")
    assert guards.host_path_error({"out": absolute}, "out") is None


def test_an_unset_path_is_not_relative():
    """An empty option stays empty so the caller can omit the parameter."""
    assert guards.host_path_error({"output": ""}, "output") is None
    assert guards.host_path_error({}, "output") is None


def test_the_first_relative_name_wins():
    """The message names one parameter; the order is the caller's."""
    error = guards.host_path_error({"a": "one", "b": "two"}, "a", "b")
    assert error["error"] == "path must be absolute: a one"


# ── every handler that opens a host path refuses a relative one ─────────────


# (handler, params, the parameter the caller has to fix)
_GUARDED = [
    (build_handlers._cmd_export, {"output": "snap.xml"}, "output"),
    (build_handlers._cmd_build, {"output": "build.log"}, "output"),
    (build_handlers._cmd_export_csv, {"output": "vars.csv"}, "output"),
    (build_handlers._cmd_export_st, {"output": "st"}, "output"),
    (build_handlers._cmd_application_tree, {"output": "tree.json"}, "output"),
    (sync_handlers._cmd_sync_compare, {"against": "snap.xml"}, "against"),
    (project_handlers._cmd_project_open, {"path": "plant.project"}, "path"),
    (plc_handlers._cmd_plc_log, {"output": "logs"}, "output"),
    (plc_handlers._cmd_plc_download, {"dest": "local.bin"}, "dest"),
    (plc_handlers._cmd_plc_upload, {"src": "local.bin"}, "src"),
    (snapshooter_handlers._cmd_snapshooter, {"action": "take", "out": "p.json"}, "out"),
]


@pytest.mark.parametrize(
    "handler,params,name",
    _GUARDED,
    ids=[h.__name__ for h, _p, _n in _GUARDED],
)
def test_a_relative_host_path_is_refused(handler, params, name):
    result = handler(params)

    assert result["ok"] is False
    assert result["error"] == "path must be absolute: {0} {1}".format(
        name, params[name]
    )


def test_the_refusal_comes_before_touching_the_project():
    """No daemon state is installed in this module on purpose: the refusal must
    not depend on a project being open, or the real cause would be hidden."""
    result = build_handlers._cmd_export({"output": "week/snap.xml"})
    assert result["error"] == "path must be absolute: output week/snap.xml"
