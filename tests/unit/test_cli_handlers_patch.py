# -*- coding: utf-8 -*-
"""
test_cli_handlers_patch.py -- Tests for ``cts patch save``.

The daemon is stubbed: these pin what lands on disk, that --dry-run writes
nothing, and that the copy-over layout keeps the project-view/ prefix.
"""

import io
import json
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_cli import _cli_handlers_patch as p

POU_GUID = "6f9dac99-8de1-4efc-8465-68ac443b7d08"
VISU_GUID = "f18bec89-9fef-401d-9953-2f11739a6808"


@pytest.fixture
def sync_folder(tmp_path):
    """A minimal sync folder: two changed files, one untouched, one manifest."""
    view = tmp_path / "project-view"
    (view / "Application").mkdir(parents=True)
    (view / "HMI").mkdir(parents=True)
    (view / "Application" / "PLC_PRG.st").write_text("PROGRAM PLC_PRG\n", "utf-8")
    (view / "HMI" / "Main.xml").write_text("<Single Name='Object' />", "utf-8")
    (view / "Application" / "Device.xml").write_text("<Device />", "utf-8")

    dump = tmp_path / ".dump"
    dump.mkdir()
    manifest = {
        "entries": [
            {
                "guid": "g1",
                "type_guid": POU_GUID,
                "xml_path": "Application/PLC_PRG.xml",
                "xml_root": "dump",
                "projection_paths": ["Application/PLC_PRG.st"],
            },
            {
                "guid": "g2",
                "type_guid": VISU_GUID,
                "xml_path": "HMI/Main.xml",
            },
        ]
    }
    (dump / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    (tmp_path / "cds-text-sync.json").write_text(
        json.dumps({"layout": "project-view", "sync_mode": "text_first"}), "utf-8"
    )
    return tmp_path


@pytest.fixture
def stub_daemon(monkeypatch, sync_folder):
    """Point the handler at the fixture folder and stub the compare call."""
    report = {
        "objects": {
            "modified": [
                {
                    "guid": "g1",
                    "name": "PLC_PRG",
                    "type_guid": POU_GUID,
                    "path": "Application/PLC_PRG",
                },
                {
                    "guid": "g2",
                    "name": "Main",
                    "type_guid": VISU_GUID,
                    "path": "HMI/Main",
                },
            ],
            "added": [],
            "deleted": [
                {
                    "guid": "g3",
                    "name": "OldPrg",
                    "type_guid": POU_GUID,
                    "path": "Application/OldPrg",
                }
            ],
        }
    }
    monkeypatch.setattr(
        p, "_resolve_sync_folder", lambda *a, **k: str(sync_folder)
    )
    monkeypatch.setattr(
        p, "send_command_reverse", lambda *a, **k: {"ok": True, "data": report}
    )
    return report


def _capture(monkeypatch):
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    return buffer


def _patch_dirs(sync_folder):
    root = sync_folder / ".dump" / "patch"
    return sorted(root.iterdir()) if root.exists() else []


def test_dry_run_writes_nothing(sync_folder, stub_daemon, monkeypatch):
    out = _capture(monkeypatch)
    p.cmd_patch_save(dry_run=True)
    summary = json.loads(out.getvalue())
    assert summary["dry_run"] is True
    assert sorted(summary["paths"]) == ["Application/PLC_PRG.st", "HMI/Main.xml"]
    assert _patch_dirs(sync_folder) == []


def test_save_copies_files_under_the_project_view_prefix(
    sync_folder, stub_daemon, monkeypatch
):
    out = _capture(monkeypatch)
    p.cmd_patch_save()
    summary = json.loads(out.getvalue())

    folders = _patch_dirs(sync_folder)
    assert len(folders) == 1
    folder = folders[0]
    assert folder.name.startswith("patch_")
    assert os.path.normcase(summary["output"]) == os.path.normcase(str(folder))
    assert (folder / "project-view" / "Application" / "PLC_PRG.st").is_file()
    assert (folder / "project-view" / "HMI" / "Main.xml").is_file()


def test_non_authored_xml_never_travels(sync_folder, stub_daemon, monkeypatch):
    """Device XML lives in the view but encodes the sender's machine state."""
    stub_daemon["objects"]["modified"].append(
        {
            "guid": "g4",
            "name": "Device",
            "type_guid": "225bfe47-7336-4dbc-9419-4105a7c831fa",
            "path": "Application/Device",
            "view_path": "Application/Device.xml",
        }
    )
    _capture(monkeypatch)
    p.cmd_patch_save()
    folder = _patch_dirs(sync_folder)[0]
    assert not (folder / "project-view" / "Application" / "Device.xml").exists()


def test_metadata_records_deletions_and_the_file_list(
    sync_folder, stub_daemon, monkeypatch
):
    _capture(monkeypatch)
    p.cmd_patch_save()
    folder = _patch_dirs(sync_folder)[0]

    manifest = json.loads((folder / "patch.json").read_text("utf-8"))
    assert sorted(item["path"] for item in manifest["files"]) == [
        "Application/PLC_PRG.st",
        "HMI/Main.xml",
    ]
    assert manifest["deleted"][0]["name"] == "OldPrg"
    assert manifest["sync_mode"] == "text_first"

    readme = (folder / "README.txt").read_text("utf-8")
    assert "cts import" in readme
    assert "OldPrg" in readme


def test_bare_skips_the_metadata_files(sync_folder, stub_daemon, monkeypatch):
    _capture(monkeypatch)
    p.cmd_patch_save(bare=True)
    folder = _patch_dirs(sync_folder)[0]
    assert not (folder / "patch.json").exists()
    assert not (folder / "README.txt").exists()
    assert (folder / "project-view" / "Application" / "PLC_PRG.st").is_file()


def test_zip_is_written_next_to_the_folder(sync_folder, stub_daemon, monkeypatch):
    out = _capture(monkeypatch)
    p.cmd_patch_save(make_zip=True)
    summary = json.loads(out.getvalue())
    assert summary["zip"].endswith(".zip")
    assert os.path.isfile(summary["zip"])


def test_file_listed_by_compare_but_absent_on_disk_is_skipped(
    sync_folder, stub_daemon, monkeypatch
):
    (sync_folder / "project-view" / "HMI" / "Main.xml").unlink()
    out = _capture(monkeypatch)
    p.cmd_patch_save()
    summary = json.loads(out.getvalue())
    assert summary["missing"] == ["HMI/Main.xml"]
    assert summary["files"] == 1


def test_nothing_to_package_creates_no_folder(sync_folder, monkeypatch):
    monkeypatch.setattr(
        p, "_resolve_sync_folder", lambda *a, **k: str(sync_folder)
    )
    monkeypatch.setattr(
        p,
        "send_command_reverse",
        lambda *a, **k: {"ok": True, "data": {"objects": {"modified": []}}},
    )
    out = _capture(monkeypatch)
    p.cmd_patch_save()
    summary = json.loads(out.getvalue())
    assert summary["files"] == 0
    assert summary["output"] is None
    assert _patch_dirs(sync_folder) == []


def test_a_failed_compare_exits_non_zero(sync_folder, monkeypatch):
    monkeypatch.setattr(
        p, "_resolve_sync_folder", lambda *a, **k: str(sync_folder)
    )
    monkeypatch.setattr(
        p, "send_command_reverse", lambda *a, **k: {"ok": False, "error": "no project"}
    )
    with pytest.raises(SystemExit) as excinfo:
        p.cmd_patch_save()
    assert excinfo.value.code == 1
