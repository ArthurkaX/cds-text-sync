"""Tests for the shared external-UI launcher used by the CODESYS bridges.

Covers the bounded readiness handshake with fake process objects (a real
process is never started), the command/environment construction, the stdout
drain, the FSM launcher, and the bootstrap manifest contract.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "products" / "codesys-host"
BRIDGE = HOST / "src" / "ide_bridge"

if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))


def _load_shared():
    spec = importlib.util.spec_from_file_location(
        "_codesys_external_ui_launcher_under_test",
        str(BRIDGE / "codesys_external_ui_launcher.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fsm_launcher():
    spec = importlib.util.spec_from_file_location(
        "_codesys_fsm_launcher_under_test",
        str(BRIDGE / "codesys_fsm_launcher.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "_cds_bootstrap_ui_launcher_test",
        str(HOST / "cds_bootstrap.py"),
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


class _FakeStdout:
    """A fake child stdout: readline() yields the given chunks, then EOF."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._lock = threading.Lock()

    def readline(self):
        with self._lock:
            if self._chunks:
                return self._chunks.pop(0)
            return ""


class _FakeProcess:
    def __init__(self, stdout, poll_result=None, returncode=None, pid=123):
        self.stdout = stdout
        self._poll_result = poll_result
        self.returncode = returncode
        self.pid = pid

    def poll(self):
        return self._poll_result


def _make_runtime():
    class _Ui:
        def __init__(self):
            self.messages = []

        def info(self, message):
            self.messages.append(("info", message))

        def error(self, message):
            self.messages.append(("error", message))

    class _Runtime:
        pass

    runtime = _Runtime()
    runtime.ui = _Ui()
    return runtime


def _ready_stream(launcher):
    return _FakeStdout([launcher.READY_LINE + "\n", ""])


# ---------------------------------------------------------------------------
# project_sync_folder
# ---------------------------------------------------------------------------


def test_project_sync_folder_resolves_relative_property():
    launcher = _load_shared()

    path, error = launcher.project_sync_folder(_Project(r".\sync"))

    assert error is None
    assert path == os.path.normpath(r"C:\Projects\Demo\sync")


def test_project_sync_folder_reports_when_unconfigured():
    launcher = _load_shared()

    path, error = launcher.project_sync_folder(_Project(""))

    assert path is None
    assert "Sync folder is not configured" in error


# ---------------------------------------------------------------------------
# start_ui: handshake outcomes and process plumbing
# ---------------------------------------------------------------------------


def test_start_ui_readiness_line_returns_started(monkeypatch):
    launcher = _load_shared()
    runtime = _make_runtime()
    process = _FakeProcess(_ready_stream(launcher))
    captured = {}

    monkeypatch.setattr(launcher, "python_command", lambda: r"C:\Python\python.exe")
    monkeypatch.setattr(launcher, "body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs)
        or process,
    )
    monkeypatch.setattr(
        launcher, "_start_drain", lambda stream: captured.update(drained=stream)
    )

    result = launcher.start_ui(runtime, _Project(r".\sync"), ["ui"], "the analyzer UI")

    workspace = os.path.normpath(r"C:\Projects\Demo\sync")
    assert result["status"] == "started"
    assert result["pid"] == 123
    assert result["sync_folder"] == workspace
    assert captured["command"][:4] == [
        r"C:\Python\python.exe", "-m", "cds_cli.main", "ui",
    ]
    assert captured["command"][-2:] == ["--workspace", workspace]
    assert captured["kwargs"]["stdout"] is launcher.subprocess.PIPE
    assert captured["kwargs"]["stderr"] is launcher.subprocess.STDOUT


def test_start_ui_builds_fsm_ui_command(monkeypatch):
    launcher = _load_shared()
    runtime = _make_runtime()
    process = _FakeProcess(_ready_stream(launcher))
    captured = {}

    monkeypatch.setattr(launcher, "python_command", lambda: "python")
    monkeypatch.setattr(launcher, "body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command) or process,
    )
    monkeypatch.setattr(launcher, "_start_drain", lambda stream: None)

    result = launcher.start_ui(runtime, _Project(r".\sync"), ["fsm", "ui"], "the FSM map")

    workspace = os.path.normpath(r"C:\Projects\Demo\sync")
    assert result["status"] == "started"
    assert captured["command"][:5] == ["python", "-m", "cds_cli.main", "fsm", "ui"]
    assert captured["command"][-2:] == ["--workspace", workspace]


def test_start_ui_sets_initial_workspace_environment(monkeypatch):
    launcher = _load_shared()
    runtime = _make_runtime()
    process = _FakeProcess(_ready_stream(launcher))
    captured = {}

    monkeypatch.setattr(launcher, "python_command", lambda: "python")
    monkeypatch.setattr(launcher, "body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(kwargs=kwargs) or process,
    )
    monkeypatch.setattr(launcher, "_start_drain", lambda stream: None)

    result = launcher.start_ui(runtime, _Project(r".\sync"), ["ui"], "the analyzer UI")

    workspace = os.path.normpath(r"C:\Projects\Demo\sync")
    assert result["status"] == "started"
    assert captured["kwargs"]["env"]["CTS_INITIAL_WORKSPACE"] == workspace


