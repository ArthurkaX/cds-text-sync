# -*- coding: utf-8 -*-
"""
test_script_message_capture.py - The advanced debug option copies script
messages into sync_debug.log.

A failure after the engine step (pre-import backup, patch apply) is reported
only through print(), which CODESYS shows in the Messages window and nowhere
else, so a user's sync_debug.log ended at "Applying changes from ..." with
the cause missing.
"""

import json
import os
import sys

import pytest

BRIDGE_DIR = os.path.normpath(
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
if BRIDGE_DIR not in sys.path:
    sys.path.insert(0, BRIDGE_DIR)

import ide_runtime_common  # noqa: E402
from _project_settings import load_project_settings, save_project_settings  # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_print_output_reaches_stdout_and_log(tmp_path, capsys):
    log_path = str(tmp_path / ".dump" / "sync_debug.log")
    with ide_runtime_common.capture_script_messages(log_path):
        print("Pre-import backup failed: no active project.")
        ide_runtime_common.log_error("Failed to apply patch to IDE.")

    assert "Pre-import backup failed" in capsys.readouterr().out
    text = _read(log_path)
    assert "[script] Pre-import backup failed: no active project." in text
    assert "[IDE ERROR]" in text and "Failed to apply patch to IDE." in text


def test_stdout_is_restored_and_partial_line_is_kept(tmp_path):
    log_path = str(tmp_path / "sync_debug.log")
    original = sys.stdout
    with ide_runtime_common.capture_script_messages(log_path):
        sys.stdout.write("no newline at the end")
    assert sys.stdout is original
    assert "[script] no newline at the end" in _read(log_path)


def test_escaping_exception_is_logged_with_traceback(tmp_path):
    log_path = str(tmp_path / "sync_debug.log")
    with pytest.raises(ValueError):
        with ide_runtime_common.capture_script_messages(log_path):
            raise ValueError("boom")
    text = _read(log_path)
    assert "Unhandled exception" in text
    assert "Traceback" in text and "ValueError: boom" in text


def test_without_log_path_nothing_is_captured(tmp_path):
    original = sys.stdout
    with ide_runtime_common.capture_script_messages(None):
        assert sys.stdout is original
    assert not os.listdir(str(tmp_path))


def test_nested_capture_does_not_duplicate_lines(tmp_path):
    log_path = str(tmp_path / "sync_debug.log")
    with ide_runtime_common.capture_script_messages(log_path):
        with ide_runtime_common.capture_script_messages(log_path):
            print("once")
    assert _read(log_path).count("once") == 1


def test_advanced_debug_setting_round_trips(tmp_path):
    root = str(tmp_path)
    assert load_project_settings(root)["advanced_debug"] is False
    save_project_settings(root, {"advanced_debug": True})
    with open(os.path.join(root, "cds-text-sync.json")) as handle:
        assert json.load(handle)["advanced_debug"] is True
    assert load_project_settings(root)["advanced_debug"] is True


def test_advanced_debug_implies_the_debug_log(tmp_path):
    root = str(tmp_path)
    assert ide_runtime_common.project_logging_config(root) == (False, None)
    save_project_settings(root, {"advanced_debug": True})
    verbose, log_path = ide_runtime_common.project_logging_config(root)
    assert verbose is True
    assert log_path.endswith(os.path.join(".dump", "sync_debug.log"))
