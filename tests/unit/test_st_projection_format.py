# -*- coding: utf-8 -*-
"""The projected ``.st`` text format: one contract, five call sites.

A single CODESYS object projects into one ``.st`` file.  Two boundaries can
appear in it:

* ``// --- implementation ---`` between a declaration and its body;
* ``// === SECTION ===`` between two sections of an object that has no
  declaration (the GET/SET accessors of a property).

Five places parse that text -- ``variable_map.split_decl_impl``,
``call_tree._split_decl_impl``, ``folder_reader._split_st_create_content``,
``ide_st_text.split_st_text`` and ``xml_helpers`` -- and they were written
independently.  This module pins what each of them does today, including where
they differ, so the constants and the split/join rules can move into one
module without silently changing any caller.
"""

import os
import sys
import xml.etree.ElementTree as ET

import pytest


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENGINE = os.path.join(_ROOT, "products", "cds-text-sync", "src", "cds_text_sync", "engine")
_BRIDGE = os.path.join(_ROOT, "products", "codesys-host", "src", "ide_bridge")

if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

from xml_helpers import (  # noqa: E402
    TEXT_PROJECTION_SEPARATOR,
    join_text_blob_values,
    split_st_projection_values,
    split_text_projection,
    st_projection_content,
)
from xml_helpers import split_action_projection  # noqa: E402
import variable_map  # noqa: E402
import call_tree  # noqa: E402
import folder_reader  # noqa: E402
import ide_st_text  # noqa: E402


MARKER = "// --- implementation ---"
SECTION = "// === SECTION ==="


# ---------------------------------------------------------------------------
# The constants themselves
# ---------------------------------------------------------------------------


def test_every_site_spells_the_markers_the_same_way():
    assert variable_map.ST_IMPLEMENTATION_MARKER == MARKER
    assert call_tree.ST_IMPLEMENTATION_MARKER == MARKER
    assert ide_st_text.ST_IMPLEMENTATION_MARKER == MARKER
    assert ide_st_text.ST_SECTION_MARKER == SECTION
    assert TEXT_PROJECTION_SEPARATOR == "\n\n" + SECTION + "\n\n"


# ---------------------------------------------------------------------------
# The marker split: the three engine splitters are interchangeable
# ---------------------------------------------------------------------------

MARKED_INPUTS = {
    "plain": "DECL\n" + MARKER + "\nBODY",
    "crlf": "DECL\r\n" + MARKER + "\r\nBODY",
    "marker_at_start": MARKER + "\nBODY",
    "marker_at_end": "DECL\n" + MARKER,
    "two_markers": "DECL\n" + MARKER + "\nA\n" + MARKER + "\nB",
    "marker_inside_a_string": "x := '" + MARKER + "';\n" + MARKER + "\ny := 1;",
}


@pytest.mark.parametrize("text", MARKED_INPUTS.values(), ids=MARKED_INPUTS.keys())
def test_engine_splitters_agree_on_marked_text(text):
    # The declaration keeps its surrounding whitespace here; only the daemon
    # side (ide_st_text, checked below) strips.
    assert variable_map.split_decl_impl(text) == call_tree._split_decl_impl(text)
    assert folder_reader._split_st_create_content(text) == tuple(
        part.strip() for part in variable_map.split_decl_impl(text)
    )


def test_a_marker_inside_a_string_literal_is_still_a_marker():
    # Characterisation, not endorsement: all sites split on the raw substring.
    decl, impl = variable_map.split_decl_impl(MARKED_INPUTS["marker_inside_a_string"])
    assert decl == "x := '" + MARKER + "';"
    assert impl == "y := 1;"


def test_only_the_first_marker_splits():
    decl, impl = variable_map.split_decl_impl(MARKED_INPUTS["two_markers"])
    assert decl == "DECL"
    assert impl == "A\n" + MARKER + "\nB"


def test_call_tree_also_accepts_the_codesys_implementation_keyword():
    text = "PROGRAM P\nVAR\nEND_VAR\nIMPLEMENTATION\nx := 1;"
    assert call_tree._split_decl_impl(text) == (
        "PROGRAM P\nVAR\nEND_VAR",
        "x := 1;",
    )
    # ... and the other engine splitters do not, which is why this split is
    # not shared with them yet.
    assert variable_map.split_decl_impl(text) == (text, None)


