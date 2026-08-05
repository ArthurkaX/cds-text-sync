# -*- coding: utf-8 -*-
"""
test_action_round_trip.py — ACTION projections must survive a full round trip.

CODESYS ACTIONs (and other declaration-less POU children) expose an
implementation section only. Exporting them as a bare body made the .st file
non-self-describing: the reader could not tell the kind, and the import path
could not tell the body apart from a GVL/DUT declaration, so edits never
reached the IDE.

The header is synthesised on the way out and stripped on the way back. Both
directions are covered here, together with the declaration-only kinds that
share the same code path and must NOT be treated as implementations.
"""

import os
import sys
import xml.etree.ElementTree as ET

import pytest

from xml_helpers import (
    ST_IMPLEMENTATION_MARKER,
    split_action_projection,
    split_st_projection_values,
    st_projection_content,
    text_blob_values,
)

import folder_reader


_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

from ide_st_text import split_st_text  # noqa: E402


# ---------------------------------------------------------------------------
# Entry builders — mirror the EntryList shape produced by the snapshot reader
# ---------------------------------------------------------------------------


def _add_text_section(parent, section_name, text):
    section = ET.SubElement(parent, "Single", {"Name": section_name})
    document = ET.SubElement(section, "Single", {"Name": "TextDocument"})
    blob = ET.SubElement(
        document, "Single", {"Name": "TextBlobForSerialisation"}
    )
    blob.text = text
    return blob


def _make_entry(name, declaration=None, implementation=None):
    entry = ET.Element("Single")
    if name is not None:
        meta = ET.SubElement(entry, "Single", {"Name": "MetaObject"})
        name_element = ET.SubElement(meta, "Single", {"Name": "Name"})
        name_element.text = name
    obj = ET.SubElement(entry, "Single", {"Name": "Object"})
    if implementation is not None:
        _add_text_section(obj, "Implementation", implementation)
    if declaration is not None:
        _add_text_section(obj, "Interface", declaration)
    return entry


ACTION_BODY = "IF bReset THEN\n    nCount := 0;\nEND_IF"
GVL_DECLARATION = "VAR_GLOBAL\n    bReset : BOOL;\nEND_VAR"
DUT_DECLARATION = "TYPE Point :\nSTRUCT\n    x : INT;\nEND_STRUCT\nEND_TYPE"


# ---------------------------------------------------------------------------
# Forward: export
# ---------------------------------------------------------------------------


def test_action_projection_carries_header_and_marker():
    entry = _make_entry("Reset", implementation=ACTION_BODY)
    content = st_projection_content(entry)
    assert content.startswith("ACTION Reset\n")
    assert ST_IMPLEMENTATION_MARKER in content
    assert ACTION_BODY in content


def test_action_projection_without_metaobject_name_stays_bare():
    """No name to synthesise from -> previous behaviour, never a broken header."""
    entry = _make_entry(None, implementation=ACTION_BODY)
    assert st_projection_content(entry) == ACTION_BODY


def test_declaration_only_projection_is_untouched():
    """GVL/DUT must not gain an ACTION header — they have no implementation."""
    for declaration in (GVL_DECLARATION, DUT_DECLARATION):
        entry = _make_entry("Thing", declaration=declaration)
        content = st_projection_content(entry)
        assert content == declaration
        assert "ACTION" not in content
        assert ST_IMPLEMENTATION_MARKER not in content


# ---------------------------------------------------------------------------
# Reverse: the direction the projection change would otherwise corrupt
# ---------------------------------------------------------------------------


def test_action_round_trip_restores_the_bare_body():
    entry = _make_entry("Reset", implementation=ACTION_BODY)
    projected = st_projection_content(entry)
    values = split_st_projection_values(projected, entry)
    assert len(values) == 1
    # The stored blob must never receive the header or the marker.
    assert "ACTION" not in values[0]
    assert ST_IMPLEMENTATION_MARKER not in values[0]
    assert values[0].strip() == ACTION_BODY