def test_start_ui_reports_immediate_exit_with_code_and_hint(monkeypatch):
    launcher = _load_shared()
    runtime = _make_runtime()
    process = _FakeProcess(
        _FakeStdout(["Traceback (most recent call last):\n", ""]),
        poll_result=7,
        returncode=7,
    )
    captured = {}

    monkeypatch.setattr(launcher, "python_command", lambda: "python")
    monkeypatch.setattr(launcher, "body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command) or process,
    )

    result = launcher.start_ui(runtime, _Project(r".\sync"), ["ui"], "the analyzer UI")

    assert result["status"] == "error"
    assert "code 7" in result["error"]
    assert "Traceback" in result["error"]
    assert 'pip install -e ".[ui]"' in result["error"]
    assert runtime.ui.messages[0][0] == "error"


def test_start_ui_reports_timeout_when_no_line_and_no_exit(monkeypatch):
    launcher = _load_shared()
    runtime = _make_runtime()
    # EOF immediately but the process is still running: neither signal arrives.
    process = _FakeProcess(_FakeStdout([]))
    captured = {}

    monkeypatch.setattr(launcher, "python_command", lambda: "python")
    monkeypatch.setattr(launcher, "body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command) or process,
    )

    result = launcher.start_ui(
        runtime, _Project(r".\sync"), ["ui"], "the analyzer UI", timeout_seconds=0.05
    )

    assert result["status"] == "error"
    assert "did not report readiness" in result["error"]
    assert runtime.ui.messages[0][0] == "error"


def test_start_ui_reports_unconfigured_sync_folder():
    launcher = _load_shared()
    runtime = _make_runtime()

    result = launcher.start_ui(runtime, _Project(""), ["ui"], "the analyzer UI")

    assert result["status"] == "error"
    assert "Sync folder is not configured" in result["error"]
    assert runtime.ui.messages[0][0] == "error"


# ---------------------------------------------------------------------------
# stdout drain
# ---------------------------------------------------------------------------


def test_stdout_is_drained_after_a_successful_handshake(monkeypatch):
    launcher = _load_shared()
    runtime = _make_runtime()
    stream = _ready_stream(launcher)
    process = _FakeProcess(stream)
    drained = {}

    monkeypatch.setattr(launcher, "python_command", lambda: "python")
    monkeypatch.setattr(launcher, "body_root", lambda: r"C:\cds-text-sync")
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **kwargs: process)
    monkeypatch.setattr(
        launcher, "_start_drain", lambda target: drained.update(stream=target)
    )

    result = launcher.start_ui(runtime, _Project(r".\sync"), ["ui"], "the analyzer UI")

    assert result["status"] == "started"
    assert drained["stream"] is stream


def test_start_drain_uses_a_daemon_thread_and_reads_to_eof():
    launcher = _load_shared()

    class _Stream:
        def __init__(self):
            self._remaining = [("line %d\n" % index) for index in range(50)]

        def readline(self):
            return self._remaining.pop(0) if self._remaining else ""

    stream = _Stream()

    thread = launcher._start_drain(stream)

    assert thread.daemon is True
    thread.join(timeout=2.0)
    assert thread.is_alive() is False


# ---------------------------------------------------------------------------
# FSM launcher
# ---------------------------------------------------------------------------


def test_fsm_launcher_main_delegates_to_shared_start_ui(monkeypatch):
    launcher = _load_fsm_launcher()
    project = _Project(r".\sync")

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

    captured = {}

    def fake_start_ui(_runtime, _project, command_args, label):
        captured["command_args"] = command_args
        captured["label"] = label
        return {"status": "started", "pid": 1, "sync_folder": r"C:\sync"}

    monkeypatch.setattr(launcher, "resolve_runtime", lambda **_kwargs: _Runtime())
    monkeypatch.setattr(launcher, "resolve_projects", lambda *_args: _Projects())
    monkeypatch.setattr(launcher, "start_ui", fake_start_ui)

    result = launcher.main()

    assert result["status"] == "started"
    assert captured["command_args"] == ["fsm", "ui"]
    assert captured["label"] == "the FSM map"


def test_fsm_launcher_main_reports_when_no_project_is_open(monkeypatch):
    launcher = _load_fsm_launcher()

    class _Ui:
        def error(self, _message):
            pass

    class _Runtime:
        projects = None
        caller_globals = {}
        ui = _Ui()

    monkeypatch.setattr(launcher, "resolve_runtime", lambda **_kwargs: _Runtime())
    monkeypatch.setattr(launcher, "resolve_projects", lambda *_args: None)

    result = launcher.main()

    assert result["status"] == "error"
    assert "No CODESYS project is open." in result["error"]


def test_fsm_launcher_imports_no_forbidden_modules():
    source = (BRIDGE / "codesys_fsm_launcher.py").read_text(encoding="utf-8")

    for forbidden in (
        "cts_shared.st.fsm",
        "cds_text_sync.fsm",
        "System.Windows.Forms",
        "codesys_fsm_picker",
        "codesys_fsm_ui",
    ):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# Bootstrap manifest
# ---------------------------------------------------------------------------


def test_project_fsm_bootstrap_entry_is_a_bridge_to_codesys_fsm_launcher():
    bootstrap = _load_bootstrap()

    spec = bootstrap.ENTRYPOINTS_BY_NAME["Project_fsm"]

    assert spec["name"] == "Project_fsm"
    assert spec["kind"] == "bridge"
    assert spec["module"] == "codesys_fsm_launcher"
    assert spec["entry"] == "main"
    assert spec["entry_kwargs"] == ["params", "caller_globals"]
    assert "Show the FSM transition map" in spec["summary"]
