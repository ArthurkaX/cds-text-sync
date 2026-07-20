# -*- coding: utf-8 -*-
"""
test_dirty_scan.py - Unit tests for _dirty_scan.py (export dirty preflight).
"""

import codecs
import json
import os

import xml.etree.ElementTree as ET

from _dirty_scan import dirty_view_paths, scan_dirty
from _project_model import ProjectModel, ProjectNode
from folder_writer import FolderWriter
from xml_helpers import sha1_hex


def _write_file(base_path, relative_path, content, newline=None):
    full = os.path.join(base_path, relative_path)
    parent = os.path.dirname(full)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if newline is None:
        with codecs.open(full, "w", "utf-8") as f:
            f.write(content)
    else:
        with open(full, "wb") as f:
            f.write(content.replace("\n", newline).encode("utf-8"))
    return full


def _manifest(entries, view_root="views"):
    return {"view_root": view_root, "ns": "", "entries": entries}


class TestScanDirty:
    def test_empty_manifest_reports_nothing(self, tmp_path):
        report = scan_dirty(None, str(tmp_path))
        assert report == {"dirty": [], "orphans": []}

    def test_detects_dirty_xml_and_projection(self, tmp_path):
        views = str(tmp_path / "views")
        original_xml = "<Single Name='Object'/>"
        original_st = "PROGRAM P\nEND_PROGRAM"
        _write_file(views, "A.xml", "<Single Name='Edited'/>")
        _write_file(views, "A.st", "PROGRAM P\n// edited\nEND_PROGRAM")
        manifest = _manifest(
            [
                {
                    "guid": "g1",
                    "xml_path": "A.xml",
                    "hash": sha1_hex(original_xml),
                    "projection_paths": ["A.st"],
                    "projection_hashes": {"A.st": sha1_hex(original_st)},
                }
            ]
        )
        report = scan_dirty(manifest, views)
        paths = sorted(item["path"] for item in report["dirty"])
        assert paths == ["A.st", "A.xml"]
        kinds = dict((item["path"], item["file_kind"]) for item in report["dirty"])
        assert kinds["A.xml"] == "xml"
        assert kinds["A.st"] == "st"

    def test_clean_files_and_missing_files_are_not_dirty(self, tmp_path):
        views = str(tmp_path / "views")
        content = "<Single Name='Object'/>"
        _write_file(views, "A.xml", content)
        manifest = _manifest(
            [
                {"guid": "g1", "xml_path": "A.xml", "hash": sha1_hex(content)},
                {"guid": "g2", "xml_path": "Missing.xml", "hash": "deadbeef"},
            ]
        )
        report = scan_dirty(manifest, views)
        assert report["dirty"] == []

    def test_crlf_edit_is_dirty(self, tmp_path):
        views = str(tmp_path / "views")
        original = "PROGRAM P\nEND_PROGRAM"
        _write_file(views, "A.st", original, newline="\r\n")
        manifest = _manifest(
            [
                {
                    "guid": "g1",
                    "xml_path": "A.xml",
                    "hash": None,
                    "projection_paths": ["A.st"],
                    "projection_hashes": {"A.st": sha1_hex(original)},
                }
            ]
        )
        report = scan_dirty(manifest, views)
        assert [item["path"] for item in report["dirty"]] == ["A.st"]

    def test_dump_rooted_xml_entries_are_skipped(self, tmp_path):
        views = str(tmp_path / "views")
        _write_file(views, "A.xml", "<Single Name='Edited'/>")
        manifest = _manifest(
            [
                {
                    "guid": "g1",
                    "xml_path": "A.xml",
                    "xml_root": "dump",
                    "hash": sha1_hex("<Single Name='Object'/>"),
                }
            ]
        )
        report = scan_dirty(manifest, views)
        assert report["dirty"] == []

    def test_selected_guids_limit_the_scan(self, tmp_path):
        views = str(tmp_path / "views")
        _write_file(views, "A.xml", "edited a")
        _write_file(views, "B.xml", "edited b")
        manifest = _manifest(
            [
                {"guid": "g1", "xml_path": "A.xml", "hash": sha1_hex("a")},
                {"guid": "g2", "xml_path": "B.xml", "hash": sha1_hex("b")},
            ]
        )
        report = scan_dirty(manifest, views, selected_guids=["g2"])
        assert [item["path"] for item in report["dirty"]] == ["B.xml"]

    def test_orphans_reported_only_with_enabled_extensions(self, tmp_path):
        views = str(tmp_path / "views")
        _write_file(views, "hand_made.st", "PROGRAM H\nEND_PROGRAM")
        manifest = _manifest([])
        without = scan_dirty(manifest, views, enabled_extensions=None)
        assert without["orphans"] == []
        with_ext = scan_dirty(manifest, views, enabled_extensions={".st"})
        assert [item["path"] for item in with_ext["orphans"]] == ["hand_made.st"]

    def test_managed_projection_is_not_an_orphan(self, tmp_path):
        views = str(tmp_path / "views")
        content = "PROGRAM P\nEND_PROGRAM"
        _write_file(views, "A.st", content)
        manifest = _manifest(
            [
                {
                    "guid": "g1",
                    "xml_path": "A.xml",
                    "hash": None,
                    "projection_paths": ["A.st"],
                    "projection_hashes": {"A.st": sha1_hex(content)},
                }
            ]
        )
        report = scan_dirty(manifest, views, enabled_extensions={".st"})
        assert report["orphans"] == []
        assert report["dirty"] == []


class TestWriterRoundTrip:
    def test_fresh_export_rescans_clean(self, tmp_path):
        """Hash normalization proof: what the writer just wrote is never dirty."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump)
        node = ProjectNode(
            "g1", "MyObj", node_type="6f9dac99-8de1-4efc-8465-68ac443b7d08"
        )
        node.display_path = ["Folder"]
        root_elem = ET.Element("Single", {"Name": "Object"})
        decl = ET.SubElement(root_elem, "Single", {"Name": "TextBlobForSerialisation"})
        decl.text = "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR"
        impl = ET.SubElement(root_elem, "Single", {"Name": "TextBlobForSerialisation"})
        impl.text = "x := 1;"
        node.entry_element = root_elem
        model = ProjectModel()
        model.add_node(node)
        profile = {
            "guid_aliases": {"pou": ["6f9dac99-8de1-4efc-8465-68ac443b7d08"]},
            "projections": [
                {
                    "id": "st_proj",
                    "kind": "pou",
                    "format": "st",
                    "default_enabled": True,
                }
            ],
        }
        writer = FolderWriter(
            views, dump, profile=profile, projections={"st_proj": True}
        )
        writer.write(model)
        with open(os.path.join(dump, "manifest.json"), "r") as f:
            manifest = json.load(f)
        report = scan_dirty(manifest, views, enabled_extensions={".st"})
        assert report["dirty"] == []
        assert report["orphans"] == []
        assert dirty_view_paths(manifest, views) == set()
