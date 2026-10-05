# -*- coding: utf-8 -*-
"""The daemon's ``snapshooter`` handler contract.

``ide_handlers_snapshooter._cmd_snapshooter`` is the IronPython side of
``cts snapshooter``: it resolves the active project, dispatches one action to
the UI-free backend in ``project_snapshooter``, and turns every failure into
``{"ok": False, "error": ...}``.  The CODESYS project and the backend functions
are faked here, so the tests describe the handler's routing -- which backend
call each action makes, with which arguments, and what it returns -- rather
than the backend's own behaviour (covered by ``test_project_snapshooter``).
"""

import os
import sys

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRIDGE = os.path.join(ROOT, "products", "codesys-host", "src", "ide_bridge")
if BRIDGE not in sys.path:
    sys.path.insert(0, BRIDGE)

import ide_handlers_snapshooter as handler  # noqa: E402


class DummyProject(object):
    pass


@pytest.fixture
def project(monkeypatch):
    """Resolve a dummy active project, and make every backend call recorded."""
    monkeypatch.setattr(handler, "_get_active_project", lambda: (DummyProject(), None))
    return DummyProject()


def _patch(monkeypatch, name, fake):
    monkeypatch.setattr(handler.backend, name, fake)


def test_tree_returns_leaf_paths_and_types(monkeypatch, project):
    rows = [
        {"path": "GVL.a", "type": "INT", "leaf": True},
        {"path": "GVL.b", "type": "BOOL", "leaf": True},
    ]
    seen = {}

    def fake_build_tree(app="Application", project=None):
        seen["app"] = app
        seen["project"] = project
        return rows

    _patch(monkeypatch, "build_tree", fake_build_tree)

    result = handler._cmd_snapshooter({"action": "tree", "app": "MainApp"})

    assert result["ok"] is True
    assert result["data"]["action"] == "tree"
    assert result["data"]["app"] == "MainApp"
    assert result["data"]["path"] is None
    assert result["data"]["count"] == 2
    assert result["data"]["leaves"] == [
        {"path": "GVL.a", "type": "INT"},
        {"path": "GVL.b", "type": "BOOL"},
    ]
    assert seen["app"] == "MainApp"
    assert isinstance(seen["project"], DummyProject)


def test_tree_filters_by_path_prefix(monkeypatch, project):
    rows = [
        {"path": "GVL_HMI.a", "type": "INT"},
        {"path": "GVL_Routing.b", "type": "UINT"},
    ]
    _patch(monkeypatch, "build_tree", lambda app="Application", project=None: rows)

    result = handler._cmd_snapshooter({"action": "tree", "path": "GVL_HMI"})

    assert [leaf["path"] for leaf in result["data"]["leaves"]] == ["GVL_HMI.a"]
    assert result["data"]["path"] == "GVL_HMI"


def test_take_returns_a_document_without_saving_by_default(monkeypatch, project):
    document = {"variables": [{"path": "GVL.a", "value": "1"}]}
    seen = {}

    def fake_take(paths=None, app="Application", label="", project=None):
        seen["paths"] = paths
        seen["label"] = label
        return document

    _patch(monkeypatch, "take", fake_take)
    _patch(monkeypatch, "save", lambda data, path: pytest.fail("save must not run"))
    _patch(monkeypatch, "_vars_from_data", lambda data: list(data.get("variables", [])))

    result = handler._cmd_snapshooter({"action": "take", "label": "speed"})

    assert result["ok"] is True
    assert result["data"]["document"] == document
    assert result["data"]["count"] == 1
    assert "saved_to" not in result["data"]
    assert seen["paths"] is None
    assert seen["label"] == "speed"


def test_take_normalizes_paths_and_saves_when_out_is_given(monkeypatch, project):
    seen = {}

    def fake_take(paths=None, app="Application", label="", project=None):
        seen["paths"] = paths
        return {"variables": [{"path": "GVL.a"}, {"path": "GVL.b"}]}

    def fake_save(data, path):
        seen["save"] = (data, path)
        return path

    _patch(monkeypatch, "take", fake_take)
    _patch(monkeypatch, "save", fake_save)
    _patch(monkeypatch, "_vars_from_data", lambda data: list(data.get("variables", [])))

    result = handler._cmd_snapshooter(
        {"action": "take", "paths": "GVL.a,\nGVL.b\n", "out": "preset.json"}
    )

    assert seen["paths"] == ["GVL.a", "GVL.b"]
    assert seen["save"] == (result["data"]["document"], "preset.json")
    assert result["data"]["saved_to"] == "preset.json"


def test_diff_loads_the_input_and_compares_against_the_live_values(monkeypatch, project):
    preset = {"variables": [{"path": "GVL.a", "type": "INT"}]}
    current = {"variables": [{"path": "GVL.a", "type": "INT", "value": "9"}]}
    seen = {}

    _patch(monkeypatch, "load", lambda path: preset)
    _patch(monkeypatch, "_vars_from_data", lambda data: list(data.get("variables", [])))

    def fake_take(paths=None, app="Application", label="", project=None):
        seen["paths"] = paths
        return current

    def fake_compare(data, current=None):
        seen["compare"] = (data, current)
        return {"identical": True}

    _patch(monkeypatch, "take", fake_take)
    _patch(monkeypatch, "compare", fake_compare)

    result = handler._cmd_snapshooter({"action": "diff", "input": "preset.json"})

    assert seen["paths"] == ["GVL.a"]
    assert seen["compare"] == (preset, current)
    assert result["data"]["report"] == {"identical": True}
    assert result["data"]["count"] == 1