def test_declaration_only_round_trip_keeps_the_declaration():
    entry = _make_entry("Globals", declaration=GVL_DECLARATION)
    projected = st_projection_content(entry)
    values = split_st_projection_values(projected, entry)
    assert len(values) == 1
    assert values[0].strip() == GVL_DECLARATION.strip()


def test_full_pou_round_trip_is_unchanged():
    declaration = "PROGRAM Main\nVAR\n    x : INT;\nEND_VAR"
    entry = _make_entry("Main", declaration=declaration, implementation="x := 1;")
    projected = st_projection_content(entry)
    values = split_st_projection_values(projected, entry)
    assert len(values) == 2
    assert [value.strip() for value in values] == ["x := 1;", declaration]
    # Blob order in the entry is implementation-then-interface; the split must
    # follow the entry, not the projection.
    assert text_blob_values(entry) == ["x := 1;", declaration]


@pytest.mark.parametrize(
    "content",
    [
        "ACTION Reset\n\n" + ST_IMPLEMENTATION_MARKER + "\n\n" + ACTION_BODY + "\n",
        "ACTION Reset\n" + ACTION_BODY + "\n",
        "ACTION Reset\n" + ACTION_BODY + "\nEND_ACTION\n",
        "\n\nACTION Reset\n\n" + ACTION_BODY + "\n\n",
    ],
)
def test_split_action_projection_accepts_hand_written_variants(content):
    assert split_action_projection(content).strip() == ACTION_BODY


def test_split_action_projection_ignores_non_action_text():
    assert split_action_projection(GVL_DECLARATION) is None
    assert split_action_projection("PROGRAM Main\nVAR\nEND_VAR") is None
    assert split_action_projection("") is None


# ---------------------------------------------------------------------------
# Daemon-side splitter — one implementation shared by update/create/update-pou
# ---------------------------------------------------------------------------


def test_split_st_text_routes_action_body_to_implementation():
    content = "ACTION Reset\n\n" + ST_IMPLEMENTATION_MARKER + "\n\n" + ACTION_BODY
    declaration, implementation = split_st_text(content)
    assert declaration == ""
    assert implementation.strip() == ACTION_BODY


@pytest.mark.parametrize("declaration", [GVL_DECLARATION, DUT_DECLARATION])
def test_split_st_text_keeps_marker_less_content_as_declaration(declaration):
    """The regression that would silently no-op every GVL and DUT import."""
    assert split_st_text(declaration) == (declaration, "")


def test_split_st_text_splits_on_the_marker():
    content = "PROGRAM Main\nVAR\nEND_VAR\n\n" + ST_IMPLEMENTATION_MARKER + "\n\nx := 1;"
    declaration, implementation = split_st_text(content)
    assert declaration == "PROGRAM Main\nVAR\nEND_VAR"
    assert implementation == "x := 1;"


def test_split_st_text_strips_pou_end_only_when_asked():
    content = (
        "FUNCTION_BLOCK FB\nVAR\nEND_VAR\n\n"
        + ST_IMPLEMENTATION_MARKER
        + "\n\nx := 1;\nEND_FUNCTION_BLOCK"
    )
    assert split_st_text(content)[1].endswith("END_FUNCTION_BLOCK")
    assert split_st_text(content, strip_pou_end=True)[1] == "x := 1;"


def test_split_st_text_on_empty_content():
    assert split_st_text("") == ("", "")
    assert split_st_text("   \n\n") == ("", "")


# ---------------------------------------------------------------------------
# Creation path
# ---------------------------------------------------------------------------


def test_create_split_puts_action_body_in_implementation():
    content = "ACTION Reset\n\n" + ST_IMPLEMENTATION_MARKER + "\n\n" + ACTION_BODY
    declaration, implementation = folder_reader._split_st_create_content(content)
    assert declaration == ""
    assert implementation.strip() == ACTION_BODY


def test_create_split_keeps_gvl_as_declaration():
    declaration, implementation = folder_reader._split_st_create_content(
        GVL_DECLARATION
    )
    assert declaration == GVL_DECLARATION
    assert implementation is None
