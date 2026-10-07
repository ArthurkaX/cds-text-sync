# -*- coding: utf-8 -*-
"""
test_project_close_api.py — closing the active project.

``_cmd_project_close`` used to fall back to ``projects.close(project)`` when the
project object had no ``close``. IScriptProjects has no such method -- the API
snapshot lists all/convert/create/get_by_path/open/open_archive/primary -- so
the fallback could only ever raise. The handler now says what is wrong instead
of calling a method that does not exist.

The snapshot checker (tools/check_script_api.py) is what found it; the entry in
its KNOWN_MISMATCHES map is gone with this fix.
"""

import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _path in (
    _ROOT,
    os.path.join(_ROOT, "shared", "src"),
    os.path.join(_ROOT, "products", "codesys-host", "src", "ide_bridge"),
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import ide_handlers_project as handlers  # noqa: E402

_STATE_KEY = "_codesys_daemon_loop"


class _Project(object):
    """A project object with or without ``close``, as the API allows."""

    def __init__(self, has_close=True, name="Demo"):
        self.name = name
        self.closed = 0
        if has_close:
            self.close = self._close

    def _close(self):
        self.closed += 1


class _Projects(object):
    """IScriptProjects: no close().  Any call to one is an AttributeError."""

    def __init__(self):
        self.calls = []


@pytest.fixture
def daemon_state(monkeypatch):
    def _install(project):
        projects = _Projects()
        monkeypatch.setattr(
            sys, _STATE_KEY, {"projects": projects, "system": object()}, raising=False
        )
        monkeypatch.setattr(handlers, "_get_active_project", lambda: (project, None))
        return projects

    return _install


def test_the_active_project_is_closed_through_its_own_close(daemon_state):
    project = _Project()
    daemon_state(project)

    result = handlers._cmd_project_close()

    assert result["ok"] is True
    assert "closed" in result["data"]
    assert project.closed == 1


def test_a_project_without_close_is_an_honest_error_not_a_wrong_call(daemon_state):
    project = _Project(has_close=False)
    projects = daemon_state(project)

    result = handlers._cmd_project_close()

    assert result["ok"] is False
    assert "no close()" in result["error"]
    assert "IScriptProject" in result["error"]
    # The dead fallback would have called projects.close(...): AttributeError.
    assert not hasattr(projects, "close")
