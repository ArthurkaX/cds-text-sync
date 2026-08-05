# -*- coding: utf-8 -*-
"""
test_patch_builder.py -- Unit tests for _patch_builder.py.

Tests the classification logic for native re-creates, pending creates,
text creates, and objects present on both sides.
"""

import os
import tempfile
import xml.etree.ElementTree as ET

from _patch_builder import PatchBuilder
from _project_model import ProjectModel, ProjectNode


# ===================================================================
# Helpers (same pattern as test_diff_engine.py)
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


# Minimal valid native-object XML content (e.g. a CODESYS visualization).
NATIVE_XML = (
    '<Single Name="Object" Type="{a1b2c3d4-e5f6-7890-abcd-ef1234567890}">'
    "<SomeChild Name=\"Data\">content</SomeChild></Single>"
)

# Type GUID shared for native-object tests.
NATIVE_TYPE_GUID = "{a1b2c3d4-e5f6-7890-abcd-ef1234567890}"


# ===================================================================
# Tests
# ===================================================================


class TestPatchBuilder:
    def test_manifest_listed_native_recreate(self):
        """A manifest-listed native object with xml_text, absent from the IDE,
        produces a <CreateNativeObject> in the IMPORT.xml output."""
        guid = "native-recreate-001"
        folder_node = _make_node(
            guid,
            name="MyVis",
            xml_text=NATIVE_XML,
            node_type=NATIVE_TYPE_GUID,
            view_path="/Folder",
        )
        folder_model = model_with(folder_node)
        ide_model = model_with()  # empty -- object was deleted from IDE
        diff_result = {
            "added": [guid],
            "modified": [],
            "deleted": [],
        }
        builder = PatchBuilder(diff_result, ide_model, folder_model)

        # Unit check: _is_native_recreate recognises this case
        assert builder._is_native_recreate(guid)

        # Build and verify the patch XML
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            result = builder.build_patch(path)
            assert result is True  # changes were emitted

            tree = ET.parse(path)
            root = tree.getroot()

            native_objs = root.findall(".//CreateNativeObject")
            assert len(native_objs) == 1, (
                "Expected exactly one CreateNativeObject, got %d" % len(native_objs)
            )
            obj = native_objs[0]
            assert obj.get("Name") == "MyVis"
            assert obj.get("Path") == "/Folder"
            # TypeGuid falls back to node.type for manifest-listed objects
            assert obj.get("TypeGuid") == NATIVE_TYPE_GUID

            native_xml_elem = obj.find("NativeXml")
            assert native_xml_elem is not None
            assert NATIVE_XML in native_xml_elem.text
        finally:
            os.remove(path)

    def test_pending_native_create_still_works(self):
        """A standard pending native create (pending_create=True,
        create_kind='native_xml') still produces a CreateNativeObject."""
        guid = "pending-native-001"
        folder_node = _make_node(
            guid,
            name="TestNative",
            xml_text=NATIVE_XML,
            pending_create=True,
            create_kind="native_xml",
            create_path="/Folder",
            create_name="TestNative",
            create_type_guid=NATIVE_TYPE_GUID,
        )
        folder_model = model_with(folder_node)
        ide_model = model_with()
        diff_result = {
            "added": [guid],
            "modified": [],
            "deleted": [],
        }
        builder = PatchBuilder(diff_result, ide_model, folder_model)

        assert builder._is_pending_create(guid)
        assert builder._is_native_create(guid)

        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            result = builder.build_patch(path)
            assert result is True

            tree = ET.parse(path)
            root = tree.getroot()

            native_objs = root.findall(".//CreateNativeObject")
            assert len(native_objs) == 1
            obj = native_objs[0]
            assert obj.get("Name") == "TestNative"
            assert obj.get("Path") == "/Folder"
            assert obj.get("TypeGuid") == NATIVE_TYPE_GUID
            native_xml_elem = obj.find("NativeXml")
            assert native_xml_elem is not None
            assert NATIVE_XML in native_xml_elem.text
        finally:
            os.remove(path)

    def test_pending_text_create_still_works(self):
        """A standard pending text create (pending_create=True,
        create_kind='pou') produces a CreateTextObject and is not
        affected by the native-recreate fix."""
        guid = "text-create-001"
        folder_node = _make_node(
            guid,
            name="MyPou",
            pending_create=True,
            create_kind="pou",
            create_path="/Folder",
            create_name="MyPou",
            create_type_guid="{6f9dac99-8de1-4efc-8465-68ac443b7d08}",
            create_declaration="PROGRAM MyPou\nVAR\n  x : INT;\nEND_VAR",
            create_implementation="x := 1;",
        )
        folder_model = model_with(folder_node)
        ide_model = model_with()
        diff_result = {
            "added": [guid],
            "modified": [],
            "deleted": [],
        }
        builder = PatchBuilder(diff_result, ide_model, folder_model)

        assert builder._is_pending_create(guid)
        assert not builder._is_native_create(guid)

        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            result = builder.build_patch(path)
            assert result is True

            tree = ET.parse(path)
            root = tree.getroot()

            # Should contain CreateTextObject(s), NOT CreateNativeObject
            text_objs = root.findall(".//CreateTextObject")
            assert len(text_objs) == 1
            native_objs = root.findall(".//CreateNativeObject")
            assert len(native_objs) == 0

            obj = text_objs[0]
            assert obj.get("Name") == "MyPou"
            assert obj.get("Path") == "/Folder"
            declaration = obj.find("Declaration")
            assert declaration is not None
            assert "PROGRAM MyPou" in (declaration.text or "")
        finally:
            os.remove(path)

    def test_manifest_listed_object_in_both_models_no_create(self):
        """A manifest-listed object that exists in BOTH the IDE model and
        the folder model does NOT produce a CreateNativeObject -- it
        should not be classified as a native recreate."""
        guid = "both-sides-001"
        folder_node = _make_node(
            guid,
            name="Existing",
            xml_text=NATIVE_XML,
            node_type=NATIVE_TYPE_GUID,
        )
        ide_node = _make_node(
            guid,
            name="Existing",
            xml_text=NATIVE_XML,
            node_type=NATIVE_TYPE_GUID,
        )
        folder_model = model_with(folder_node)
        ide_model = model_with(ide_node)
        diff_result = {
            "added": [],
            "modified": [],
            "deleted": [],
        }
        builder = PatchBuilder(diff_result, ide_model, folder_model)

        # _is_native_recreate must be False because the node IS in the IDE model
        assert not builder._is_native_recreate(guid)

        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            result = builder.build_patch(path)
            assert result is False  # no changes

            tree = ET.parse(path)
            root = tree.getroot()
            native_objs = root.findall(".//CreateNativeObject")
            assert len(native_objs) == 0, (
                "No CreateNativeObject should exist when the object is "
                "present in both models"
            )
        finally:
            os.remove(path)


