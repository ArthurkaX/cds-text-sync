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


def _menu_runtime(errors, browse_result=None, headless=True, infos=None):
    return SimpleNamespace(
        is_headless=headless,
        projects=None,
        caller_globals={},
        system=SimpleNamespace(
            ui=SimpleNamespace(
                browse_directory_dialog=lambda *args: browse_result,
                query_string=lambda message, default: default,
            )
        ),
        ui=SimpleNamespace(
            error=errors.append,
            info=(infos.append if infos is not None else (lambda message: None)),
        ),
    )


def _install_dialog(monkeypatch, answer):
    """Stub the sync-folder dialog, recording the arguments it was offered."""
    seen = {}

    def dialog(title, suggestion, browse=None, query=None):
        seen["title"] = title
        seen["suggestion"] = suggestion
        seen["browse"] = browse
        return answer(browse) if callable(answer) else answer

    monkeypatch.setitem(
        sys.modules, "codesys_ui", SimpleNamespace(show_sync_folder_dialog=dialog)
    )
    return seen


@pytest.mark.parametrize("saved", [True, False])
def test_menu_validates_relative_path_before_updating_properties(monkeypatch, tmp_path, saved):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project") if saved else "")
    project.info.values["cds-sync-folder"] = "original"
    errors = []
    _install_dialog(monkeypatch, "../sync")

    result = directory.set_base_directory(_menu_runtime(errors), _Projects(project))

    if saved:
        assert result["status"] == "ok"
        assert result["relative"] is True
        assert project.info.values["cds-sync-folder"] == os.path.normpath("../sync")
        assert not errors
    else:
        assert result["status"] == "error"
        assert errors
        assert project.info.values == {"cds-sync-folder": "original"}


def test_menu_suggests_a_relative_folder_named_after_the_project(monkeypatch, tmp_path):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project"))
    _install_project(monkeypatch, project)
    errors = []
    seen = _install_dialog(monkeypatch, lambda browse: seen["suggestion"])

    result = directory.set_base_directory(_menu_runtime(errors), _Projects(project))

    assert seen["suggestion"] == "Demo-cts"
    assert result["status"] == "ok"
    assert result["relative"] is True
    assert project.info.values["cds-sync-folder"] == "Demo-cts"
    # Accepting the suggestion must not create anything: load_base_dir does that
    # on first use, so a cancelled workflow leaves no empty folder behind.
    assert not (tmp_path / "Demo-cts").exists()
    assert not errors


def test_menu_prefers_the_configured_folder_over_the_suggestion(monkeypatch, tmp_path):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project"))
    project.info.values["cds-sync-folder"] = "existing"
    seen = _install_dialog(monkeypatch, "existing")

    directory.set_base_directory(_menu_runtime([]), _Projects(project))

    assert seen["suggestion"] == "existing"


def test_menu_suggests_the_project_directory_when_unsaved(monkeypatch):
    import codesys_directory_operation as directory

    project = _Project("")
    seen = _install_dialog(monkeypatch, None)

    result = directory.set_base_directory(_menu_runtime([]), _Projects(project))

    assert seen["suggestion"] == "."
    assert result["status"] == "cancelled"


@pytest.mark.parametrize(
    "browsed, expected",
    [
        ("Demo-cts", "Demo-cts"),
        (os.path.join("nested", "deeper"), os.path.join("nested", "deeper")),
        (".", "."),
    ],
)
def test_browsing_inside_the_project_stores_a_relative_path(
    monkeypatch, tmp_path, browsed, expected
):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project"))
    picked = os.path.abspath(str(tmp_path / browsed)) if browsed != "." else str(tmp_path)
    runtime = _menu_runtime([], browse_result=picked)
    _install_dialog(monkeypatch, lambda browse: browse())

    result = directory.set_base_directory(runtime, _Projects(project))

    assert result["status"] == "ok"
    assert project.info.values["cds-sync-folder"] == expected


def test_browsing_outside_the_project_keeps_the_absolute_path(monkeypatch, tmp_path):
    import codesys_directory_operation as directory

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    elsewhere = os.path.abspath(str(tmp_path / "elsewhere"))
    project = _Project(str(project_dir / "Demo.project"))
    runtime = _menu_runtime([], browse_result=elsewhere)
    _install_dialog(monkeypatch, lambda browse: browse())

    result = directory.set_base_directory(runtime, _Projects(project))

    assert result["status"] == "ok"
    assert result["relative"] is False
    assert project.info.values["cds-sync-folder"] == os.path.normpath(elsewhere)


def test_dialog_falls_back_to_a_text_query_without_windows_forms(monkeypatch):
    """The real dialog with Windows Forms unavailable, as in a --NoUI session.

    Forms is never instantiated here: showing it would need a live IDE window.
    """
    import codesys_ui

    monkeypatch.setattr(codesys_ui, "Form", None)
    asked = {}

    def query(message, default):
        asked["message"] = message
        asked["default"] = default
        return "typed-folder"

    assert codesys_ui.show_sync_folder_dialog("t", "Demo-cts", query=query) == "typed-folder"
    assert asked["default"] == "Demo-cts"
    assert "relative" in asked["message"].lower()
    # No query available and no Forms: cancel rather than raise.
    assert codesys_ui.show_sync_folder_dialog("t", "Demo-cts") is None


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("Demo", "Demo-cts"),
        ("fio-sorting-weight", "fio-sorting-weight-cts"),
        ("My Project", "My-Project-cts"),
        ("a  b", "a-b-cts"),
        ("Сортировка", "Сортировка-cts"),
        ("bad<>name", "badname-cts"),
        ("<>", "cts"),
    ],
)
def test_suggested_folder_name(tmp_path, stem, expected):
    import codesys_utils

    project = _Project(str(tmp_path / (stem + ".project")))

    assert codesys_utils.suggest_sync_folder(project) == expected


