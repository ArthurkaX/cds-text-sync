# -*- coding: utf-8 -*-
"""
test_folder_writer.py – Unit tests for folder_writer.py (Priority 5).

Uses ``tmp_path`` but keeps tests small.  Uses minimal
``xml.etree.ElementTree.Element`` values for XML-path tests.
"""

import codecs
import json
import os

from _project_model import ProjectModel, ProjectNode
from folder_writer import FolderWriter


def _write_manifest(dump_path, manifest_data):
    with open(os.path.join(dump_path, "manifest.json"), "w") as f:
        json.dump(manifest_data, f, indent=2)


class TestFolderWriterWrite:
    def test_writes_manifest_with_view_root(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        writer = FolderWriter(views, dump)
        model = ProjectModel()
        writer.write(model)
        manifest_path = os.path.join(dump, "manifest.json")
        assert os.path.exists(manifest_path)
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        assert manifest["view_root"] == "views"

    def test_writes_xml_file_for_node_with_entry_element(self, tmp_path):
        import xml.etree.ElementTree as ET

        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        node = ProjectNode("g1", "MyObj")
        node.display_path = ["Folder"]
        root_elem = ET.Element("Single", {"Name": "Object"})
        ET.SubElement(root_elem, "Single", {"Name": "Data"}).text = "hello"
        node.entry_element = root_elem
        model = ProjectModel()
        model.add_node(node)
        writer = FolderWriter(views, dump)
        writer.write(model)
        xml_path = os.path.join(views, "Folder", "MyObj.xml")
        assert os.path.exists(xml_path)

    def test_selected_guid_export_preserves_other_entries(self, tmp_path):
        """When exporting with ``selected_guids``, the writer should replace
        only selected manifest entries and preserve non-selected ones."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
        # Pre-existing manifest with two entries
        _write_manifest(
            dump,
            {
                "view_root": views,
                "ns": "",
                "entries": [
                    {
                        "guid": "g1",
                        "name": "A",
                        "type_guid": "",
                        "parent_guid": None,
                        "view_path": "a.st",
                    },
                    {
                        "guid": "g2",
                        "name": "B",
                        "type_guid": "",
                        "parent_guid": None,
                        "view_path": "b.st",
                    },
                ],
            },
        )
        # Write files for g1 and g2
        _write_file(views, "a.st", "old code a")
        _write_file(views, "b.st", "old code b")
        node = ProjectNode("g2", "B_Updated")
        node.display_path = []
        node.code = "new code b"
        node.entry_element = None
        model = ProjectModel()
        model.add_node(node)
        writer = FolderWriter(views, dump, selected_guids=["g2"])
        writer.write(model)
        with open(os.path.join(dump, "manifest.json"), "r") as f:
            manifest = json.load(f)
        entries_by_guid = {e["guid"]: e for e in manifest["entries"]}
        assert entries_by_guid["g1"]["name"] == "A"
        assert entries_by_guid["g1"]["view_path"] == "a.st"
        assert entries_by_guid["g2"]["name"] == "B_Updated"


def _write_file(base_path, relative_path, content):
    full = os.path.join(base_path, relative_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with codecs.open(full, "w", "utf-8") as f:
        f.write(content)


# ===================================================================
# _safe_path_in_root
# ===================================================================


class TestSafePathInRoot:
    def test_rejects_reserved_root_children_dot_dump(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        writer = FolderWriter(views, dump)
        assert writer._safe_path_in_root(".dump/something.xml", views) is None

    def test_rejects_paths_outside_view_root(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        writer = FolderWriter(views, dump)
        assert writer._safe_path_in_root("../../etc/passwd", views) is None

    def test_accepts_normal_relative_path(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        writer = FolderWriter(views, dump)
        result = writer._safe_path_in_root("Folder/Obj.xml", views)
        assert result is not None


# ===================================================================
# Orphan projection cleanup
# ===================================================================


class TestRemoveOrphanProjectionFiles:
    def test_removes_stale_st_files_only_when_extension_enabled(self, tmp_path):
        """Orphan ``.st`` files are removed only when the ``.st`` projection
        extension is enabled in the profile."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
        # Write an orphan .st file
        _write_file(views, "orphan.st", "PROGRAM Orphan\nEND_PROGRAM")
        profile = {
            "projections": [
                {
                    "id": "st_proj",
                    "kind": "pou",
                    "format": "st",
                    "default_enabled": True,
                },
            ],
        }
        projections = {"st_proj": True}
        writer = FolderWriter(views, dump, profile=profile, projections=projections)
        emitted = set()
        writer._remove_orphan_projection_files(emitted)
        assert not os.path.exists(os.path.join(views, "orphan.st"))

    def test_preserves_st_files_when_extension_not_enabled(self, tmp_path):
        """When the ``.st`` projection is not enabled, orphan ``.st`` files
        should *not* be cleaned up."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
        _write_file(views, "orphan.st", "PROGRAM Orphan\nEND_PROGRAM")
        profile = {"projections": []}
        writer = FolderWriter(views, dump, profile=profile, projections={})
        emitted = set()
        writer._remove_orphan_projection_files(emitted)
        assert os.path.exists(os.path.join(views, "orphan.st"))


# ===================================================================
# Projection writing emits hashes and import_safe metadata
# ===================================================================


class TestProjectionWritingMetadata:
    def test_writes_projection_hashes_and_import_safe(self, tmp_path):
        import xml.etree.ElementTree as ET

        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
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
            "guid_aliases": {
                "pou": ["6f9dac99-8de1-4efc-8465-68ac443b7d08"],
            },
            "projections": [
                {
                    "id": "st_proj",
                    "kind": "pou",
                    "format": "st",
                    "default_enabled": True,
                    "import_safe": True,
                },
            ],
        }
        projections = {"st_proj": True}
        writer = FolderWriter(views, dump, profile=profile, projections=projections)
        writer.write(model)
        with open(os.path.join(dump, "manifest.json"), "r") as f:
            manifest = json.load(f)
        entry = manifest["entries"][0]
        assert "projection_hashes" in entry
        assert "projection_import_safe" in entry