def test_marker_less_text_stays_a_declaration():
    # A marker-less file is a GVL/DUT/empty-body POU: the whole text is the
    # declaration.  The implementation is None (engine) or "" (daemon).
    assert variable_map.split_decl_impl("VAR_GLOBAL x : INT; END_VAR") == (
        "VAR_GLOBAL x : INT; END_VAR",
        None,
    )
    assert call_tree._split_decl_impl("VAR_GLOBAL x : INT; END_VAR") == (
        "VAR_GLOBAL x : INT; END_VAR",
        None,
    )
    assert folder_reader._split_st_create_content("VAR_GLOBAL x : INT; END_VAR") == (
        "VAR_GLOBAL x : INT; END_VAR",
        None,
    )


# ---------------------------------------------------------------------------
# The daemon-side splitter (ide_st_text)
# ---------------------------------------------------------------------------


WELL_FORMED = {
    key: text
    for key, text in MARKED_INPUTS.items()
    if key != "marker_inside_a_string"
}


@pytest.mark.parametrize("text", WELL_FORMED.values(), ids=WELL_FORMED.keys())
def test_daemon_splitter_strips_both_halves(text):
    declaration, implementation = ide_st_text.split_st_text(text)
    expected = variable_map.split_decl_impl(text)
    assert declaration == expected[0].strip()
    assert implementation == (expected[1] or "").strip()


def test_the_marker_only_counts_on_its_own_line():
    """The daemon used to split on the bare substring, the engine on the line.

    They disagreed when the marker text appeared inline -- inside a string
    literal or a comment -- and the daemon split early.  Both go through the
    line-first ladder now, so the inline occurrence no longer splits.
    """
    text = MARKED_INPUTS["marker_inside_a_string"]
    assert variable_map.split_decl_impl(text)[0] == "x := '" + MARKER + "';"
    assert ide_st_text.split_st_text(text)[0] == "x := '" + MARKER + "';"


def test_daemon_splitter_understands_the_section_separator():
    # Accessor files carry no declaration: the section marker splits them and
    # the declaration half is empty.
    assert ide_st_text.split_st_text("\n\n" + SECTION + "\n\nProp := 42;\n") == (
        "",
        "Prop := 42;",
    )
    assert ide_st_text.split_st_text("Prop := 42;\n\n" + SECTION + "\n\n") == (
        "Prop := 42;",
        "",
    )


def test_engine_create_path_does_not_understand_the_section_separator():
    # Characterisation: the create path predates the accessor projector and
    # treats such a file as one declaration with no body.
    text = "\n\n" + SECTION + "\n\nProp := 42;\n"
    assert folder_reader._split_st_create_content(text) == (text.strip(), None)


def test_daemon_splitter_drops_the_pou_end_keyword_only_when_asked():
    text = (
        "FUNCTION_BLOCK FB\nVAR\nEND_VAR\n" + MARKER + "\nx := 1;\nEND_FUNCTION_BLOCK"
    )
    assert ide_st_text.split_st_text(text)[1] == "x := 1;\nEND_FUNCTION_BLOCK"
    assert ide_st_text.split_st_text(text, strip_pou_end=True)[1] == "x := 1;"


# ---------------------------------------------------------------------------
# ACTION headers
# ---------------------------------------------------------------------------


def test_action_header_is_stripped_on_the_way_back():
    text = "ACTION Act\n" + MARKER + "\n\nx := 1;\nEND_ACTION\n"
    assert ide_st_text.split_st_text(text)[1] == "x := 1;"
    assert split_action_projection(text) == "x := 1;\n"


def test_action_splitter_returns_none_for_a_plain_declaration():
    assert split_action_projection("VAR_GLOBAL x : INT; END_VAR") is None
    assert split_action_projection("") is None


# ---------------------------------------------------------------------------
# Section join/split (xml_helpers)
# ---------------------------------------------------------------------------


def test_sections_are_joined_with_the_separator():
    assert join_text_blob_values(["a", "b"]) == "a\n\n" + SECTION + "\n\nb"
    assert join_text_blob_values(["only"]) == "only"
    assert join_text_blob_values([]) is None


