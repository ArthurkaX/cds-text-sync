# -*- coding: utf-8 -*-
"""
test_folder_reader.py – Unit tests for folder_reader.py (Priority 4).

These tests use ``tmp_path`` for filesystem-heavy checks.
"""

import codecs
import json
import os

import pytest
from folder_reader import FolderReader, _detect_st_kind, _split_st_create_content
from xml_helpers import sha1_hex

# ===================================================================
# _split_st_create_content
# ===================================================================


class TestSplitStCreateContent:
    def test_declaration_only(self):
        decl, impl = _split_st_create_content("PROGRAM MyPrg\nEND_PROGRAM")
        assert "PROGRAM" in decl
        assert impl is None

    def test_declaration_plus_implementation_marker(self):
        content = "PROGRAM MyPrg\nVAR\nEND_VAR\n// --- implementation ---\nx := 1;"
        decl, impl = _split_st_create_content(content)
        assert "PROGRAM" in decl
        assert "x := 1;" in impl

    def test_crlf_and_lf_inputs_produce_equivalent_result(self):
        crlf = "PROGRAM P\r\nVAR\r\nEND_VAR\r\n// --- implementation ---\r\nx := 1;"
        lf = "PROGRAM P\nVAR\nEND_VAR\n// --- implementation ---\nx := 1;"
        assert _split_st_create_content(crlf) == _split_st_create_content(lf)


# ===================================================================
# _detect_st_kind
# ===================================================================


class TestDetectStKind:
    def test_program(self):
        assert _detect_st_kind("PROGRAM MyPrg\nEND_PROGRAM") == "pou"

    def test_function_block(self):
        assert _detect_st_kind("FUNCTION_BLOCK MyFb\nEND_FUNCTION_BLOCK") == "pou"

    def test_var_global(self):
        assert _detect_st_kind("VAR_GLOBAL\n  x : INT;\nEND_VAR") == "gvl"

    def test_type(self):
        assert _detect_st_kind("TYPE MyType :\nSTRUCT\nEND_STRUCT\nEND_TYPE") == "dut"

    def test_method(self):
        assert _detect_st_kind("METHOD MyMethod\nEND_METHOD") == "method"

    def test_type_guid_pragma_returns_none(self):
        content = '(* cds-text-sync: TypeGuid="{a1b2c3d4-e5f6-7890-abcd-ef1234567890}" *)\nPROGRAM P'
        assert _detect_st_kind(content) is None


# ===================================================================
# FolderReader – manifest-based loading
# ===================================================================


def _write_manifest(dump_path, manifest_data):
    """Write a manifest.json into the given dump directory."""
    with open(os.path.join(dump_path, "manifest.json"), "w") as f:
        json.dump(manifest_data, f, indent=2)


