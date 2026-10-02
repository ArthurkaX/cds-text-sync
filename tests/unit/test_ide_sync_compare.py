# -*- coding: utf-8 -*-
"""
test_ide_sync_compare.py -- `cts project compare` must compare objects, not names.

The handler used to collect every Name attribute in the snapshot XML -- which
on a native export is almost entirely property keys -- and compare that set
with the project's object names. A real 187-object project therefore reported a
common count of 1. These tests pin the fix: objects come from the EntryList
entries (identity from MetaObject), and a project in sync with its snapshot
reports everything common and nothing one-sided.

The daemon modules are IronPython-only, so their CODESYS/.NET dependencies are
stubbed before import; ide_runtime_common is real, since the comparison uses
its object accessors.
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

_STUBBED = (
    "ide_daemon_state",
    "ide_daemon_helpers",
    "ide_st_text",
)

_GUID_A = "11111111-1111-1111-1111-111111111111"
_GUID_B = "22222222-2222-2222-2222-222222222222"
_GUID_C = "33333333-3333-3333-3333-333333333333"
_TYPE_POU = "6f9dac99-8de1-4efc-8465-68ac443b7d08"


@pytest.fixture(scope="module")
def sync_handlers():
    """Load ide_handlers_sync with its CODESYS-only dependencies stubbed out."""
    logged = []

    def _stub(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        return module

    if str(BRIDGE_DIR) not in sys.path:
        sys.path.insert(0, str(BRIDGE_DIR))

    saved = {name: sys.modules.get(name) for name in _STUBBED}
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
        "ide_handlers_sync_compare_under_test", BRIDGE_DIR / "ide_handlers_sync.py"
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


class _FakeObject(object):
    def __init__(self, name, guid, type_guid=_TYPE_POU):
        self.guid = guid
        self.type = type_guid
        self._name = name

    def get_name(self):
        return self._name


class _FakeProject(object):
    def __init__(self, objects):
        self._objects = objects

    def get_children(self, recursive=False):
        return list(self._objects)


def _entry(name, guid, type_guid=_TYPE_POU, path=("Device", "Application")):
    path_xml = "".join(
        "<Single Type=\"string\">{0}</Single>".format(part) for part in path
    )
    return (
        "<Single>"
        "<Single Name=\"MetaObject\">"
        "<Single Name=\"Guid\" Type=\"System.Guid\">{guid}</Single>"
        "<Single Name=\"ParentGuid\" Type=\"System.Guid\">"
        "00000000-0000-0000-0000-000000000000</Single>"
        "<Single Name=\"Name\" Type=\"string\">{name}</Single>"
        "<Single Name=\"TypeGuid\" Type=\"System.Guid\">{type_guid}</Single>"
        "</Single>"
        "<Array Name=\"Path\">{path}</Array>"
        "<Single Name=\"Object\">"
        "<Single Name=\"Implementation\">"
        "<Single Name=\"TextDocument\">"
        "<Single Name=\"TextBlobForSerialisation\">body of {name}</Single>"
        "</Single>"
        "</Single>"
        # A nested MetaObject inside the object body: not an object of its own.
        "<Single Name=\"MetaObject\">"
        "<Single Name=\"Guid\" Type=\"System.Guid\">"
        "99999999-9999-9999-9999-999999999999</Single>"
        "<Single Name=\"Name\" Type=\"string\">Nested</Single>"
        "</Single>"
        "</Single>"
        "</Single>"
    ).format(guid=guid, name=name, type_guid=type_guid, path=path_xml)


def _write_snapshot(directory, filename, objects):
    entries = "".join(_entry(**obj) for obj in objects)
    xml = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<Project>"
        "<StructuredView Guid=\"{{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}}\">"
        "<Single>"
        "<List2 Name=\"EntryList\">{entries}</List2>"
        "</Single>"
        "</StructuredView>"
        "</Project>"
    ).format(entries=entries)
    path = directory / filename
    path.write_text(xml, encoding="utf-8")
    return path


def _use_project(sync_handlers, objects):
    sync_handlers._get_active_project = lambda: (_FakeProject(objects), None)


def _use_sync_folder(sync_handlers, sync_dir):
    sync_handlers._get_sync_folder = lambda: (str(sync_dir), None)


def test_property_names_are_not_objects(sync_handlers, tmp_path):
    """The snapshot's property keys must never be counted as project objects."""
    path = _write_snapshot(
        tmp_path,
        "snapshot-20260101_000000.xml",
        [
            {"name": "MAIN", "guid": _GUID_A},
            {"name": "Globals", "guid": _GUID_B},
        ],
    )

    from ide_snapshot_objects import snapshot_objects

    objects, entry_lists = snapshot_objects(str(path))
    names = sorted(obj["name"] for obj in objects)

    assert entry_lists == 1
    assert names == ["Globals", "MAIN"]
    for property_name in ("MetaObject", "Guid", "Path", "TextDocument", "Nested"):
        assert property_name not in names


