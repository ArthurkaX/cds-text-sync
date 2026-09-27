# -*- coding: utf-8 -*-
"""
test_daemon_handshake.py — Unit tests for the daemon's protocol v2 handshake and instance metadata.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parent.parent.parent
_IDE_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_STUB_NAMES = [
    "clr",
    "System",
    "System.IO",
    "System.IO.Pipes",
    "System.Threading",
    "System.Windows",
    "System.Windows.Forms",
    "System.Drawing",
    "System.Collections",
    "System.Collections.Generic",
    "System.Array",
    "System.Byte",
    "scriptengine",
]


class _AutoStub:
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self

    def __iter__(self):
        return iter([])


def _stub_module(name):
    mod = ModuleType(name)
    mod.__spec__ = None
    mod.__getattr__ = lambda attr: _AutoStub()  # type: ignore[attr-defined]
    return mod


_saved_modules = {}
for name in _STUB_NAMES:
    _saved_modules[name] = sys.modules.get(name)
    sys.modules[name] = _stub_module(name)

if str(_IDE_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_IDE_BRIDGE))

import ide_daemon_state as ds
import ide_reverse_pipe_loop as rpl

# Restore sys.modules so stubs don't pollute subsequent unit tests
for name, orig in _saved_modules.items():
    if orig is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = orig


class FakePipe:
    """Mock pipe delivering a sequence of incoming JSON messages and recording outgoing messages."""

    def __init__(self, incoming: list[dict | None]):
        self.incoming = list(incoming)
        self.outgoing: list[dict] = []

    def read_msg(self) -> dict | None:
        if self.incoming:
            return self.incoming.pop(0)
        return None

    def write_msg(self, data: dict) -> bool:
        self.outgoing.append(data)
        return True


class TestDaemonHandshake:
    def setup_method(self):
        sys._codesys_daemon_loop = {
            "running": True,
            "started": True,
            "projects": None,
            "system": None,
            "started_at": "2026-09-27 12:00:00",
            "command_count": 0,
            "last_command": None,
            "online_app": None,
            "online_target_app": None,
            "timeout_profile": None,
        }

    def test_hello_then_command(self, monkeypatch):
        pipe = FakePipe([
            {"method": "ping", "params": {"hello": 2}},
            {"method": "ping", "params": {}},
        ])

        stop = rpl._serve_connection(pipe)
        assert stop is False
        assert len(pipe.outgoing) == 2

        # First reply is H2
        h2 = pipe.outgoing[0]
        assert h2["ok"] is True
        assert "hello" in h2
        assert h2["hello"]["protocol"] == 2
        assert h2["hello"]["pid"] == os.getpid()
        assert h2["hello"]["id"] == f"ide-{os.getpid()}"

        # Second reply is response to ping command with attached instance info
        cmd_resp = pipe.outgoing[1]
        assert cmd_resp["ok"] is True
        assert cmd_resp["data"]["status"] == "pong"
        assert "instance" in cmd_resp
        assert cmd_resp["instance"]["id"] == f"ide-{os.getpid()}"
        assert sys._codesys_daemon_loop["command_count"] == 1

    def test_hello_then_release(self):
        pipe = FakePipe([
            {"method": "ping", "params": {"hello": 2}},
            {"release": True},
        ])

        stop = rpl._serve_connection(pipe)
        assert stop is False
        assert len(pipe.outgoing) == 1
        assert pipe.outgoing[0]["ok"] is True
        assert "hello" in pipe.outgoing[0]
        # Release does not count as a command
        assert sys._codesys_daemon_loop["command_count"] == 0

    def test_hello_then_eof(self):
        pipe = FakePipe([
            {"method": "ping", "params": {"hello": 2}},
            None,
        ])

        stop = rpl._serve_connection(pipe)
        assert stop is False
        assert len(pipe.outgoing) == 1
        assert sys._codesys_daemon_loop["command_count"] == 0

    def test_bare_command_legacy_cts(self):
        pipe = FakePipe([
            {"method": "ping", "params": {}},
        ])

        stop = rpl._serve_connection(pipe)
        assert stop is False
        assert len(pipe.outgoing) == 1
        resp = pipe.outgoing[0]
        assert resp["ok"] is True
        assert resp["data"]["status"] == "pong"
        assert "instance" in resp
        assert sys._codesys_daemon_loop["command_count"] == 1

    def test_instance_attached_to_error_response(self):
        pipe = FakePipe([
            {"method": "non_existent_method_xyz", "params": {}},
        ])

        stop = rpl._serve_connection(pipe)
        assert stop is False
        assert len(pipe.outgoing) == 1
        resp = pipe.outgoing[0]
        assert resp["ok"] is False
        assert "instance" in resp
        assert resp["instance"]["id"] == f"ide-{os.getpid()}"

    def test_instance_with_no_project(self):
        info = ds._instance_info()
        assert info["id"] == f"ide-{os.getpid()}"
        assert info["project"] is None

        h_info = ds._hello_info()
        assert h_info["protocol"] == 2
        assert h_info["project"] is None

    def test_instance_with_project(self, monkeypatch):
        mock_proj = MagicMock()
        mock_proj.path = r"S:\Projects\VKO\VKO.project"

        mock_projects = MagicMock()
        mock_projects.primary = mock_proj
        sys._codesys_daemon_loop["projects"] = mock_projects

        monkeypatch.setattr(ds, "_project_file_path", lambda p: r"S:\Projects\VKO\VKO.project")
        monkeypatch.setattr(ds, "_project_sync_folder", lambda p: r"S:\Active\VKO")

        info = ds._instance_info()
        assert info["id"] == f"ide-{os.getpid()}"
        assert info["project"] == {
            "name": "VKO",
            "path": r"S:\Projects\VKO\VKO.project",
            "sync_folder": r"S:\Active\VKO",
        }

    def test_no_project_error_code(self):
        sys._codesys_daemon_loop["projects"] = None
        proj, err = ds._get_active_project()
        assert proj is None
        assert err["ok"] is False
        assert err["code"] == "no_project"
        assert f"ide-{os.getpid()}" in err["error"]
