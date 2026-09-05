# -*- coding: utf-8 -*-
"""Tests for daemon-driven project sync-folder configuration."""

import os
import sys


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


def test_bare_relative_path_is_rejected(monkeypatch, tmp_path):
    project = _Project(str(tmp_path / "Demo.project"))
    _install_project(monkeypatch, project)

    result = handlers._cmd_set_sync_folder({"path": "sync"})

    assert result["ok"] is False
    assert "start with './'" in result["error"]
    assert "cds-sync-folder" not in project.info.values


def test_automatic_path_requires_a_saved_project(monkeypatch):
    project = _Project("")
    _install_project(monkeypatch, project)

    result = handlers._cmd_set_sync_folder({})

    assert result["ok"] is False
    assert "project has not been saved" in result["error"]
