"""Tests for the CODESYS bridge that starts the analyzer UI."""

from __future__ import annotations

import importlib.util
import os
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


def test_project_sync_folder_resolves_relative_property():
    launcher = _load_launcher()

    path, error = launcher._project_sync_folder(_Project(r".\sync"))

    assert error is None
    assert path == os.path.normpath(r"C:\Projects\Demo\sync")


def test_main_passes_workspace_to_process_and_environment(monkeypatch):
    launcher = _load_launcher()
    project = _Project(r".\sync")
    captured = {}

    class _Projects:
        primary = project

    class _Ui:
        def info(self, _message):
            pass

        def error(self, _message):
            pass

    class _Runtime:
        projects = _Projects()
        caller_globals = {}
        ui = _Ui()

    class _Process:
        pid = 123

        @staticmethod
        def poll():
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr(launcher, "resolve_runtime", lambda **_kwargs: _Runtime())
    monkeypatch.setattr(launcher, "resolve_projects", lambda *_args: _Projects())
    monkeypatch.setattr(launcher, "_body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(launcher, "_python_command", lambda: r"C:\Python\python.exe")
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)

    result = launcher.main()

    workspace = os.path.normpath(r"C:\Projects\Demo\sync")
    assert result["status"] == "started"
    assert captured["command"][-2:] == ["--workspace", workspace]
    assert captured["kwargs"]["env"]["CTS_INITIAL_WORKSPACE"] == workspace