def test_sections_split_pads_and_merges_to_the_expected_count():
    assert split_text_projection("a\n\n" + SECTION + "\n\nb", 2) == ["a", "b"]
    assert split_text_projection("a", 3) == ["a", "", ""]
    merged = split_text_projection(
        TEXT_PROJECTION_SEPARATOR.join(["a", "b", "c"]), 2
    )
    assert merged[0] == "a"
    assert merged[1] == "b" + TEXT_PROJECTION_SEPARATOR + "c"


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


def _section(name, text):
    node = ET.Element("Single", {"Name": name})
    document = ET.SubElement(node, "Single", {"Name": "TextDocument"})
    blob = ET.SubElement(document, "Single", {"Name": "TextBlobForSerialisation"})
    blob.text = text
    return node


def _entry(*sections):
    root = ET.Element("Single", {"Name": "Object"})
    for name, text in sections:
        root.append(_section(name, text))
    return root


def _accessor(implementation):
    node = ET.Element("Single", {"Name": "Object"})
    for name in ("Get", "Set"):
        accessor = ET.SubElement(node, "Single", {"Name": name})
        document = ET.SubElement(accessor, "Single", {"Name": "TextDocument"})
        blob = ET.SubElement(
            document, "Single", {"Name": "TextBlobForSerialisation"}
        )
        blob.text = implementation
    return node


@pytest.mark.parametrize(
    "entry,declaration,implementation",
    [
        (
            _entry(
                ("Interface", "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR"),
                ("Implementation", "x := 1;"),
            ),
            "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR\n",
            "x := 1;\n",
        ),
        (
            _entry(
                ("Interface", "METHOD m : BOOL"),
                ("Implementation", "m := TRUE;"),
            ),
            "METHOD m : BOOL\n",
            "m := TRUE;\n",
        ),
    ],
    ids=["pou", "method"],
)
def test_marked_projection_round_trips(entry, declaration, implementation):
    projected = st_projection_content(entry)
    assert projected == declaration + "\n" + MARKER + "\n\n" + implementation
    assert split_st_projection_values(projected, entry) == [
        declaration,
        implementation,
    ]


def test_property_accessors_project_declaration_first_and_round_trip():
    entry = _entry(("Interface", ""), ("Implementation", "Prop := fValue;"))
    projected = st_projection_content(entry)
    assert projected == "\n\n" + SECTION + "\n\nProp := fValue;\n"
    assert split_st_projection_values(projected, entry) == ["", "Prop := fValue;\n"]


def test_get_and_set_accessors_keep_their_sections_in_order():
    entry = _accessor("Prop := fValue;")
    projected = st_projection_content(entry)
    assert projected == "Prop := fValue;\n\n" + SECTION + "\n\nProp := fValue;"
    assert split_st_projection_values(projected, entry) == [
        "Prop := fValue;",
        "Prop := fValue;",
    ]


def test_accessor_st_file_splits_like_the_daemon_reads_it():
    # What the projector writes for a declaration-less accessor, the daemon
    # must read back: the declaration half is empty, the body keeps the rest.
    text = st_projection_content(_entry(("Interface", ""), ("Implementation", "Prop := 42;\n")))
    assert text == "\n\n" + SECTION + "\n\nProp := 42;\n"
    assert ide_st_text.split_st_text(text) == ("", "Prop := 42;")


def test_hand_written_accessor_st_matches_the_projected_form():
    hand_written = "\n\n" + SECTION + "\n\nProp := fValue;\n"
    projected = st_projection_content(
        _entry(("Interface", ""), ("Implementation", "Prop := fValue;\n"))
    )
    assert hand_written == projected
    assert ide_st_text.split_st_text(hand_written) == ("", "Prop := fValue;")


# ---------------------------------------------------------------------------
# Known divergence: bare CR
# ---------------------------------------------------------------------------


def test_bare_cr_is_normalised_everywhere():
    """``xml_helpers`` used to replace CRLF only; every other site replaced
    bare CR too.  It shares ``normalize_newlines`` now, so a bare-CR file is
    read the same way on both sides.  (CODESYS does not emit bare CR, so the
    old behaviour was never exercised in the wild.)
    """
    from xml_helpers import _split_marked_projection

    text = "DECL\r" + MARKER + "\rBODY"
    assert variable_map.split_decl_impl(text) == ("DECL", "BODY")
    assert _split_marked_projection(text) == ("DECL\n", "BODY\n")
