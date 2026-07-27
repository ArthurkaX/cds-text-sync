# -*- coding: utf-8 -*-
"""
test_xml_helpers.py – Unit tests for xml_helpers.py (Priority 1: pure helpers).

These tests do not touch the filesystem.
"""

import xml.etree.ElementTree as ET

import pytest
from xml_helpers import (
    IMPORT_SAFE_CSV_EXTRACTORS,
    ST_IMPLEMENTATION_MARKER,
    ProjectionValidationError,
    extract_bool_property,
    extract_cds_text_sync_type_guid,
    get_namespace,
    join_text_blob_values,
    normalize_guid,
    normalized_xml_text,
    sha1_hex,
    split_st_projection_values,
    split_text_projection,
    st_projection_content,
    strip_cds_text_sync_pragmas,
)

# ===================================================================
# normalize_guid
# ===================================================================


class TestNormalizeGuid:
    def test_strips_braces(self):
        assert normalize_guid("{ABC123}") == "abc123"

    def test_trims_whitespace(self):
        assert normalize_guid("  abc  ") == "abc"

    def test_lowercases(self):
        assert normalize_guid("A1B2C3D4-E5F6-7890-ABCD-EF1234567890") == (
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )

    def test_none_returns_empty_string(self):
        assert normalize_guid(None) == ""

    def test_braces_and_whitespace_together(self):
        assert normalize_guid("  {ABC}  ") == "abc"


# ===================================================================
# sha1_hex
# ===================================================================


class TestSha1Hex:
    def test_str_and_utf8_bytes_produce_same_digest(self):
        text = "hello world"
        assert sha1_hex(text) == sha1_hex(text.encode("utf-8"))

    def test_none_returns_none(self):
        assert sha1_hex(None) is None

    def test_deterministic(self):
        assert sha1_hex("test") == sha1_hex("test")


# ===================================================================
# get_namespace
# ===================================================================


class TestGetNamespace:
    def test_returns_namespace_prefix_for_namespaced_tag(self, namespaced_tag):
        assert get_namespace(namespaced_tag) == "{http://example.com/ns}"

    def test_returns_empty_string_for_plain_tag(self, plain_tag):
        assert get_namespace(plain_tag) == ""

    def test_empty_string_tag(self):
        assert get_namespace("") == ""


# ===================================================================
# extract_cds_text_sync_type_guid
# ===================================================================


class TestExtractCdsTextSyncTypeGuid:
    def test_accepts_braced_guid(self):
        content = (
            '(* cds-text-sync: TypeGuid="{a1b2c3d4-e5f6-7890-abcd-ef1234567890}" *)'
        )
        result = extract_cds_text_sync_type_guid(content)
        assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_accepts_guid_without_braces(self):
        content = '(* cds-text-sync: TypeGuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890" *)'
        result = extract_cds_text_sync_type_guid(content)
        assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_ignores_unrelated_comments(self):
        content = "(* some other comment *)"
        assert extract_cds_text_sync_type_guid(content) is None

    def test_none_content(self):
        assert extract_cds_text_sync_type_guid(None) is None


# ===================================================================
# strip_cds_text_sync_pragmas
# ===================================================================


class TestStripCdsTextSyncPragmas:
    def test_removes_cds_text_sync_block_pragma(self):
        content = 'before (* cds-text-sync: TypeGuid="{abc}" *) after'
        result = strip_cds_text_sync_pragmas(content)
        assert "cds-text-sync" not in result
        assert "before" in result
        assert "after" in result

    def test_preserves_normal_user_comments(self):
        content = "(* normal user comment *)"
        result = strip_cds_text_sync_pragmas(content)
        assert result == content

    def test_none_content(self):
        result = strip_cds_text_sync_pragmas(None)
        assert result == ""


# ===================================================================
# split_text_projection
# ===================================================================


