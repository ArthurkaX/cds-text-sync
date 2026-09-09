# -*- coding: utf-8 -*-
"""Tests for daemon-driven project sync-folder configuration."""

import os
import sys
from types import SimpleNamespace

import pytest


_IDE_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "products",
        "codesys-host",
        "src",
        "ide_bridge",
    )
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

import ide_handlers_project as handlers


class _Info(object):
    def __init__(self):
        self.values = {}


class _Project(object):
    def __init__(self, path):
        self.path = path
        self.info = _Info()
        self.save_calls = 0

    def get_project_info(self):
        return self.info

    def save(self):
        self.save_calls += 1


class _Projects(object):
    def __init__(self, project):
        self.primary = project


def _install_project(monkeypatch, project):
    monkeypatch.setattr(
        sys,
        "_codesys_daemon_loop",
        {"projects": _Projects(project), "started_at": "now"},
        raising=False,
    )


def test_omitted_path_uses_saved_project_directory_and_can_save(monkeypatch, tmp_path):
    project_file = tmp_path / "Demo.project"
    project = _Project(str(project_file))
    _install_project(monkeypatch, project)

    result = handlers._cmd_set_sync_folder({"save": True})

    assert result["ok"] is True
    assert project.info.values["cds-sync-folder"] == "."
    assert result["data"]["automatic"] is True
    assert result["data"]["resolved_sync_folder"] == os.path.normpath(str(tmp_path))
    assert result["data"]["saved"] is True
    assert project.save_calls == 1


def test_explicit_unicode_absolute_path_is_stored_without_saving(monkeypatch, tmp_path):
    project = _Project(str(tmp_path / "Demo.project"))
    _install_project(monkeypatch, project)
    sync_folder = os.path.abspath(str(tmp_path / "Синхронизация"))

    result = handlers._cmd_set_sync_folder({"path": sync_folder})

    assert result["ok"] is True
    assert project.info.values["cds-sync-folder"] == os.path.normpath(sync_folder)
    assert result["data"]["saved"] is False
    assert "unsaved" in result["data"]
    assert project.save_calls == 0


@pytest.mark.parametrize("path", ["sync", "../sync", "./../sync", r"..\sync"])
def test_relative_setting_round_trips_through_daemon(monkeypatch, tmp_path, path):
    import ide_daemon_helpers as helpers

    project = _Project(str(tmp_path / "Demo.project"))
    _install_project(monkeypatch, project)

    result = handlers._cmd_set_sync_folder({"path": path})

    assert result["ok"] is True
    expected = os.path.normpath(os.path.join(str(tmp_path), path.replace("\\", os.sep)))
    assert result["data"]["resolved_sync_folder"] == expected
    assert helpers._get_sync_folder() == (expected, None)
    assert project.save_calls == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
@pytest.mark.parametrize("path", ["D:sync", "C:", r"\sync", "/sync", "bad\x00path"])
def test_invalid_setting_preserves_existing_property(monkeypatch, tmp_path, path):
    project = _Project(str(tmp_path / "Demo.project"))
    project.info.values["cds-sync-folder"] = "original"
    _install_project(monkeypatch, project)

    result = handlers._cmd_set_sync_folder({"path": path, "save": True})

    assert result["ok"] is False
    assert project.info.values == {"cds-sync-folder": "original"}
    assert project.save_calls == 0


def test_automatic_path_requires_a_saved_project(monkeypatch):
    project = _Project("")
    _install_project(monkeypatch, project)

    result = handlers._cmd_set_sync_folder({})

    assert result["ok"] is False
    assert "project has not been saved" in result["error"]


@pytest.mark.parametrize("saved", [True, False])
def test_menu_validates_relative_path_before_updating_properties(monkeypatch, tmp_path, saved):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project") if saved else "")
    project.info.values["cds-sync-folder"] = "original"
    errors = []
    runtime = SimpleNamespace(
        system=SimpleNamespace(ui=SimpleNamespace(browse_directory_dialog=lambda *args: "../sync")),
        ui=SimpleNamespace(error=errors.append, info=lambda message: None),
    )
    monkeypatch.setitem(sys.modules, "codesys_ui", SimpleNamespace(show_directory_choice_dialog=lambda *args: "yes"))

    result = directory.set_base_directory(runtime, _Projects(project))

    if saved:
        assert result["status"] == "ok"
        assert result["relative"] is True
        assert project.info.values["cds-sync-folder"] == os.path.normpath("../sync")
        assert not errors
    else:
        assert result["status"] == "error"
        assert errors
        assert project.info.values == {"cds-sync-folder": "original"}
