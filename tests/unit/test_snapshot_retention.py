# -*- coding: utf-8 -*-
"""
test_snapshot_retention.py — .dump/ must not grow without bound.

Every `cts export` writes a snapshot-<timestamp>.xml into .dump/, and so do
`cts compare` and even `cts import --dry-run`, at well over a megabyte a piece.
Nothing used to remove them: a folder tested for an afternoon held 23 MB of
them. Only the newest is ever read back, so the rest are a short undo trail at
best.

Pruning and selection must agree on what a snapshot is, or pruning could delete
the file the importer is about to pick.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)


@pytest.fixture(scope="module")
def sync_handlers():
    """Load ide_handlers_sync with its CODESYS-only dependencies stubbed out."""
    logged = []

    def _stub(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        return module

    saved = {name: sys.modules.get(name) for name in _STUBBED}
    sys.modules["ide_runtime_common"] = _stub("ide_runtime_common")
    sys.modules["ide_daemon_state"] = _stub(
        "ide_daemon_state",
        _log=lambda *a, **k: logged.append(" ".join(str(x) for x in a)),
        _get_active_project=lambda *a, **k: (None, None),
        _read_text_utf8=lambda *a, **k: "",
    )
    sys.modules["ide_daemon_helpers"] = _stub(
        "ide_daemon_helpers",
        _active_app_online_state=lambda *a, **k: None,
        _active_application_name=lambda *a, **k: "",
        _find_object_by_selector=lambda *a, **k: None,
        _find_object_in_project=lambda *a, **k: None,
        _get_sync_folder=lambda *a, **k: ("", None),
        _invalidate_device_cache=lambda *a, **k: None,
    )
    sys.modules["ide_st_text"] = _stub(
        "ide_st_text", split_st_text=lambda *a, **k: ("", "")
    )

    spec = importlib.util.spec_from_file_location(
        "ide_handlers_sync", BRIDGE_DIR / "ide_handlers_sync.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._test_log = logged

    yield module

    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


_STUBBED = (
    "ide_runtime_common",
    "ide_daemon_state",
    "ide_daemon_helpers",
    "ide_st_text",
)


def _make_snapshots(directory, count, start=1):
    """Create snapshots whose names sort oldest-first, as real timestamps do."""
    names = []
    for i in range(start, start + count):
        name = "snapshot-20260731_{0:06d}.xml".format(i)
        (directory / name).write_text("x", encoding="utf-8")
        names.append(name)
    return names


def test_keeps_the_newest_and_drops_the_rest(sync_handlers, tmp_path):
    names = _make_snapshots(tmp_path, 25)
    removed = sync_handlers._prune_snapshots(tmp_path.as_posix(), keep=10)

    survivors = sorted(p.name for p in tmp_path.iterdir())
    assert removed == 15
    assert survivors == sorted(names[-10:])


def test_is_a_no_op_below_the_limit(sync_handlers, tmp_path):
    names = _make_snapshots(tmp_path, 10)
    assert sync_handlers._prune_snapshots(tmp_path.as_posix(), keep=10) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(names)


def test_the_newest_snapshot_always_survives(sync_handlers, tmp_path):
    """The importer takes the newest; pruning must never remove it."""
    names = _make_snapshots(tmp_path, 40)
    newest = sorted(names, reverse=True)[0]
    sync_handlers._prune_snapshots(tmp_path.as_posix(), keep=1)
    assert [p.name for p in tmp_path.iterdir()] == [newest]


def test_leaves_everything_else_in_dump_alone(sync_handlers, tmp_path):
    """.dump holds reports and the IDE mirror too — only snapshots may go."""
    _make_snapshots(tmp_path, 20)
    bystanders = [
        "manifest.json",
        "IDE.current.xml",
        "IMPORT.xml",
        "compare_report.json",
        "dirty_report.json",
        "snapshot-notes.txt",  # snapshot prefix, but not an .xml
    ]
    for name in bystanders:
        (tmp_path / name).write_text("keep me", encoding="utf-8")

    sync_handlers._prune_snapshots(tmp_path.as_posix(), keep=5)

    for name in bystanders:
        assert (tmp_path / name).exists(), name


def test_survives_a_missing_directory(sync_handlers, tmp_path):
    """Pruning is a courtesy after a successful export; it must never raise."""
    assert sync_handlers._prune_snapshots((tmp_path / "nope").as_posix()) == 0


def test_prune_and_select_share_one_predicate(sync_handlers):
    """Drift here would let pruning delete the file the importer wants."""
    source = (BRIDGE_DIR / "ide_handlers_sync.py").read_text(encoding="utf-8")
    assert source.count('startswith("snapshot-")') == 1, (
        "snapshot matching was inlined again; route it through "
        "_is_snapshot_name so pruning and selection cannot disagree"
    )
    assert sync_handlers._is_snapshot_name("snapshot-20260731_172100.xml")
    assert not sync_handlers._is_snapshot_name("snapshot-notes.txt")
    assert not sync_handlers._is_snapshot_name("IDE.current.xml")


def test_default_retention_matches_the_backup_limit(sync_handlers):
    """Two retention knobs that disagree would only confuse."""
    settings = (
        Path(__file__).parent.parent.parent
        / "products"
        / "cds-text-sync"
        / "src"
        / "cds_text_sync"
        / "engine"
        / "_project_settings.py"
    ).read_text(encoding="utf-8")
    assert '"backup_retention_count": 10,' in settings
    assert sync_handlers.SNAPSHOT_RETENTION_COUNT == 10
