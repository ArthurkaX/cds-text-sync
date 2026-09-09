# -*- coding: utf-8 -*-
"""
test_project_file_path.py — Regression guard for relative cds-sync-folder anchoring.

Root cause of GH #61: IronPython attribute access is case-sensitive and the
canonical CODESYS ScriptEngine attribute is the lowercase ``path``. Older call
sites tried only ["filename", "FileName", "FullName", "Path"], so on builds such
as SP18 (which expose the path only via lowercase ``path``) the relative sync
folder was never anchored and fell through to a misleading "Access denied".

``_project_file_path`` centralizes the case-insensitive lookup with lowercase
``path`` tried FIRST. These tests pin that contract.
"""

import os
import sys
from types import SimpleNamespace

import pytest

_IDE_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

import ide_daemon_state as state


class _LowerPathProject(object):
    """The SP18 shape: exposes ONLY lowercase ``path`` (the #61 regression)."""

    path = r"C:\Users\eddie\Desktop\Test\Untitled1.project"


class _PascalCaseProject(object):
    """Older/other builds: no lowercase ``path``, only PascalCase variants."""

    FullName = r"D:\projects\Sample.project"


class _NoPathProject(object):
    """Unsaved / path-less project: nothing usable."""

    pass


class _RaisingProject(object):
    """Attribute access raises — must be swallowed, not propagated."""

    @property
    def path(self):
        raise RuntimeError("no path on this build")

    filename = r"E:\fallback\Fallback.project"


def test_lowercase_path_is_resolved():
    # The exact SP18 regression from GH #61.
    assert (
        state._project_file_path(_LowerPathProject())
        == r"C:\Users\eddie\Desktop\Test\Untitled1.project"
    )


def test_pascalcase_fallback_still_works():
    assert state._project_file_path(_PascalCaseProject()) == r"D:\projects\Sample.project"


def test_missing_path_returns_empty_string():
    # Empty (not None) so os.path.dirname("") is "" and callers can loud-fail.
    assert state._project_file_path(_NoPathProject()) == ""


def test_raising_attribute_falls_through():
    assert state._project_file_path(_RaisingProject()) == r"E:\fallback\Fallback.project"


@pytest.mark.parametrize("configured", ["../sync", "./../sync", r"..\sync", "sync", "."])
@pytest.mark.parametrize("attribute", ["path", "FullName"])
def test_sync_consumers_ignore_process_directory(monkeypatch, tmp_path, configured, attribute):
    import codesys_utils
    import codesys_external_ui_launcher as launcher
    import ide_daemon_helpers as helpers
    import ide_handlers_project as handlers
    import project_snapshooter as snapshots

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    process_dir = tmp_path / "unrelated"
    process_dir.mkdir()
    monkeypatch.chdir(process_dir)
    info = SimpleNamespace(values={"cds-sync-folder": configured})
    project = SimpleNamespace(get_project_info=lambda: info)
    setattr(project, attribute, str(project_dir / "Demo.project"))
    projects = SimpleNamespace(primary=project)
    monkeypatch.setattr(sys, "_codesys_daemon_loop", {"projects": projects}, raising=False)
    monkeypatch.setattr(codesys_utils, "resolve_projects", lambda: projects)
    monkeypatch.setattr(snapshots, "_SNAPSHOOTER_SYNC", None)
    expected = os.path.normpath(os.path.join(str(project_dir), configured.replace("\\", os.sep)))

    assert helpers._get_sync_folder() == (expected, None)
    assert launcher.project_sync_folder(project) == (expected, None)
    assert handlers._sync_folder_for_project(project) == expected
    assert snapshots._sync_folder(project) == expected
    assert snapshots._resolve_log_sync_folder() == expected
    assert codesys_utils.load_base_dir() == (expected, None)
    assert list(process_dir.iterdir()) == []


@pytest.mark.parametrize("project_path", ["", "Demo.project", "   "])
@pytest.mark.parametrize("configured", ["../sync", "sync", ".", "   ", "bad\x00path"])
def test_unanchored_sync_folder_never_creates_a_directory(monkeypatch, tmp_path, project_path, configured):
    import codesys_utils
    import ide_daemon_helpers as helpers
    import codesys_external_ui_launcher as launcher
    import project_snapshooter as snapshots

    project = SimpleNamespace(path=project_path, get_project_info=lambda: SimpleNamespace(
        values={"cds-sync-folder": configured}))
    projects = SimpleNamespace(primary=project)
    monkeypatch.setattr(sys, "_codesys_daemon_loop", {"projects": projects}, raising=False)
    monkeypatch.setattr(codesys_utils, "resolve_projects", lambda: projects)
    monkeypatch.chdir(tmp_path)

    for result in (helpers._get_sync_folder(), codesys_utils.load_base_dir(), launcher.project_sync_folder(project)):
        assert result[0] is None
        assert result[1]
    with pytest.raises(ValueError):
        snapshots._sync_folder(project)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
@pytest.mark.parametrize("configured", [r"C:\Синхронизация\..\sync", r"\\server\share\sync", r"\\?\C:\sync"])
def test_absolute_windows_paths_do_not_require_saved_project(configured):
    import codesys_utils

    assert codesys_utils.resolve_sync_folder(configured, None) == os.path.normpath(configured)


@pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
@pytest.mark.parametrize("configured", ["D:sync", "C:", r"\sync", "/sync"])
def test_ambiguous_windows_roots_are_rejected(configured):
    import codesys_utils

    with pytest.raises(ValueError, match="fully qualified"):
        codesys_utils.resolve_sync_folder(configured, _LowerPathProject())