def _write_file(base_path, relative_path, content):
    """Write *content* (str) into *base_path/relative_path*, creating dirs."""
    full = os.path.join(base_path, relative_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with codecs.open(full, "w", "utf-8") as f:
        f.write(content)


class TestFolderReaderManifest:
    def _make_reader(self, tmp_path, manifest_data, views_subdir="views"):
        views = str(tmp_path / views_subdir)
        dump = str(tmp_path / ".dump")
        os.makedirs(views, exist_ok=True)
        os.makedirs(dump, exist_ok=True)
        manifest_data.setdefault("view_root", views)
        manifest_data.setdefault("ns", "")
        manifest_data.setdefault("entries", [])
        _write_manifest(dump, manifest_data)
        return FolderReader(views, dump), views, dump

    def test_missing_manifest_returns_none(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(views, exist_ok=True)
        os.makedirs(dump, exist_ok=True)
        reader = FolderReader(views, dump)
        assert reader.read() is None

    def test_manifest_with_xml_entry_loads_xml_text_and_metadata(self, tmp_path):
        xml_content = "<Root><Single Name='Data'>hello</Single></Root>"
        xml_path = "Folder/Obj.xml"
        reader, views, dump = self._make_reader(
            tmp_path,
            {
                "entries": [
                    {
                        "guid": "g1",
                        "name": "Obj",
                        "type_guid": "",
                        "parent_guid": None,
                        "xml_path": xml_path,
                        "hash": sha1_hex(xml_content),
                    }
                ],
            },
        )
        _write_file(views, xml_path, xml_content)
        model = reader.read()
        assert model is not None
        node = model.get_node("g1")
        assert node is not None
        assert node.xml_text is not None
        assert "hello" in node.xml_text
        assert node.metadata["original_hash"] == sha1_hex(xml_content)

    def test_manifest_with_view_path_entry_loads_code(self, tmp_path):
        code = "x := 42;"
        view_path = "Folder/Obj.st"
        reader, views, dump = self._make_reader(
            tmp_path,
            {
                "entries": [
                    {
                        "guid": "g1",
                        "name": "Obj",
                        "type_guid": "",
                        "parent_guid": None,
                        "view_path": view_path,
                    }
                ],
            },
        )
        _write_file(views, view_path, code)
        model = reader.read()
        node = model.get_node("g1")
        assert node is not None
        assert node.code == code

    def test_changed_xml_sets_xml_changed_metadata(self, tmp_path):
        xml_content = "<Root><Data>new</Data></Root>"
        old_hash = "deadbeef"
        reader, views, dump = self._make_reader(
            tmp_path,
            {
                "entries": [
                    {
                        "guid": "g1",
                        "name": "Obj",
                        "type_guid": "",
                        "parent_guid": None,
                        "xml_path": "Obj.xml",
                        "hash": old_hash,
                    }
                ],
            },
        )
        _write_file(views, "Obj.xml", xml_content)
        model = reader.read()
        node = model.get_node("g1")
        assert node.metadata.get("xml_changed") is True

    def test_view_root_mismatch_raises_runtime_error(self, tmp_path):
        views_a = str(tmp_path / "views_a")
        views_b = str(tmp_path / "views_b")
        dump = str(tmp_path / ".dump")
        os.makedirs(views_a, exist_ok=True)
        os.makedirs(dump, exist_ok=True)
        _write_manifest(
            dump,
            {
                "view_root": views_b,
                "ns": "",
                "entries": [],
            },
        )
        reader = FolderReader(views_a, dump)
        with pytest.raises(RuntimeError, match="view root"):
            reader.read()

    def test_path_traversal_ignored_by_safety_checks(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        reader = FolderReader(views, dump)
        assert reader._safe_path_in_root("../../etc/passwd", views) is None

    def test_projection_conflict_metadata(self, tmp_path):
        """When XML changed AND projection changed, projection_conflict is True."""
        xml_content = "<Root><Data>x</Data></Root>"
        old_hash = "deadbeef"
        proj_path = "Obj.st"
        proj_content = "PROGRAM P x := 1;"
        reader, views, dump = self._make_reader(
            tmp_path,
            {
                "entries": [
                    {
                        "guid": "g1",
                        "name": "Obj",
                        "type_guid": "",
                        "parent_guid": None,
                        "xml_path": "Obj.xml",
                        "hash": old_hash,
                        "projection_paths": [proj_path],
                        "projection_hashes": {proj_path: "not-the-hash"},
                    }
                ],
            },
        )
        _write_file(views, "Obj.xml", xml_content)
        _write_file(views, proj_path, proj_content)
        model = reader.read()
        node = model.get_node("g1")
        assert node.metadata.get("xml_changed") is True
        assert len(node.metadata.get("projection_changed_paths", [])) > 0
        assert node.metadata.get("projection_conflict") is True


# ===================================================================
# Pending ST create discovery
# ===================================================================


class TestFolderReaderExtractBoolProperty:
    def test_malformed_xml_returns_none(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        reader = FolderReader(views, dump)
        assert reader._extract_bool_property("\x00not xml", "SomeProp") is None

    def test_empty_string_returns_none(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        reader = FolderReader(views, dump)
        assert reader._extract_bool_property("", "SomeProp") is None


class TestFolderReaderRehydration:
    def test_malformed_xml_rehydration_returns_original_text(self, tmp_path):
        """When rehydration receives malformed XML, it returns it unchanged."""
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        reader = FolderReader(views, dump)
        bad_xml = "\x00not valid xml"
        result = reader._rehydrate_externalized_text(bad_xml, ["some.st"])
        assert result == bad_xml


class TestFolderReaderPendingStCreates:
    def _setup_reader(self, tmp_path, profile=None):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(views, exist_ok=True)
        os.makedirs(dump, exist_ok=True)
        _write_manifest(dump, {"view_root": views, "ns": "", "entries": []})
        return FolderReader(views, dump, profile=profile or {})

    def test_discovers_program(self, tmp_path):
        reader = self._setup_reader(tmp_path)
        _write_file(reader.views_path, "MyPrg.st", "PROGRAM MyPrg\nEND_PROGRAM")
        model = reader.read()
        found = [n for n in model.nodes.values() if n.metadata.get("pending_create")]
        assert len(found) >= 1
        assert found[0].metadata["create_kind"] == "pou"

    def test_discovers_function_block(self, tmp_path):
        reader = self._setup_reader(tmp_path)
        _write_file(
            reader.views_path, "MyFb.st", "FUNCTION_BLOCK MyFb\nEND_FUNCTION_BLOCK"
        )
        model = reader.read()
        found = [n for n in model.nodes.values() if n.metadata.get("pending_create")]
        assert len(found) >= 1
        assert found[0].metadata["create_kind"] == "pou"

    def test_discovers_var_global(self, tmp_path):
        reader = self._setup_reader(tmp_path)
        _write_file(reader.views_path, "MyGvl.st", "VAR_GLOBAL\n  x : INT;\nEND_VAR")
        model = reader.read()
        found = [n for n in model.nodes.values() if n.metadata.get("pending_create")]
        assert len(found) >= 1
        assert found[0].metadata["create_kind"] == "gvl"

    def test_discovers_type(self, tmp_path):
        reader = self._setup_reader(tmp_path)
        _write_file(
            reader.views_path, "MyDut.st", "TYPE MyDut :\nSTRUCT\nEND_STRUCT\nEND_TYPE"
        )
        model = reader.read()
        found = [n for n in model.nodes.values() if n.metadata.get("pending_create")]
        assert len(found) >= 1
        assert found[0].metadata["create_kind"] == "dut"

    def test_discovers_method_with_parent_method_naming(self, tmp_path):
        reader = self._setup_reader(tmp_path)
        _write_file(reader.views_path, "Parent.Method.st", "METHOD Method\nEND_METHOD")
        model = reader.read()
        found = [n for n in model.nodes.values() if n.metadata.get("pending_create")]
        assert len(found) >= 1
        assert found[0].metadata["create_kind"] == "method"
        assert found[0].metadata.get("create_parent_name") == "Parent"

    def test_discovers_file_with_type_guid_pragma(self, tmp_path):
        """A file with ``cds-text-sync: TypeGuid`` pragma whose GUID maps to a
        kind in the profile should be discovered."""
        profile = {
            "guid_aliases": {
                "pou": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
            },
        }
        reader = self._setup_reader(tmp_path, profile=profile)
        content = '(* cds-text-sync: TypeGuid="{a1b2c3d4-e5f6-7890-abcd-ef1234567890}" *)\njust code'
        _write_file(reader.views_path, "Ambiguous.st", content)
        model = reader.read()
        found = [n for n in model.nodes.values() if n.metadata.get("pending_create")]
        assert len(found) >= 1
        assert (
            found[0].metadata["create_type_guid"]
            == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )


# ===================================================================
# Pending XML create discovery
# ===================================================================


class TestFolderReaderPendingXmlCreates:
    """A .cds-object.xml file is always a container/object descriptor sidecar,
    never a standalone importable native object. The pending-XML-create
    discovery must skip it regardless of whether it is the dotfile form
    (.cds-object.xml) or the named form (ObjectName.cds-object.xml)."""

    def _setup_reader(self, tmp_path, profile=None):
        views = str(tmp_path / "views")
        dump = str(tmp_path / ".dump")
        os.makedirs(views, exist_ok=True)
        os.makedirs(dump, exist_ok=True)
        _write_manifest(dump, {"view_root": views, "ns": "", "entries": []})
        return FolderReader(views, dump, profile=profile or {})

    def test_skips_named_cds_object_xml_sidecar(self, tmp_path):
        """A named .cds-object.xml sidecar (ObjectName.cds-object.xml) must NOT
        be discovered as a pending native-XML create, while the genuine
        ObjectName.xml next to it IS discovered."""
        reader = self._setup_reader(tmp_path)

        # A valid standalone native object export.
        _write_file(
            reader.views_path,
            "HMI/Main_Screen.xml",
            '<Single Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}"'
            ' Method="IArchivable"><SomeChild/></Single>',
        )
        # Named descriptor sidecar -- MUST be skipped.
        _write_file(
            reader.views_path,
            "HMI/Main_Screen.cds-object.xml",
            '<Single Type="{00000000-0000-0000-0000-000000000000}">'
            "<Guid>{placeholder}</Guid></Single>",
        )

        model = reader.read()
        pending = [
            n for n in model.nodes.values() if n.metadata.get("pending_create")
        ]

        assert len(pending) == 1, (
            "Expected 1 pending create (Main_Screen.xml) but got {0}: {1}".format(
                len(pending),
                [(n.name, n.metadata.get("create_path")) for n in pending],
            )
        )
        assert pending[0].name == "Main_Screen"
        assert pending[0].metadata["create_path"] == "HMI/Main_Screen.xml"

    def test_skips_dotfile_cds_object_xml_sidecar(self, tmp_path):
        """A dotfile .cds-object.xml (.cds-object.xml) must also be skipped
        (regression guard for form 1)."""
        reader = self._setup_reader(tmp_path)

        _write_file(
            reader.views_path,
            "HMI/Main_Screen.xml",
            '<Single Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}"'
            ' Method="IArchivable"><SomeChild/></Single>',
        )
        _write_file(
            reader.views_path,
            "HMI/.cds-object.xml",
            '<Single Type="{00000000-0000-0000-0000-000000000000}">'
            "<Guid>{dot}</Guid></Single>",
        )

        model = reader.read()
        pending = [
            n for n in model.nodes.values() if n.metadata.get("pending_create")
        ]

        assert len(pending) == 1
        assert pending[0].name == "Main_Screen"

    def test_skips_all_cds_object_xml_variants(self, tmp_path):
        """With both named and dotfile .cds-object.xml present alongside a
        genuine .xml, only the genuine object is discovered."""
        reader = self._setup_reader(tmp_path)

        _write_file(
            reader.views_path,
            "HMI/Main_Screen.xml",
            '<Single Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}"'
            ' Method="IArchivable"><SomeChild/></Single>',
        )
        # Named sidecar
        _write_file(
            reader.views_path,
            "HMI/Main_Screen.cds-object.xml",
            '<Single Type="{00000000-0000-0000-0000-000000000000}">'
            "<Guid>{placeholder}</Guid></Single>",
        )
        # Dotfile sidecar
        _write_file(
            reader.views_path,
            "HMI/.cds-object.xml",
            '<Single Type="{00000000-0000-0000-0000-000000000000}">'
            "<Guid>{dot}</Guid></Single>",
        )

        model = reader.read()
        pending = [
            n for n in model.nodes.values() if n.metadata.get("pending_create")
        ]

        assert len(pending) == 1, (
            "Expected 1 pending create but got {0}: {1}".format(
                len(pending),
                [(n.name, n.metadata.get("create_path")) for n in pending],
            )
        )
        assert pending[0].name == "Main_Screen"
        assert pending[0].metadata["create_path"] == "HMI/Main_Screen.xml"

        # Double-check: no pending create has a .cds-object name or path.
        for node in pending:
            assert not node.name.endswith(".cds-object")
            create_path = node.metadata.get("create_path") or ""
            assert not create_path.endswith(".cds-object.xml")
