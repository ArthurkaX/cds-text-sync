# -*- coding: utf-8 -*-
"""
test_discover_report.py -- CPython coverage for the shared discovery report
builder (src/ide_bridge/discover_report.py).

The builder is pure duck-typed logic over a CODESYS project's get_children()
and the on-disk sync settings/profile, so it runs under CPython with a fake
project and a bare temp dir (settings/profile default gracefully). This guards
the extraction shared by codesys_discover_operation.pyw (forward mode) and
ide_handlers_project._cmd_discover (reverse-pipe daemon).
"""

import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (os.path.join(_ROOT, "src", "ide_bridge"), os.path.join(_ROOT, "cli", "external_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import discover_report as dr  # noqa: E402


class _FakeObj(object):
    def __init__(self, name, guid, type_guid="", parent=None):
        self._name = name
        self.guid = guid
        self.type = type_guid
        self.parent = parent

    def get_name(self):
        return self._name


class _FakeProject(object):
    def __init__(self, children):
        self._children = children

    def get_name(self):
        return "TestProject"

    def get_children(self, recursive=False):
        return list(self._children)


def _sample_project():
    root = _FakeObj("App", "g-root", "{aaaa}")
    child = _FakeObj("MAIN", "g-child", "{bbbb}", parent=root)
    return _FakeProject([root, child]), root, child


def test_report_has_expected_shape_and_counts(tmp_path):
    project, _root, _child = _sample_project()
    report = dr.build_discovery_report(project, str(tmp_path), "3.5.19.0")

    assert report["status"] == "success"
    assert report["project_name"] == "TestProject"
    assert report["codesys_version"] == "3.5.19.0"
    assert report["sync_root"] == str(tmp_path)
    assert report["object_count"] == 2
    assert len(report["objects"]) == 2
    for obj in report["objects"]:
        assert set(obj) >= {"name", "kind", "type_guid", "level", "unknown", "guid"}


def test_tree_nesting_by_parent_guid(tmp_path):
    project, _root, _child = _sample_project()
    report = dr.build_discovery_report(project, str(tmp_path), "")

    by_name = {o["name"]: o for o in report["objects"]}
    # child.parent is root, and root's guid is known, so MAIN nests one level in.
    assert by_name["App"]["level"] == 0
    assert by_name["MAIN"]["level"] == 1


def test_unknown_types_detected_and_suggested_profile(tmp_path):
    # A bare temp dir yields the default profile, which knows none of the fake
    # type GUIDs, so both objects are flagged unknown and a profile is suggested.
    project, _root, _child = _sample_project()
    report = dr.build_discovery_report(project, str(tmp_path), "")

    assert report["unknown_type_count"] == 2
    assert all(o["unknown"] for o in report["objects"])
    assert "suggested_profile" in report
    assert report["suggested_profile"]["extends"] == report["profile"]


def test_enumeration_failure_returns_error(tmp_path):
    class _Boom(object):
        def get_name(self):
            return "Boom"

        def get_children(self, recursive=False):
            raise RuntimeError("cannot enumerate")

    report = dr.build_discovery_report(_Boom(), str(tmp_path), "")
    assert report["status"] == "error"
    assert "cannot enumerate" in report["error"]