def test_diff_accepts_an_inline_preset(monkeypatch, project):
    inline = {"variables": [{"path": "GVL.a"}]}
    _patch(monkeypatch, "load", lambda path: pytest.fail("load must not run"))
    _patch(monkeypatch, "_vars_from_data", lambda data: list(data.get("variables", [])))
    _patch(monkeypatch, "take", lambda paths=None, app="Application", label="", project=None: {})
    _patch(monkeypatch, "compare", lambda data, current=None: {"identical": False})

    result = handler._cmd_snapshooter({"action": "diff", "preset": inline})

    assert result["ok"] is True


def test_diff_without_input_or_preset_is_an_error(monkeypatch, project):
    result = handler._cmd_snapshooter({"action": "diff"})

    assert result["ok"] is False
    assert "input" in result["error"]


def test_restore_is_a_dry_run_unless_apply(monkeypatch, project):
    preset = {"variables": [{"path": "GVL.a"}]}
    seen = {}
    _patch(monkeypatch, "load", lambda path: preset)

    def fake_restore(data, apply=False, project=None):
        seen["apply"] = apply
        return {"written": 0, "would_write": 1}

    _patch(monkeypatch, "restore", fake_restore)

    result = handler._cmd_snapshooter({"action": "restore", "input": "p.json"})

    assert seen["apply"] is False
    assert result["data"]["applied"] is False
    assert result["data"]["result"] == {"written": 0, "would_write": 1}


def test_restore_applies_when_asked(monkeypatch, project):
    seen = {}
    _patch(monkeypatch, "load", lambda path: {"variables": []})
    _patch(
        monkeypatch,
        "restore",
        lambda data, apply=False, project=None: seen.update(apply=apply)
        or {"written": 1},
    )

    result = handler._cmd_snapshooter({"action": "restore", "input": "p.json", "apply": True})

    assert seen["apply"] is True
    assert result["data"]["applied"] is True


def test_an_unknown_action_is_rejected(monkeypatch, project):
    result = handler._cmd_snapshooter({"action": "explode"})

    assert result["ok"] is False
    assert "explode" in result["error"]


def test_a_missing_action_is_rejected(monkeypatch, project):
    result = handler._cmd_snapshooter({})

    assert result["ok"] is False
    assert "(none)" in result["error"]


def test_no_open_project_returns_the_daemon_error(monkeypatch):
    err = {"ok": False, "error": "No project is open in this IDE (ide-1)."}
    monkeypatch.setattr(handler, "_get_active_project", lambda: (None, err))

    assert handler._cmd_snapshooter({"action": "tree"}) is err


def test_a_backend_failure_becomes_an_error_response(monkeypatch, project):
    def boom(app="Application", project=None):
        raise RuntimeError("Snapshooter requires project property cds-sync-folder.")

    _patch(monkeypatch, "build_tree", boom)

    result = handler._cmd_snapshooter({"action": "tree"})

    assert result["ok"] is False
    assert "cds-sync-folder" in result["error"]
    assert "Snapshooter tree failed:" in result["error"]


def test_online_guard_on_apply_is_surfaced(monkeypatch, project):
    _patch(monkeypatch, "load", lambda path: {"variables": []})

    def refuse(data, apply=False, project=None):
        raise handler.backend.SnapshotOnlineError("Snapshot import is disabled while CODESYS is online.")

    _patch(monkeypatch, "restore", refuse)

    result = handler._cmd_snapshooter({"action": "restore", "input": "p.json", "apply": "yes"})

    assert result["ok"] is False
    assert "online" in result["error"]


def test_ui_check_returns_the_report(monkeypatch):
    captured = {}
    report = {"ok": True, "steps": [{"name": "save", "ok": True, "error": ""}]}

    def fake_check(backend, app="Application", script=None):
        captured["backend"] = backend
        captured["app"] = app
        captured["script"] = script
        return report

    _patch_check(monkeypatch, fake_check)

    result = handler._cmd_snapshooter({"action": "ui_check", "app": "MainApp", "script": ["save"]})

    assert result["ok"] is True
    assert result["data"]["report"] is report
    assert captured["app"] == "MainApp"
    assert captured["script"] == ["save"]
    assert captured["backend"] is not None


def test_ui_check_reports_a_window_that_cannot_be_built(monkeypatch):
    _patch_check(
        monkeypatch,
        lambda backend, app="Application", script=None: {
            "ok": False,
            "error": "cannot create the Snapshooter window: ImportError: no clr",
        },
    )

    result = handler._cmd_snapshooter({"action": "ui_check"})

    assert result["ok"] is False
    assert "no clr" in result["error"]


def _patch_check(monkeypatch, fake):
    """Install ``fake`` as ``project_snapshooter_ui.check`` for the lazy import."""
    import project_snapshooter_ui

    monkeypatch.setattr(project_snapshooter_ui, "check", fake)
