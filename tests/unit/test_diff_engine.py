# -*- coding: utf-8 -*-
"""
test_diff_engine.py – Unit tests for diff_engine.py (Priority 3).

Uses synthetic ProjectModel instances with small helper functions.
"""

import pytest
import xml.etree.ElementTree as ET
from _project_model import COLLAPSED_OBJECT_TYPE_GUIDS, ProjectModel, ProjectNode
from diff_engine import DiffEngine

# ===================================================================
# Helpers
# ===================================================================


def _make_node(guid, name="Obj", code=None, xml_text=None, node_type=None, **meta):
    node = ProjectNode(guid, name, node_type=node_type)
    node.code = code
    node.xml_text = xml_text
    node.metadata.update(meta)
    return node


def model_with(*nodes):
    """Build a ProjectModel containing the given nodes."""
    model = ProjectModel()
    for node in nodes:
        model.add_node(node)
    return model


def _pou_xml(declaration, implementation):
    root = ET.Element("Single", {"Name": "Object"})
    decl_parent = ET.SubElement(root, "Single", {"Name": "Declaration"})
    decl = ET.SubElement(
        decl_parent, "Single", {"Name": "TextBlobForSerialisation"}
    )
    decl.text = declaration
    impl_parent = ET.SubElement(root, "Single", {"Name": "Implementation"})
    impl = ET.SubElement(
        impl_parent, "Single", {"Name": "TextBlobForSerialisation"}
    )
    impl.text = implementation
    return ET.tostring(root, encoding="unicode")


# A sample profile with a collapsed-object type and export_only override.
COLLAPSED_TYPE = list(COLLAPSED_OBJECT_TYPE_GUIDS)[0]

_PROFILE_EXPORT_ONLY = {
    "guid_aliases": {
        "pou": [COLLAPSED_TYPE],
        "gvl": ["00000000-0000-0000-0000-000000000001"],
    },
    "sync_direction_overrides": {
        "gvl": "export_only",
    },
}


# ===================================================================
# Unchanged / modified / added / deleted
# ===================================================================


class TestDiffEngineBasic:
    def test_unchanged_when_contents_match(self):
        node = _make_node("g1", code="same code")
        ide = model_with(node)
        folder = model_with(_make_node("g1", code="same code"))
        result = DiffEngine(ide, folder).compare()
        assert "g1" in result["unchanged"]
        assert "g1" not in result["modified"]

    def test_modified_when_code_differs(self):
        ide = model_with(_make_node("g1", code="old"))
        folder = model_with(_make_node("g1", code="new"))
        result = DiffEngine(ide, folder).compare()
        assert "g1" in result["modified"]

    def test_modified_when_normalized_xml_differs(self):
        ide = model_with(
            _make_node("g1", xml_text="<Root><Single Name='Data'>old</Single></Root>")
        )
        folder = model_with(
            _make_node("g1", xml_text="<Root><Single Name='Data'>new</Single></Root>")
        )
        result = DiffEngine(ide, folder).compare()
        assert "g1" in result["modified"]

    def test_added_when_only_in_folder(self):
        folder = model_with(_make_node("g1", code="code"))
        ide = model_with()
        result = DiffEngine(ide, folder).compare()
        assert "g1" in result["added"]

    def test_deleted_when_only_in_ide(self):
        ide = model_with(_make_node("g1", code="code"))
        folder = model_with()
        result = DiffEngine(ide, folder).compare()
        assert "g1" in result["deleted"]


# ===================================================================
# Nested / collapsed object
# ===================================================================


class TestDiffEngineCollapsed:
    def test_nested_ide_object_ignored_when_not_in_folder(self):
        """A nested IDE node under a collapsed parent is excluded from the
        diff when it does not appear in the folder model."""
        parent = _make_node("p1", name="ParentPOU", node_type=COLLAPSED_TYPE)
        parent.display_path = ["Folder"]
        child = _make_node("c1", name="Method", parent_guid="p1")
        child.display_path = ["Folder", "ParentPOU"]
        ide = model_with(parent, child)
        folder = model_with(parent)
        result = DiffEngine(ide, folder).compare()
        assert "c1" not in result["deleted"]

    def test_nested_object_compared_when_present_in_folder(self):
        """A nested node under a collapsed parent that *is* present in the
        folder model should appear in the diff."""
        parent = _make_node("p1", name="ParentPOU", node_type=COLLAPSED_TYPE)
        parent.display_path = ["Folder"]
        child_ide = _make_node("c1", name="Method", parent_guid="p1", code="old")
        child_ide.display_path = ["Folder", "ParentPOU"]
        child_folder = _make_node("c1", name="Method", code="new")
        ide = model_with(parent, child_ide)
        folder = model_with(parent, child_folder)
        result = DiffEngine(ide, folder).compare()
        assert "c1" in result["modified"]


