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
        extension is enabled in the profile (and removal is opted into)."""
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
        writer = FolderWriter(
            views, dump, profile=profile, projections=projections, remove_orphans=True
        )
        emitted = set()
        writer._remove_orphan_projection_files(emitted)
        assert not os.path.exists(os.path.join(views, "orphan.st"))

    def test_preserves_orphans_in_default_mode(self, tmp_path):
        """Without ``remove_orphans`` the export never deletes files it did
        not regenerate - they may be hand-authored (pending import)."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
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
        writer._remove_orphan_projection_files(set())
        assert os.path.exists(os.path.join(views, "orphan.st"))

    def test_overwrite_dirty_alone_does_not_remove_orphans(self, tmp_path):
        """Orphan removal is decoupled from dirty overwrite: --overwrite-dirty
        must not delete unmanaged files."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
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
        writer = FolderWriter(
            views,
            dump,
            profile=profile,
            projections={"st_proj": True},
            overwrite_dirty=True,
        )
        writer._remove_orphan_projection_files(set())
        assert os.path.exists(os.path.join(views, "orphan.st"))

    def test_preserves_st_files_when_extension_not_enabled(self, tmp_path):
        """When the ``.st`` projection is not enabled, orphan ``.st`` files
        should *not* be cleaned up."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
        _write_file(views, "orphan.st", "PROGRAM Orphan\nEND_PROGRAM")
        profile = {"projections": []}
        writer = FolderWriter(
            views, dump, profile=profile, projections={}, remove_orphans=True
        )
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


# ===================================================================
# Dirty guard: skip vs overwrite of locally-modified files
# ===================================================================


def _pou_model_and_profile():
    import xml.etree.ElementTree as ET

    node = ProjectNode("g1", "MyObj", node_type="6f9dac99-8de1-4efc-8465-68ac443b7d08")
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
            },
        ],
    }
    return model, profile, {"st_proj": True}


def _read_file(base_path, relative_path):
    with codecs.open(os.path.join(base_path, relative_path), "r", "utf-8") as f:
        return f.read()


def _load_manifest(dump):
    with open(os.path.join(dump, "manifest.json"), "r") as f:
        return json.load(f)


