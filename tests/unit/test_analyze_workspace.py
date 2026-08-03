"""
test_analyze_workspace.py - WorkspaceResolver priority and errors.
"""

import os

import pytest

from cds_text_sync.analyze.workspace import (
    WorkspaceError,
    WorkspaceResolver,
)

from analyze_helpers import fixture_project_view


def _make_workspace(tmp_path, with_config=False):
    root = tmp_path / "sync"
    (root / "project-view").mkdir(parents=True)
    if with_config:
        (root / "cts-analyze.toml").write_text("[analyze]\n")
    return str(root)


def test_explicit_workspace(tmp_path):
    root = _make_workspace(tmp_path)
    ws = WorkspaceResolver(workspace=root).resolve()
    assert ws.root == os.path.abspath(root)
    assert ws.project_view == os.path.abspath(os.path.join(root, "project-view"))
    assert ws.state_dir == os.path.abspath(os.path.join(root, ".cts-analyze"))


def test_workspace_and_project_view_conflict(tmp_path):
    root = _make_workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        WorkspaceResolver(workspace=root, project_view=root).resolve()


def test_missing_workspace_is_an_error(tmp_path):
    with pytest.raises(WorkspaceError):
        WorkspaceResolver(workspace=str(tmp_path / "nope")).resolve()


def test_project_view_without_project_view_dir_is_an_error(tmp_path):
    root = str(tmp_path / "sync")
    os.makedirs(root)
    with pytest.raises(WorkspaceError):
        WorkspaceResolver(workspace=root).resolve()


def test_explicit_project_view(tmp_path):
    pv = fixture_project_view()
    ws = WorkspaceResolver(project_view=pv).resolve()
    assert os.path.basename(ws.root) == "analyze"
    assert os.path.basename(ws.project_view) == "project-view"


def test_nearest_ancestor_with_config_wins(tmp_path):
    root = tmp_path / "sync"
    (root / "project-view").mkdir(parents=True)
    (root / "cts-analyze.toml").write_text("[analyze]\n")
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    ws = WorkspaceResolver(cwd=str(nested)).resolve()
    assert ws.root == os.path.abspath(str(root))


def test_project_view_in_cwd_is_found(tmp_path):
    root = tmp_path / "sync"
    (root / "project-view").mkdir(parents=True)
    ws = WorkspaceResolver(cwd=str(root)).resolve()
    assert os.path.basename(ws.project_view) == "project-view"


def test_no_workspace_anywhere_is_a_clear_error(tmp_path):
    with pytest.raises(WorkspaceError) as excinfo:
        WorkspaceResolver(cwd=str(tmp_path)).resolve()
    assert "--workspace" in str(excinfo.value)


def test_config_path_is_detected(tmp_path):
    root = _make_workspace(tmp_path, with_config=True)
    ws = WorkspaceResolver(workspace=root).resolve()
    assert ws.config_path == os.path.join(root, "cts-analyze.toml")
