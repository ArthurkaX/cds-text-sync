"""Tests for the CODESYS bridge that starts the analyzer UI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"

if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))


def _load_launcher():
    spec = importlib.util.spec_from_file_location(
        "_codesys_analyze_ui_launcher_under_test",
        str(BRIDGE / "codesys_analyze_ui_launcher.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Info:
    def __init__(self, values):
        self.values = values


class _Project:
    path = r"C:\Projects\Demo\Demo.project"

    def __init__(self, sync_folder):
        self._info = _Info({"cds-sync-folder": sync_folder})

    def get_project_info(self):
        return self._info


def _make_runtime():
    class _Projects:
        primary = _Project(r".\sync")

    class _Ui:
        def info(self, _message):
            pass

        def error(self, _message):
            pass

    class _Runtime:
        projects = _Projects()
        caller_globals = {}
        ui = _Ui()

    return _Runtime()


def test_main_delegates_to_the_shared_start_ui_with_the_ui_command(monkeypatch):
    launcher = _load_launcher()
    runtime = _make_runtime()
    captured = {}

    def fake_start_ui(_runtime, project, command_args, label):
        captured["project"] = project
        captured["command_args"] = command_args
        captured["label"] = label
        return {"status": "started", "pid": 123, "sync_folder": r"C:\sync"}

    monkeypatch.setattr(launcher, "resolve_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(launcher, "resolve_projects", lambda *_args: runtime.projects)
    monkeypatch.setattr(launcher, "start_ui", fake_start_ui)

    result = launcher.main()

    assert result["status"] == "started"
    assert captured["command_args"] == ["ui"]
    assert captured["label"] == "the analyzer UI"
    assert captured["project"] is runtime.projects.primary


def test_main_reports_an_error_when_no_project_is_open(monkeypatch):
    launcher = _load_launcher()
    runtime = _make_runtime()
    messages = []

    class _FakeNotify:
        def __call__(self, _runtime, message, is_error=False):
            messages.append((message, is_error))

    monkeypatch.setattr(launcher, "resolve_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(launcher, "resolve_projects", lambda *_args: None)
    monkeypatch.setattr(launcher, "notify", _FakeNotify())

    result = launcher.main()

    assert result["status"] == "error"
    assert "No CODESYS project is open." in result["error"]
    assert messages[0][0] == "No CODESYS project is open."
    assert messages[0][1] is True
