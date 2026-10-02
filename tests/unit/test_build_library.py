# -*- coding: utf-8 -*-
"""``build`` on a library project: check, and optionally install."""

import os

from test_build_message_identifier import build


class _Msg:
    def __init__(self, severity, text="msg"):
        self.severity = severity
        self.text = text
        self.prefix = "C"
        self.number = 1
        self.object = None


class _System:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.cleared = 0

    def clear_messages(self, guid):
        self.cleared += 1

    def get_message_objects(self, guid):
        return self.messages


class _Project:
    def __init__(self, check_result=True, fail_at=None):
        self.calls = []
        self.check_result = check_result
        self.fail_at = fail_at

    def _step(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(name + " boom")

    def check_all_pool_objects(self):
        self._step("check")
        return self.check_result

    def save(self):
        self._step("save")

    def save_as_compiled_library(self, path):
        self._step("compile")
        with open(path, "wb") as handle:
            handle.write(b"x")


class _Manager:
    repositories = ["LibRepository(User, C:\\u)", "LibRepository(System, C:\\s)"]

    def __init__(self):
        self.installed = []

    def install_library(self, path, repository, overwrite):
        assert os.path.exists(path)
        self.installed.append((os.path.basename(path), repository, overwrite))


# _build_library derives the compiled-library name with os.path.basename, so
# the fixture path has to use the separator of the host running the test.
LIBRARY_PROJECT = os.path.join("libs", "example_lib.library")


def _setup(monkeypatch, manager=None):
    monkeypatch.setattr(build, "_project_file", lambda project: LIBRARY_PROJECT)
    monkeypatch.setattr(build, "_library_manager", lambda: manager)


def test_library_detected_by_file_type(monkeypatch):
    monkeypatch.setattr(build, "_project_file", lambda project: r"X:\a\b.LIBRARY")
    assert build._is_library_project(object())
    monkeypatch.setattr(build, "_project_file", lambda project: r"X:\a\b.project")
    assert not build._is_library_project(object())


def test_check_only_does_not_install(monkeypatch):
    manager = _Manager()
    _setup(monkeypatch, manager)
    project = _Project()
    result = build._build_library(project, _System(), {})
    assert result["ok"] is True
    assert result["data"]["kind"] == "library"
    assert result["data"]["installed"] is False
    assert project.calls == ["check"]
    assert manager.installed == []


def test_install_saves_compiles_installs_and_cleans_up(monkeypatch):
    manager = _Manager()
    _setup(monkeypatch, manager)
    project = _Project()
    result = build._build_library(project, _System(), {"install": True})
    assert result["ok"] is True
    assert result["data"]["installed"] is True
    assert project.calls == ["check", "save", "compile"]
    assert manager.installed == [("example_lib.compiled-library", _Manager.repositories[1], True)]
    assert not os.path.exists(result["data"]["compiled_library"])


def test_errors_block_install(monkeypatch):
    manager = _Manager()
    _setup(monkeypatch, manager)
    project = _Project()
    result = build._build_library(
        project, _System([_Msg("Error")]), {"install": True}
    )
    assert result["ok"] is False
    assert result["data"]["errors"] == 1
    assert project.calls == ["check"]
    assert manager.installed == []


def test_check_returning_false_counts_as_error(monkeypatch):
    _setup(monkeypatch, _Manager())
    result = build._build_library(_Project(check_result=False), _System(), {})
    assert result["ok"] is False
    assert result["data"]["errors"] == 1


def test_missing_library_manager_is_reported(monkeypatch):
    _setup(monkeypatch, None)
    result = build._build_library(_Project(), _System(), {"install": True})
    assert result["ok"] is False
    assert "librarymanager" in result["data"]["install_error"]


def test_install_failure_is_reported_and_temp_file_removed(monkeypatch):
    manager = _Manager()
    _setup(monkeypatch, manager)
    project = _Project(fail_at="save")
    result = build._build_library(project, _System(), {"install": True})
    assert result["ok"] is False
    assert "save boom" in result["data"]["install_error"]
    assert result["data"]["installed"] is False