def test_all_common_when_project_matches_snapshot(sync_handlers, tmp_path):
    path = _write_snapshot(
        tmp_path,
        "snapshot-20260101_000000.xml",
        [
            {"name": "MAIN", "guid": _GUID_A},
            {"name": "Globals", "guid": _GUID_B},
            {"name": "Helper", "guid": _GUID_C},
        ],
    )
    _use_project(
        sync_handlers,
        [
            _FakeObject("MAIN", _GUID_A),
            _FakeObject("Globals", _GUID_B),
            _FakeObject("Helper", _GUID_C),
        ],
    )

    result = sync_handlers._cmd_sync_compare({"against": str(path)})

    assert result["ok"] is True
    data = result["data"]
    assert data["project_objects"] == 3
    assert data["snapshot_objects"] == 3
    assert data["common_count"] == 3
    assert data["in_project_only"] == []
    assert data["in_snapshot_only"] == []


def test_one_sided_objects_are_reported_by_path(sync_handlers, tmp_path):
    path = _write_snapshot(
        tmp_path,
        "snapshot-20260101_000000.xml",
        [
            {"name": "MAIN", "guid": _GUID_A},
            {"name": "NewInSnapshot", "guid": _GUID_C},
        ],
    )
    _use_project(
        sync_handlers,
        [
            _FakeObject("MAIN", _GUID_A),
            _FakeObject("NewInProject", _GUID_B),
        ],
    )

    result = sync_handlers._cmd_sync_compare({"against": str(path)})

    data = result["data"]
    assert data["common_count"] == 1
    # The project side has no tree path in the Scripting API, so it is named;
    # the snapshot side carries the Path array CODESYS shows.
    assert data["in_project_only"] == ["NewInProject"]
    assert data["in_snapshot_only"] == ["Device\\Application\\NewInSnapshot"]


def test_compare_without_against_uses_the_newest_snapshot(sync_handlers, tmp_path):
    dump = tmp_path / ".dump"
    dump.mkdir()
    _write_snapshot(
        dump, "snapshot-20260101_000000.xml", [{"name": "Old", "guid": _GUID_B}]
    )
    newest = _write_snapshot(
        dump, "snapshot-20260202_000000.xml", [{"name": "MAIN", "guid": _GUID_A}]
    )
    _use_project(sync_handlers, [_FakeObject("MAIN", _GUID_A)])
    _use_sync_folder(sync_handlers, tmp_path)

    result = sync_handlers._cmd_sync_compare({})

    assert result["ok"] is True
    assert result["data"]["snapshot"] == str(newest)
    assert result["data"]["common_count"] == 1
    assert result["data"]["in_project_only"] == []


def test_compare_without_a_snapshot_fails_clearly(sync_handlers, tmp_path):
    dump = tmp_path / ".dump"
    dump.mkdir()
    _use_project(sync_handlers, [])
    _use_sync_folder(sync_handlers, tmp_path)

    result = sync_handlers._cmd_sync_compare({})

    assert result["ok"] is False
    assert "No snapshot XML files" in result["error"]


def test_task_reference_nodes_are_not_compared(sync_handlers, tmp_path):
    """Task "call" nodes are tree entries, not exported objects."""
    path = _write_snapshot(
        tmp_path, "snapshot-20260101_000000.xml", [{"name": "MAIN", "guid": _GUID_A}]
    )
    task_ref_type = "413e2a7d-adb1-4d2c-be29-6ae6e4fab820"
    _use_project(
        sync_handlers,
        [
            _FakeObject("MAIN", _GUID_A),
            # Same name as the POU, but a task-call reference with its own guid.
            _FakeObject("MAIN", _GUID_B, type_guid=task_ref_type),
        ],
    )

    result = sync_handlers._cmd_sync_compare({"against": str(path)})

    data = result["data"]
    assert data["common_count"] == 1
    assert data["in_project_only"] == []
    assert data["in_snapshot_only"] == []
    assert data["task_reference_nodes_skipped"] == 1


def test_alias_guid_falls_back_to_type_and_name(sync_handlers, tmp_path):
    """An object exposed under an alias GUID still matches its exported twin."""
    path = _write_snapshot(
        tmp_path,
        "snapshot-20260101_000000.xml",
        [
            {
                "name": "__VisualizationStyle",
                "guid": _GUID_A,
                "type_guid": "8e687a04-7ca7-42d3-be06-fcbda676c5ef",
            }
        ],
    )
    _use_project(
        sync_handlers,
        [
            _FakeObject(
                "__VisualizationStyle",
                _GUID_C,
                type_guid="8e687a04-7ca7-42d3-be06-fcbda676c5ef",
            )
        ],
    )

    result = sync_handlers._cmd_sync_compare({"against": str(path)})

    data = result["data"]
    assert data["common_count"] == 1
    assert data["in_project_only"] == []
    assert data["in_snapshot_only"] == []


def test_a_non_snapshot_file_is_rejected(sync_handlers, tmp_path):
    plain = tmp_path / "not-a-snapshot.xml"
    plain.write_text("<Project><Thing Name=\"MAIN\"/></Project>", encoding="utf-8")
    _use_project(sync_handlers, [_FakeObject("MAIN", _GUID_A)])

    result = sync_handlers._cmd_sync_compare({"against": str(plain)})

    assert result["ok"] is False
    assert "EntryList" in result["error"]
