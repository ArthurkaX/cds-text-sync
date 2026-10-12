# -*- coding: utf-8 -*-
"""The rules an engineer who is not the owner gets from the project
(``engine/_non_owner.py``)."""

import os
import shutil
import subprocess

import pytest

from cds_text_sync.engine._non_owner import non_owner_report, refresh_non_owner

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

_PROFILE = {
    "guid_aliases": {
        "application": ["app-type"],
        "task_config": ["tc-type"],
        "alarm_config": ["alarm-type"],
        "library_manager": ["lib-type"],
        "device": ["device-type"],
        "device_module": ["module-type"],
    }
}


def _entry(guid, path, type_guid, parent=None):
    return {
        "guid": guid,
        "xml_path": path,
        "type_guid": type_guid,
        "parent_guid": parent,
    }


def _manifest(*extra):
    """PLC / {Ethernet / Device, Plc Logic / Application / {Task Configuration
    / MainTask, Library Manager, POU}}"""
    app = "PLC/Plc Logic/Application/"
    return {
        "entries": [
            _entry("plc", "PLC.xml", "device-type"),
            _entry("eth", "PLC/Ethernet/.cds-object.xml", "module-type", "plc"),
            _entry("dev", "PLC/Ethernet/Device.xml", "device-type", "eth"),
            _entry("logic", "PLC/Plc Logic/.cds-object.xml", "logic-type", "plc"),
            _entry("app", app + ".cds-object.xml", "app-type", "logic"),
            _entry("tc", app + "Task Configuration/.cds-object.xml", "tc-type", "app"),
            _entry("task", app + "Task Configuration/MainTask.xml", "task-type", "tc"),
            _entry("lib", app + "Library Manager.xml", "lib-type", "app"),
            _entry("pou", app + "POU.xml", "pou-type", "app"),
        ]
        + list(extra)
    }


def _repo(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return str(root)


def _exclude(root):
    with open(os.path.join(root, ".git", "info", "exclude"), encoding="utf-8") as handle:
        return handle.read()


def test_the_owner_keeps_configuration_libraries_and_hardware_outside_the_application(
    tmp_path,
):
    report = non_owner_report(str(tmp_path), _manifest(), _PROFILE)

    assert report["git_work_tree"] is False
    assert report["non_owner"] is False
    assert report["owner_paths"] == [
        "PLC/Ethernet/",
        "PLC/Plc Logic/Application/Library Manager.xml",
        "PLC/Plc Logic/Application/Task Configuration/",
    ]


def test_on_writes_a_block_beside_the_user_lines_and_off_removes_it(tmp_path):
    root = _repo(tmp_path)
    with open(os.path.join(root, ".git", "info", "exclude"), "w") as handle:
        handle.write("*.bak\n")

    assert non_owner_report(root, _manifest(), _PROFILE, "on")["non_owner"]

    assert _exclude(root).startswith("*.bak\n\n# cds-text-sync:")
    assert "\n/PLC/Ethernet/\n" in _exclude(root)
    assert subprocess.run(
        ["git", "-C", root, "check-ignore", "-q", "PLC/Ethernet/Device.xml"]
    ).returncode == 0

    assert not non_owner_report(root, _manifest(), _PROFILE, "off")["non_owner"]
    assert _exclude(root) == "*.bak\n"


def test_a_command_brings_the_block_up_to_date_with_the_project(tmp_path):
    root = _repo(tmp_path)
    non_owner_report(root, _manifest(), _PROFILE, "on")
    alarm = _entry(
        "alarm", "PLC/Plc Logic/Application/Alarm Configuration/.cds-object.xml",
        "alarm-type", "app",
    )

    refresh_non_owner(root, _manifest(alarm), _PROFILE)

    assert "/PLC/Plc Logic/Application/Alarm Configuration/\n" in _exclude(root)


def test_without_the_block_a_refresh_writes_nothing(tmp_path):
    root = _repo(tmp_path)
    before = _exclude(root)

    refresh_non_owner(root, _manifest(), _PROFILE)

    assert _exclude(root) == before


def test_rules_are_anchored_at_the_work_tree_and_escape_pattern_characters(tmp_path):
    _repo(tmp_path)
    views = tmp_path / "proj-cts"
    views.mkdir()
    odd = _entry("odd", "PLC/Plc Logic/Application/[Alarms]*/.cds-object.xml",
                 "alarm-type", "app")

    non_owner_report(str(views), _manifest(odd), _PROFILE, "on")

    assert "\n/proj-cts/PLC/Plc Logic/Application/\\[Alarms\\]\\*/\n" in _exclude(
        str(tmp_path)
    )


def test_on_needs_a_work_tree_and_a_manifest(tmp_path):
    with pytest.raises(RuntimeError, match="not in a git work tree"):
        non_owner_report(str(tmp_path), _manifest(), _PROFILE, "on")
    root = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="manifest"):
        non_owner_report(root, None, _PROFILE, "on")