class TestDirtyGuard:
    def _first_export(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        model, profile, projections = _pou_model_and_profile()
        FolderWriter(views, dump, profile=profile, projections=projections).write(
            model
        )
        return views, dump, model, profile, projections

    def test_skip_dirty_preserves_file_and_carries_forward_hashes(self, tmp_path):
        views, dump, model, profile, projections = self._first_export(tmp_path)
        st_rel = os.path.join("Folder", "MyObj.st")
        original_hash = _load_manifest(dump)["entries"][0]["projection_hashes"][
            list(_load_manifest(dump)["entries"][0]["projection_hashes"])[0]
        ]
        edited = "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR\n\n// local edit\nx := 2;"
        _write_file(views, st_rel, edited)

        # Second export in default (skip) mode
        FolderWriter(views, dump, profile=profile, projections=projections).write(
            model
        )

        assert _read_file(views, st_rel) == edited
        entry = _load_manifest(dump)["entries"][0]
        carried = list(entry["projection_hashes"].values())[0]
        assert carried == original_hash

    def test_overwrite_dirty_regenerates_and_rehashes(self, tmp_path):
        views, dump, model, profile, projections = self._first_export(tmp_path)
        st_rel = os.path.join("Folder", "MyObj.st")
        generated = _read_file(views, st_rel)
        original_hash = list(
            _load_manifest(dump)["entries"][0]["projection_hashes"].values()
        )[0]
        edited = generated + "\n// local edit"
        _write_file(views, st_rel, edited)

        FolderWriter(
            views,
            dump,
            profile=profile,
            projections=projections,
            overwrite_dirty=True,
        ).write(model)

        assert _read_file(views, st_rel) == generated
        entry = _load_manifest(dump)["entries"][0]
        assert list(entry["projection_hashes"].values())[0] == original_hash

    def test_skip_dirty_preserves_locally_modified_xml(self, tmp_path):
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

        xml_rel = os.path.join("Folder", "MyObj.xml")
        original_hash = _load_manifest(dump)["entries"][0]["hash"]
        edited = "<Single Name='Object'><Single Name='Data'>edited</Single></Single>"
        _write_file(views, xml_rel, edited)

        FolderWriter(views, dump).write(model)

        assert _read_file(views, xml_rel) == edited
        entry = _load_manifest(dump)["entries"][0]
        assert entry["hash"] == original_hash

    def test_clean_second_export_rewrites_normally(self, tmp_path):
        views, dump, model, profile, projections = self._first_export(tmp_path)
        st_rel = os.path.join("Folder", "MyObj.st")
        generated = _read_file(views, st_rel)

        FolderWriter(views, dump, profile=profile, projections=projections).write(
            model
        )
        assert _read_file(views, st_rel) == generated


# ===================================================================
# Sync-mode init lock
# ===================================================================


class TestSyncModeLock:
    def test_sync_mode_change_after_manifest_raises(self, tmp_path):
        import pytest

        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        model = ProjectModel()
        FolderWriter(views, dump).write(model)

        writer = FolderWriter(views, dump, sync_mode="text_first")
        with pytest.raises(RuntimeError, match="Sync mode is fixed"):
            writer.write(model)

    def test_same_sync_mode_re_export_is_allowed(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        model = ProjectModel()
        FolderWriter(views, dump).write(model)
        assert FolderWriter(views, dump, sync_mode="xml_first").write(model)


# ===================================================================
# Text-first export: xml mirror in .dump, per-kind exceptions, orphans
# ===================================================================


class TestTextFirstExport:
    def _write_text_first(self, tmp_path, xml_in_view_kinds=None, projections=None):
        from _project_profiles import effective_projection_selection

        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        model, profile, base_projections = _pou_model_and_profile()
        effective = effective_projection_selection(
            profile, projections if projections is not None else {}, "text_first"
        )
        writer = FolderWriter(
            views,
            dump,
            profile=profile,
            projections=effective,
            sync_mode="text_first",
            xml_in_view_kinds=xml_in_view_kinds,
        )
        writer.write(model)
        return views, dump, model, profile, effective

    def test_xml_written_to_dump_mirror_with_manifest_markers(self, tmp_path):
        views, dump, model, profile, effective = self._write_text_first(tmp_path)
        st_path = os.path.join(views, "Folder", "MyObj.st")
        view_xml_path = os.path.join(views, "Folder", "MyObj.xml")
        mirror_xml_path = os.path.join(dump, "xml", "Folder", "MyObj.xml")
        assert os.path.exists(st_path)
        assert not os.path.exists(view_xml_path)
        assert os.path.exists(mirror_xml_path)
        manifest = _load_manifest(dump)
        assert manifest["sync_mode"] == "text_first"
        entry = manifest["entries"][0]
        assert entry["xml_root"] == "dump"
        assert entry["projection_paths"]

    def test_st_projection_forced_even_when_selection_empty(self, tmp_path):
        # projections={} (nothing opted in), yet text-first must emit .st
        views, dump, _, _, effective = self._write_text_first(
            tmp_path, projections={}
        )
        assert os.path.exists(os.path.join(views, "Folder", "MyObj.st"))
        assert "st_proj" in effective

    def test_xml_in_view_kind_stays_in_view(self, tmp_path):
        import xml.etree.ElementTree as ET

        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        node = ProjectNode(
            "g2", "MainVisu", node_type="8fbcbc16-9394-4b1c-8f8f-1d2c5ee44dbb"
        )
        node.display_path = ["Visus"]
        root_elem = ET.Element("Single", {"Name": "Object"})
        ET.SubElement(root_elem, "Single", {"Name": "Data"}).text = "visu-data"
        node.entry_element = root_elem
        model = ProjectModel()
        model.add_node(node)
        profile = {
            "guid_aliases": {"visu": ["8fbcbc16-9394-4b1c-8f8f-1d2c5ee44dbb"]},
            "projections": [],
        }
        writer = FolderWriter(
            views,
            dump,
            profile=profile,
            sync_mode="text_first",
            xml_in_view_kinds=["visu"],
        )
        writer.write(model)
        assert os.path.exists(os.path.join(views, "Visus", "MainVisu.xml"))
        assert not os.path.exists(os.path.join(dump, "xml", "Visus", "MainVisu.xml"))
        entry = _load_manifest(dump)["entries"][0]
        assert "xml_root" not in entry

    def test_orphan_removal_spares_unmanaged_st_even_with_removal_opt_in(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(dump, exist_ok=True)
        os.makedirs(views, exist_ok=True)
        _write_file(views, "HandMade.st", "PROGRAM HandMade\nEND_PROGRAM")
        model, profile, projections = _pou_model_and_profile()
        writer = FolderWriter(
            views,
            dump,
            profile=profile,
            projections=projections,
            sync_mode="text_first",
            remove_orphans=True,
        )
        writer.write(model)
        assert os.path.exists(os.path.join(views, "HandMade.st"))

    def test_stale_mirror_files_are_pruned_on_full_export(self, tmp_path):
        views, dump, model, profile, effective = self._write_text_first(tmp_path)
        stale = os.path.join(dump, "xml", "Old", "Gone.xml")
        os.makedirs(os.path.dirname(stale))
        with codecs.open(stale, "w", "utf-8") as f:
            f.write("<stale />")
        FolderWriter(
            views,
            dump,
            profile=profile,
            projections=effective,
            sync_mode="text_first",
        ).write(model)
        assert not os.path.exists(stale)
        assert os.path.exists(os.path.join(dump, "xml", "Folder", "MyObj.xml"))

    def test_rename_prunes_old_mirror_and_view_files(self, tmp_path):
        views, dump, model, profile, effective = self._write_text_first(tmp_path)
        # Rename the object and re-export: old .st and mirror xml must go away.
        node = model.nodes["g1"]
        node.name = "Renamed"
        node.output_name = None
        FolderWriter(
            views,
            dump,
            profile=profile,
            projections=effective,
            sync_mode="text_first",
        ).write(model)
        assert not os.path.exists(os.path.join(views, "Folder", "MyObj.st"))
        assert not os.path.exists(os.path.join(dump, "xml", "Folder", "MyObj.xml"))
        assert os.path.exists(os.path.join(views, "Folder", "Renamed.st"))
        assert os.path.exists(os.path.join(dump, "xml", "Folder", "Renamed.xml"))