def test_suggested_folder_is_empty_without_a_saved_project():
    import codesys_utils

    assert codesys_utils.suggest_sync_folder(_Project("")) == ""
    assert codesys_utils.suggest_sync_folder(_Project("Demo.project")) == ""


def _stub_setup(monkeypatch, project, outcome="ok", stored="Demo-cts"):
    """Replace the folder dialog flow with its result, recording the calls."""
    import codesys_directory_operation as directory

    calls = []

    def fake_set_base_directory(runtime, projects_obj):
        calls.append(runtime)
        if outcome == "ok":
            project.info.values["cds-sync-folder"] = stored
        return {"status": outcome}

    monkeypatch.setattr(directory, "set_base_directory", fake_set_base_directory)
    return calls


def test_missing_folder_is_configured_in_place_instead_of_failing(monkeypatch, tmp_path):
    """An interactive command offers setup and then carries on with the result."""
    import codesys_utils

    project = _Project(str(tmp_path / "Demo.project"))
    projects = _Projects(project)
    monkeypatch.setattr(codesys_utils, "resolve_projects", lambda *a, **k: projects)
    calls = _stub_setup(monkeypatch, project)

    base_dir, error = codesys_utils.load_base_dir(_menu_runtime([], headless=False))

    assert error is None
    assert len(calls) == 1
    assert base_dir == os.path.normpath(str(tmp_path / "Demo-cts"))
    assert os.path.isdir(base_dir)


def test_cancelled_setup_reports_the_folder_as_unset(monkeypatch, tmp_path):
    import codesys_utils

    project = _Project(str(tmp_path / "Demo.project"))
    monkeypatch.setattr(codesys_utils, "resolve_projects", lambda *a, **k: _Projects(project))
    calls = _stub_setup(monkeypatch, project, outcome="cancelled")

    base_dir, error = codesys_utils.load_base_dir(_menu_runtime([], headless=False))

    assert base_dir is None
    assert "not set" in error
    assert len(calls) == 1


@pytest.mark.parametrize(
    "runtime",
    [None, _menu_runtime([], headless=True), SimpleNamespace()],
    ids=["no-runtime", "headless", "runtime-without-mode"],
)
def test_lookups_that_must_not_prompt_stay_silent(monkeypatch, tmp_path, runtime):
    """A modal dialog from a background or mid-operation lookup would ambush."""
    import codesys_utils

    project = _Project(str(tmp_path / "Demo.project"))
    monkeypatch.setattr(codesys_utils, "resolve_projects", lambda *a, **k: _Projects(project))
    calls = _stub_setup(monkeypatch, project)

    base_dir, error = codesys_utils.load_base_dir(runtime)

    assert base_dir is None
    assert "not set" in error
    assert calls == []


def test_setup_does_not_recurse_into_itself(monkeypatch, tmp_path):
    """set_base_directory chains into options, which looks the folder up again."""
    import codesys_utils

    project = _Project(str(tmp_path / "Demo.project"))
    monkeypatch.setattr(codesys_utils, "resolve_projects", lambda *a, **k: _Projects(project))
    runtime = _menu_runtime([], headless=False)
    calls = []

    import codesys_directory_operation as directory

    def reentrant_set_base_directory(rt, projects_obj):
        calls.append(rt)
        # Whatever runs inside setup must not be offered setup again.
        assert codesys_utils.load_base_dir(runtime) == (
            None,
            "Project sync directory is not set. Run Project_directory.py first.",
        )
        return {"status": "cancelled"}

    monkeypatch.setattr(directory, "set_base_directory", reentrant_set_base_directory)

    codesys_utils.load_base_dir(runtime)

    assert len(calls) == 1


def test_a_fresh_folder_continues_into_the_options_dialog(monkeypatch, tmp_path):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project"))
    _install_dialog(monkeypatch, "Demo-cts")
    opened = []
    monkeypatch.setattr(
        directory,
        "_open_project_options",
        lambda runtime: opened.append(runtime) or {"status": "ok"},
    )
    infos = []

    result = directory.set_base_directory(
        _menu_runtime([], headless=False, infos=infos), _Projects(project)
    )

    assert result["status"] == "ok"
    assert result["options"] == "ok"
    assert len(opened) == 1
    # The options dialog is the confirmation; a popup in between would be a
    # third window in a row.
    assert infos == []


def test_reconfiguring_a_configured_folder_skips_the_options_dialog(monkeypatch, tmp_path):
    import codesys_directory_operation as directory

    sync_folder = tmp_path / "Demo-cts"
    sync_folder.mkdir()
    (sync_folder / "cds-text-sync.json").write_text("{}", encoding="utf-8")
    project = _Project(str(tmp_path / "Demo.project"))
    _install_dialog(monkeypatch, "Demo-cts")
    monkeypatch.setattr(
        directory, "_open_project_options", lambda runtime: pytest.fail("should not chain")
    )
    infos = []

    result = directory.set_base_directory(
        _menu_runtime([], headless=False, infos=infos), _Projects(project)
    )

    assert result["status"] == "ok"
    assert "options" not in result
    assert infos and "relative" in infos[0]


def test_headless_setup_never_opens_the_options_dialog(monkeypatch, tmp_path):
    import codesys_directory_operation as directory

    project = _Project(str(tmp_path / "Demo.project"))
    _install_dialog(monkeypatch, "Demo-cts")
    monkeypatch.setattr(
        directory, "_open_project_options", lambda runtime: pytest.fail("should not chain")
    )

    result = directory.set_base_directory(
        _menu_runtime([], headless=True), _Projects(project)
    )

    assert result["status"] == "ok"
    assert "options" not in result