# ===================================================================
# Projection metadata
# ===================================================================


class TestDiffEngineProjection:
    def test_matching_st_projection_demotes_to_unchanged(self):
        """After a daemon-side POU update, the projection hash can still look
        stale until the next export, but compare should trust equal .st text.
        """
        node_ide = _make_node("g1", xml_text=_pou_xml("PROGRAM MAIN", "x := 1;"))
        node_folder = _make_node(
            "g1",
            xml_text="<Single><DifferentFormatting /></Single>",
            projection_changed_paths=["MyObj.st"],
            projection_contents={
                "MyObj.st": "PROGRAM MAIN\n\n// --- implementation ---\n\nx := 1;"
            },
        )
        result = DiffEngine(model_with(node_ide), model_with(node_folder)).compare()
        assert "g1" in result["unchanged"]
        assert "g1" not in result["modified"]

    def test_changed_st_projection_marks_object_modified(self):
        node_ide = _make_node("g1", xml_text=_pou_xml("PROGRAM MAIN", "x := 1;"))
        node_folder = _make_node(
            "g1",
            xml_text="<Single><DifferentFormatting /></Single>",
            projection_changed_paths=["MyObj.st"],
            projection_contents={
                "MyObj.st": "PROGRAM MAIN\n// --- implementation ---\nx := 2;"
            },
        )
        result = DiffEngine(model_with(node_ide), model_with(node_folder)).compare()
        assert "g1" in result["modified"]

    def test_projection_conflict_surfaced(self):
        node_folder = _make_node("g1", code="same", projection_conflict=True)
        node_ide = _make_node("g1", code="same")
        result = DiffEngine(model_with(node_ide), model_with(node_folder)).compare()
        assert "g1" in result.get("projection_conflicts", [])

    def test_unsupported_projection_changes_surfaced(self):
        """A projection change on a non-.st, non-import-safe CSV path with an
        extractor should be surfaced under ``unsupported_projection_changes``."""
        node_ide = _make_node("g1", code="same")
        node_folder = _make_node(
            "g1",
            code="same",
            projection_changed_paths=["data.unknown"],
            projection_extractors={"data.unknown": "custom_extractor"},
            projection_import_safe={"data.unknown": False},
        )
        result = DiffEngine(model_with(node_ide), model_with(node_folder)).compare()
        unsupported = result.get("unsupported_projection_changes", {})
        assert "g1" in unsupported
        assert "data.unknown" in unsupported["g1"]

    def test_import_safe_csv_projection_does_not_become_unsupported(self):
        """Import-safe CSV projection changes should NOT be classified as
        unsupported."""
        node_ide = _make_node("g1", code="same")
        node_folder = _make_node(
            "g1",
            code="same",
            projection_changed_paths=["texts.csv"],
            projection_extractors={"texts.csv": "textlist_csv"},
            projection_import_safe={"texts.csv": True},
        )
        result = DiffEngine(model_with(node_ide), model_with(node_folder)).compare()
        unsupported = result.get("unsupported_projection_changes", {})
        assert "g1" not in unsupported


# ===================================================================
# Export-only sync-direction override
# ===================================================================


class TestDiffEngineExportOnly:
    def test_export_only_demotes_modified_to_unchanged(self):
        node_type = "00000000-0000-0000-0000-000000000001"
        ide_node = _make_node("g1", code="old", node_type=node_type)
        folder_node = _make_node("g1", code="new", node_type=node_type)
        result = DiffEngine(
            model_with(ide_node),
            model_with(folder_node),
            profile=_PROFILE_EXPORT_ONLY,
        ).compare()
        assert "g1" not in result["modified"]
        assert "g1" in result["unchanged"]

    def test_export_only_demotes_added_to_unchanged(self):
        node_type = "00000000-0000-0000-0000-000000000001"
        folder_node = _make_node("g1", code="new", node_type=node_type)
        result = DiffEngine(
            model_with(),
            model_with(folder_node),
            profile=_PROFILE_EXPORT_ONLY,
        ).compare()
        assert "g1" not in result["added"]
        assert "g1" in result["unchanged"]

    def test_export_only_demotes_deleted_to_unchanged(self):
        node_type = "00000000-0000-0000-0000-000000000001"
        ide_node = _make_node("g1", code="old", node_type=node_type)
        result = DiffEngine(
            model_with(ide_node),
            model_with(),
            profile=_PROFILE_EXPORT_ONLY,
        ).compare()
        assert "g1" not in result["deleted"]
        assert "g1" in result["unchanged"]
