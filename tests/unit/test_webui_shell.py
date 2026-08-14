"""Tests for the shared pywebview shell; pywebview itself is not required."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from cds_text_sync.webui import shell


def _fake_webview(**attrs):
    """Build a minimal stand-in webview module from *attrs*."""
    module = types.ModuleType("webview")
    for name, value in attrs.items():
        setattr(module, name, value)
    return module


class _FakeWindow:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def create_file_dialog(self, dialog_type):
        self.calls.append(dialog_type)
        return self.result


# ---------------------------------------------------------------------------
# ProgressChannel
# ---------------------------------------------------------------------------


def test_progress_channel_snapshot_is_a_copy():
    channel = shell.ProgressChannel({"running": False, "done": 0})

    snapshot = channel.snapshot()
    snapshot["done"] = 999

    assert channel.snapshot()["done"] == 0


def test_progress_channel_record_replaces_wholesale():
    channel = shell.ProgressChannel({"running": False, "phase": ""})
    before = channel.snapshot()

    channel.record({"running": True, "phase": "rules"})

    assert before == {"running": False, "phase": ""}
    assert channel.snapshot() == {"running": True, "phase": "rules"}


def test_progress_channel_reset_restores_idle():
    idle = {"running": False, "phase": "", "done": 0, "total": 0, "detail": ""}
    channel = shell.ProgressChannel(idle)
    channel.record({"running": True, "phase": "rules", "done": 1, "total": 2, "detail": "CTS0012"})

    channel.reset()

    assert channel.snapshot() == idle


def test_progress_channel_does_not_alias_idle_dict():
    idle = {"running": False, "done": 0}
    channel = shell.ProgressChannel(idle)

    idle["running"] = True
    snapshot = channel.snapshot()
    snapshot["done"] = 999
    channel.reset()

    assert channel.snapshot() == {"running": False, "done": 0}


# ---------------------------------------------------------------------------
# resolve_under_root
# ---------------------------------------------------------------------------


def test_resolve_under_root_resolves_normal_relative_path(tmp_path):
    root = tmp_path / "project"
    source = root / "POUs" / "Main.st"
    source.parent.mkdir(parents=True)
    source.write_text("PROGRAM Main\n", encoding="utf-8")

    assert shell.resolve_under_root(root, "POUs/Main.st") == source.resolve()


def test_resolve_under_root_rejects_parent_escape(tmp_path):
    root = tmp_path / "project"
    root.mkdir()

    assert shell.resolve_under_root(root, "../outside.st") is None


def test_resolve_under_root_rejects_absolute_path_outside_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()

    assert shell.resolve_under_root(root, str(tmp_path / "elsewhere.st")) is None


def test_resolve_under_root_resolves_inside_subdirectory(tmp_path):
    root = tmp_path / "project"
    source = root / "a" / "b" / "X.st"
    source.parent.mkdir(parents=True)
    source.write_text("x := 1;\n", encoding="utf-8")

    assert shell.resolve_under_root(root, "a/b/X.st") == source.resolve()


# ---------------------------------------------------------------------------
# package_page
# ---------------------------------------------------------------------------


def test_package_page_builds_expected_path(tmp_path):
    module = tmp_path / "app.py"
    module.write_text("", encoding="utf-8")

    assert shell.package_page(module, "ui_assets") == tmp_path / "ui_assets" / "index.html"


def test_package_page_supports_custom_page_name(tmp_path):
    module = tmp_path / "app.py"
    module.write_text("", encoding="utf-8")

    assert shell.package_page(module, "ui_assets", "other.html") == (
        tmp_path / "ui_assets" / "other.html"
    )


# ---------------------------------------------------------------------------
# start_window
# ---------------------------------------------------------------------------


def test_start_window_returns_2_and_hints_when_webview_absent(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "webview", None)

    code = shell.start_window(
        "My Window", Path("index.html"), object(), 800, 600, (400, 300), "install me!"
    )

    assert code == 2
    assert "install me!" in capsys.readouterr().err


def test_start_window_creates_window_with_fake_webview(monkeypatch, tmp_path):
    calls = []
    started = []
    module = _fake_webview()
    module.create_window = lambda title, url, js_api=None, **kwargs: calls.append(
        (title, url, js_api, kwargs)
    )
    module.start = lambda: started.append(True)
    monkeypatch.setitem(sys.modules, "webview", module)

    page = tmp_path / "ui_assets" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("", encoding="utf-8")
    api = object()

    code = shell.start_window("My Window", page, api, 800, 600, (400, 300), "unused hint")

    assert code == 0
    assert len(calls) == 1
    title, url, js_api, kwargs = calls[0]
    assert title == "My Window"
    assert url == page.as_uri()
    assert js_api is api
    assert kwargs["width"] == 800
    assert kwargs["height"] == 600
    assert kwargs["min_size"] == (400, 300)
    assert started == [True]


def test_start_window_announces_readiness_before_the_event_loop(monkeypatch, tmp_path, capsys):
    # The external launcher waits for this line instead of timing the child, so
    # it has to be written after the window exists but before start() blocks.
    order = []
    module = _fake_webview()
    module.create_window = lambda *a, **k: order.append("create")
    module.start = lambda: order.append("start")
    monkeypatch.setitem(sys.modules, "webview", module)

    page = tmp_path / "index.html"
    page.write_text("", encoding="utf-8")

    def _record_ready(stream=None):
        order.append("ready")

    monkeypatch.setattr(shell, "announce_ready", _record_ready)
    assert shell.start_window("t", page, object(), 800, 600, (400, 300), "hint") == 0
    assert order == ["create", "ready", "start"]


def test_announce_ready_writes_and_flushes_the_line():
    class _Stream:
        def __init__(self):
            self.text = ""
            self.flushed = False

        def write(self, chunk):
            self.text += chunk

        def flush(self):
            self.flushed = True

    stream = _Stream()
    shell.announce_ready(stream)
    assert stream.text == shell.READY_LINE + "\n"
    assert stream.flushed is True


# ---------------------------------------------------------------------------
# choose_folder
# ---------------------------------------------------------------------------


def test_choose_folder_returns_first_folder(monkeypatch):
    window = _FakeWindow(["C:/folder", "C:/other"])
    dialog_type = object()
    module = _fake_webview(windows=[window], FOLDER_DIALOG=dialog_type)
    monkeypatch.setitem(sys.modules, "webview", module)

    assert shell.choose_folder() == "C:/folder"
    assert window.calls == [dialog_type]


def test_choose_folder_returns_empty_when_cancelled(monkeypatch):
    for result in (None, []):
        window = _FakeWindow(result)
        module = _fake_webview(windows=[window], FOLDER_DIALOG=object())
        monkeypatch.setitem(sys.modules, "webview", module)

        assert shell.choose_folder() == ""