class TestSplitTextProjection:
    def test_pads_missing_sections(self):
        result = split_text_projection("aaa", 3)
        assert len(result) == 3
        assert result[0] == "aaa"
        assert result[1] == ""
        assert result[2] == ""

    def test_merges_extra_sections_into_final(self):
        from xml_helpers import TEXT_PROJECTION_SEPARATOR

        content = TEXT_PROJECTION_SEPARATOR.join(["a", "b", "c"])
        result = split_text_projection(content, 2)
        assert len(result) == 2
        assert result[0] == "a"
        assert TEXT_PROJECTION_SEPARATOR in result[1]

    def test_exact_count(self):
        from xml_helpers import TEXT_PROJECTION_SEPARATOR

        content = TEXT_PROJECTION_SEPARATOR.join(["a", "b"])
        result = split_text_projection(content, 2)
        assert result == ["a", "b"]


# ===================================================================
# normalized_xml_text
# ===================================================================


class TestNormalizedXmlText:
    def test_ignores_volatile_elements_like_timestamp(self):
        xml_a = "<Root><Single Name='Timestamp'>2024-01-01</Single><Single Name='Data'>x</Single></Root>"
        xml_b = "<Root><Single Name='Timestamp'>2025-12-31</Single><Single Name='Data'>x</Single></Root>"
        assert normalized_xml_text(xml_a) == normalized_xml_text(xml_b)

    def test_sorts_dictionary_entries_deterministically(self):
        xml_a = (
            "<Root><Dictionary><Entry Name='b'/><Entry Name='a'/></Dictionary></Root>"
        )
        xml_b = (
            "<Root><Dictionary><Entry Name='a'/><Entry Name='b'/></Dictionary></Root>"
        )
        assert normalized_xml_text(xml_a) == normalized_xml_text(xml_b)

    def test_preserves_invalid_xml_by_returning_original_text(self):
        invalid = "<not valid xml <<"
        assert normalized_xml_text(invalid) == invalid


# ===================================================================
# ST projection helpers
# ===================================================================


class TestJoinTextBlobValues:
    def test_returns_none_for_no_values(self):
        assert join_text_blob_values([]) is None
        assert join_text_blob_values(None) is None

    def test_single_value(self):
        assert join_text_blob_values(["hello"]) == "hello"


class TestStProjectionContent:
    def _make_entry(self, declaration, implementation):
        """Build a minimal entry element with proper Declaration/Implementation
        naming so that ``_text_blob_sections`` can assign roles correctly."""
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
        return root

    def _make_action_entry(self, name, implementation):
        """Build a minimal ACTION entry element.

        ACTIONs in CODESYS have **no declaration** — only an Implementation
        section — plus a MetaObject/Name carrying the action's name. This
        mirrors the real ``<父>.<动作>.xml`` shape captured by ``cts export``.
        """
        root = ET.Element("Single", {"Name": "Object"})
        meta = ET.SubElement(root, "Single", {"Name": "MetaObject"})
        name_elem = ET.SubElement(meta, "Single", {"Name": "Name"})
        name_elem.text = name
        impl_parent = ET.SubElement(root, "Single", {"Name": "Implementation"})
        impl = ET.SubElement(
            impl_parent, "Single", {"Name": "TextBlobForSerialisation"}
        )
        impl.text = implementation
        return root

    def test_produces_declaration_and_implementation_with_marker(self):
        entry = self._make_entry(
            "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR",
            "x := 1;",
        )
        result = st_projection_content(entry)
        assert result is not None
        assert ST_IMPLEMENTATION_MARKER in result
        assert "PROGRAM MyPrg" in result
        assert "x := 1;" in result

    def test_none_for_empty_entry(self):
        assert st_projection_content(None) is None

    def test_action_emits_keyword_marker_and_implementation(self):
        """An ACTION (declaration-less) must project to a complete two-section
        .st: ``ACTION <name>`` + marker + implementation. Currently it projects
        to a bare implementation body, which ``cts import`` then refuses to
        apply (regression: editing an exported ACTION never reaches the IDE)."""
        entry = self._make_action_entry("TestAct2", "testVal := 1;")
        result = st_projection_content(entry)
        assert result is not None
        assert "ACTION TestAct2" in result
        assert ST_IMPLEMENTATION_MARKER in result
        assert "testVal := 1;" in result