# ===================================================================
# Text-first: st-authoritative overlay and st-only recreates
# ===================================================================


def _pou_xml(declaration, implementation):
    root = ET.Element("Single", {"Name": "Object"})
    decl_parent = ET.SubElement(root, "Single", {"Name": "Declaration"})
    decl = ET.SubElement(decl_parent, "Single", {"Name": "TextBlobForSerialisation"})
    decl.text = declaration
    impl_parent = ET.SubElement(root, "Single", {"Name": "Implementation"})
    impl = ET.SubElement(impl_parent, "Single", {"Name": "TextBlobForSerialisation"})
    impl.text = implementation
    return ET.tostring(root, encoding="unicode")


def _build_patch(builder):
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        emitted = builder.build_patch(path)
        with open(path, "r", encoding="utf-8") as handle:
            return emitted, handle.read()
    finally:
        os.remove(path)


class TestPatchBuilderTextFirst:
    def test_st_authoritative_overlays_ide_baseline_not_mirror_xml(self):
        """The patch must carry the .st text on the fresh IDE structure; the
        (possibly stale) rehydrated mirror xml must never win."""
        from xml_helpers import st_projection_content

        ide_xml = _pou_xml("PROGRAM P\nVAR\nEND_VAR", "x := 1;")
        disk_st = st_projection_content(ET.fromstring(ide_xml)).replace(
            "x := 1;", "x := 42;"
        )
        stale_mirror = _pou_xml("PROGRAM P_STALE\nVAR\nEND_VAR", "stale := 0;")

        ide_node = _make_node("g1", xml_text=ide_xml, structured_view_guid="sv-1")
        folder_node = _make_node(
            "g1",
            xml_text=stale_mirror,
            st_authoritative=True,
            projection_contents={"P.st": disk_st},
            structured_view_guid="sv-1",
        )
        builder = PatchBuilder(
            {"modified": ["g1"], "added": [], "deleted": []},
            model_with(ide_node),
            model_with(folder_node),
        )
        emitted, patch_text = _build_patch(builder)
        assert emitted is True
        assert "x := 42;" in patch_text
        assert "P_STALE" not in patch_text
        assert "stale := 0;" not in patch_text

    def test_st_only_added_entry_becomes_text_create(self):
        """A manifest entry with no xml baseline whose object is missing from
        the IDE is recreated from its .st text."""
        folder_node = _make_node(
            "g1",
            name="P",
            st_only=True,
            create_kind="pou",
            create_path="Folder/P.st",
            create_name="P",
            create_declaration="PROGRAM P\nVAR\nEND_VAR",
            create_implementation="x := 2;",
        )
        builder = PatchBuilder(
            {"modified": [], "added": ["g1"], "deleted": []},
            model_with(),
            model_with(folder_node),
        )
        assert builder._is_st_only_recreate("g1")
        emitted, patch_text = _build_patch(builder)
        assert emitted is True
        root = ET.fromstring(patch_text)
        creates = root.findall(".//CreateTextObject")
        assert len(creates) == 1
        assert creates[0].get("Kind") == "pou"
        assert creates[0].get("Name") == "P"
        assert "PROGRAM P" in creates[0].find("Declaration").text
        assert "x := 2;" in creates[0].find("Implementation").text
        assert root.findall(".//CreateNativeObject") == []

    def test_st_only_without_create_metadata_is_skipped_not_fatal(self):
        """An st-only added entry whose kind could not be detected must not
        crash the whole patch."""
        folder_node = _make_node("g1", name="P", st_only=True)
        builder = PatchBuilder(
            {"modified": [], "added": ["g1"], "deleted": []},
            model_with(),
            model_with(folder_node),
        )
        emitted, patch_text = _build_patch(builder)
        assert emitted is False
        assert "CreateTextObject" not in patch_text