class TestSplitStProjectionValues:
    def _make_entry(self, declaration, implementation):
        """Build a minimal entry element with proper Declaration/Implementation
        naming so that ``_text_blob_sections`` can assign roles correctly."""
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
        return root

    def test_splits_marked_projection_back_into_declaration_and_implementation(self):
        entry = self._make_entry(
            "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR",
            "x := 1;",
        )
        projected = st_projection_content(entry)
        result = split_st_projection_values(projected, entry)
        assert len(result) == 2
        assert "PROGRAM MyPrg" in result[0]
        assert "x := 1;" in result[1]

    def test_single_blob_returns_single_value(self):
        root = ET.Element("Single", {"Name": "Object"})
        blob = ET.SubElement(root, "Single", {"Name": "TextBlobForSerialisation"})
        blob.text = "just code"
        result = split_st_projection_values("just code", root)
        assert len(result) == 1
        assert result[0] == "just code"


# ===================================================================
# Negative tests
# ===================================================================


class TestExtractBoolPropertyMalformedXml:
    def test_malformed_xml_returns_none(self):
        """Malformed XML in extract_bool_property should return None."""
        from xml_helpers import extract_bool_property as _ebp

        assert _ebp(None, "SomeProp") is None

    def test_malformed_xml_string_returns_none(self):
        """Passing non-XML text should not raise."""
        result = extract_bool_property(ET.Element("Root"), "Nonexistent")
        assert result is None


class TestProjectionValidationErrorDuplicateTextId:
    def test_duplicate_textid_raises_projection_validation_error(self):
        from xml_helpers import apply_textlist_csv

        csv_content = "TextID,TextDefault\nid1,val1\nid1,val2\n"
        root = ET.Element("Single", {"Name": "Object"})
        text_list = ET.SubElement(root, "List", {"Name": "TextList"})
        item = ET.SubElement(text_list, "Single")
        ET.SubElement(item, "Single", {"Name": "TextID"}).text = "id1"
        ET.SubElement(item, "Single", {"Name": "TextDefault"}).text = "val1"

        with pytest.raises(ProjectionValidationError, match="Duplicate TextID"):
            apply_textlist_csv(root, csv_content)


class TestProjectionValidationErrorDuplicateAlarmId:
    def test_duplicate_alarmid_raises_projection_validation_error(self):
        from xml_helpers import apply_alarm_items_csv

        csv_content = "AlarmID,Expression\nid1,expr1\nid1,expr2\n"
        root = ET.Element("Single", {"Name": "Object"})
        alarms_dict = ET.SubElement(root, "Dictionary", {"Name": "Alarms"})
        entry = ET.SubElement(alarms_dict, "Entry")
        value = ET.SubElement(entry, "Value")
        alarm = ET.SubElement(value, "Single")
        ET.SubElement(alarm, "Single", {"Name": "ID"}).text = "id1"

        with pytest.raises(ProjectionValidationError, match="Duplicate AlarmID"):
            apply_alarm_items_csv(root, csv_content)


class TestCsvStructuralEditsRaiseError:
    def test_textlist_inserted_textid_raises_error(self):
        """Adding a new TextID row to a TextList CSV is a structural edit that
        raises ProjectionValidationError."""
        from xml_helpers import apply_textlist_csv

        csv_content = "TextID,TextDefault\nid1,val1\nnew_id,new_val\n"
        root = ET.Element("Single", {"Name": "Object"})
        text_list = ET.SubElement(root, "List", {"Name": "TextList"})
        item = ET.SubElement(text_list, "Single")
        ET.SubElement(item, "Single", {"Name": "TextID"}).text = "id1"
        ET.SubElement(item, "Single", {"Name": "TextDefault"}).text = "val1"

        with pytest.raises(ProjectionValidationError, match="inserted TextID"):
            apply_textlist_csv(root, csv_content)

    def test_textlist_removed_textid_raises_error(self):
        """Removing a TextID row from a TextList CSV is a structural edit that
        raises ProjectionValidationError."""
        from xml_helpers import apply_textlist_csv

        csv_content = "TextID,TextDefault\n"  # empty — all IDs removed
        root = ET.Element("Single", {"Name": "Object"})
        text_list = ET.SubElement(root, "List", {"Name": "TextList"})
        item = ET.SubElement(text_list, "Single")
        ET.SubElement(item, "Single", {"Name": "TextID"}).text = "id1"
        ET.SubElement(item, "Single", {"Name": "TextDefault"}).text = "val1"

        with pytest.raises(ProjectionValidationError, match="removed TextID"):
            apply_textlist_csv(root, csv_content)
