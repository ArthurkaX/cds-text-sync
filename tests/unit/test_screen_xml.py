# -*- coding: utf-8 -*-
"""
test_screen_xml.py -- Tests for ``cds_text_sync.visu.screen_xml``.

These tests verify screen resize, background update, and read operations
independently of the element builder.
"""

import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_text_sync.visu import builder, screen_xml, svg_export, xml_ns


@pytest.fixture
def placement():
    return {
        "parent_guid": "aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        "parent_svnode_guid": "ddc05353-f826-4861-84cf-5fd88f7a319e",
        "path": ["Runtime", "PLC Logic", "Application", "HMI"],
    }


@pytest.fixture
def screen_xml_text(placement):
    """Build a clean screen XML string using builder.build_screen."""
    return builder.build_screen(
        name="TestScreen",
        size_x=800,
        size_y=480,
        parent_guid=placement["parent_guid"],
        parent_svnode_guid=placement["parent_svnode_guid"],
        path_segments=placement["path"],
    )


# ===================================================================
# Read operations
# ===================================================================


class TestReadScreenSize:
    def test_returns_dimensions(self, screen_xml_text):
        sx, sy = screen_xml.read_screen_size(screen_xml_text)
        assert sx == 800
        assert sy == 480

    def test_after_resize(self, screen_xml_text):
        resized = screen_xml.resize_screen(screen_xml_text, 1024, 600)
        sx, sy = screen_xml.read_screen_size(resized)
        assert sx == 1024
        assert sy == 600

    def test_raises_on_missing(self):
        with pytest.raises(screen_xml.ScreenError):
            screen_xml.read_screen_size("<xml/>")

    def test_raises_on_garbage(self):
        with pytest.raises(screen_xml.ScreenError) as exc:
            screen_xml.read_screen_size("not-xml")
        assert "Could not parse" in str(exc.value)


class TestReadOwningGuid:
    def test_returns_guid(self, screen_xml_text):
        guid = screen_xml.read_owning_guid(screen_xml_text)
        # Should be either the real one from template or the fallback.
        assert isinstance(guid, str)
        assert len(guid) > 10

    def test_fallback_on_missing(self):
        guid = screen_xml.read_owning_guid("<Single/>")
        assert guid == "11111111-1111-1111-1111-111111111111"


class TestListElements:
    def test_empty_screen(self, screen_xml_text):
        assert screen_xml.list_elements(screen_xml_text) == []

    def test_after_append(self, screen_xml_text):
        from cds_text_sync.visu import catalog as _catalog

        cat = _catalog.load_catalog("rectangle")
        new_xml, geom, _ = builder.append_element(
            screen_xml_text, cat, {"x": "10", "y": "20", "width": "100", "height": "50"}
        )
        elems = screen_xml.list_elements(new_xml)
        assert len(elems) == 1
        assert elems[0]["x"] == "10"
        assert elems[0]["y"] == "20"
        assert elems[0]["width"] == "100"
        assert elems[0]["height"] == "50"


# ===================================================================
# Write / mutate operations
# ===================================================================


class TestResizeScreen:
    def test_resize_larger(self, screen_xml_text):
        resized = screen_xml.resize_screen(screen_xml_text, 1024, 600)
        sx, sy = screen_xml.read_screen_size(resized)
        assert sx == 1024
        assert sy == 600

    def test_resize_smaller(self, screen_xml_text):
        resized = screen_xml.resize_screen(screen_xml_text, 320, 240)
        sx, sy = screen_xml.read_screen_size(resized)
        assert sx == 320
        assert sy == 240

    def test_resize_to_same(self, screen_xml_text):
        same = screen_xml.resize_screen(screen_xml_text, 800, 480)
        assert same is screen_xml_text or same == screen_xml_text

    def test_resize_preserves_rest(self, screen_xml_text):
        """Resize should not affect unrelated structure."""
        resized = screen_xml.resize_screen(screen_xml_text, 1024, 600)
        # The file should still have all structural markers.
        assert resized.count("</Single>") == screen_xml_text.count("</Single>")
        assert resized.count("<List") == screen_xml_text.count("<List")
        assert "TestScreen" in resized


class TestSetScreenBackground:
    def test_bg_enabled(self, screen_xml_text):
        bg = screen_xml.set_screen_background(screen_xml_text, "#1e1e1e")
        assert 'BgColor" Type="bool">True' in bg

    def test_bg_color_updated(self, screen_xml_text):
        bg = screen_xml.set_screen_background(screen_xml_text, "#1e1e1e")
        # 0x1e1e1e with 0xFF alpha = 0xFF1E1E1E -> signed = -14803426
        assert 'BgUseColor" Type="int">-14803426' in bg

    def test_bg_0x_prefix(self, screen_xml_text):
        bg = screen_xml.set_screen_background(screen_xml_text, "0xFF1E1E1E")
        assert 'BgUseColor" Type="int">-14803426' in bg

    def test_bg_none_no_change(self, screen_xml_text):
        unchanged = screen_xml.set_screen_background(screen_xml_text, None)
        assert unchanged is screen_xml_text

    def test_bg_empty_no_change(self, screen_xml_text):
        unchanged = screen_xml.set_screen_background(screen_xml_text, "")
        assert unchanged is screen_xml_text

    def test_bg_preserves_rest(self, screen_xml_text):
        bg = screen_xml.set_screen_background(screen_xml_text, "#336699")
        assert "TestScreen" in bg
        assert 'size_x="800"' in bg or "SizeX" in bg


class TestReadIntMember:
    def test_read_existing(self, screen_xml_text):
        val = screen_xml.read_int_member(screen_xml_text, "SizeX")
        assert val == 800

    def test_read_missing(self, screen_xml_text):
        val = screen_xml.read_int_member(screen_xml_text, "NonExistent")
        assert val == 0

    def test_read_from_garbage_raises_instead_of_reporting_zero(self):
        """0 here is a counter base, not a default: it would collide."""
        with pytest.raises(screen_xml.ScreenError):
            screen_xml.read_int_member("<invalid", "SizeX")


# ===================================================================
# Integration: from_svg replacement verification
# ===================================================================


class TestFromSvgCompatibility:
    """Verify that screen_xml operations produce the same results as the
    original regex-based code in commands.from_svg."""

    def test_resize_matches_original_regex(self, screen_xml_text):
        """The resize result should be structurally valid."""
        resized = screen_xml.resize_screen(screen_xml_text, 1280, 720)
        sx, sy = screen_xml.read_screen_size(resized)
        assert sx == 1280
        assert sy == 720
        # Valid XML after resize.
        import xml.etree.ElementTree as ET

        ET.fromstring(resized)

    def test_background_matches_original_logic(self, screen_xml_text):
        """The signed int computation should match the old from_svg logic."""
        bg = screen_xml.set_screen_background(screen_xml_text, "#FF336699")
        # 0xFF336699 as signed int = -13408615
        assert 'BgUseColor" Type="int">-13408615' in bg


# ===================================================================
# Shared VisualElemMemberList traversal (visu.xml_ns)
# ===================================================================


def _member_list_element():
    """An element with one well-formed, one colour, one flat-list member and
    two entries the traversal must skip (not a <Single>, and no <Id>)."""
    import xml.etree.ElementTree as ET

    element = ET.Element("Single", {"Name": "Elem"})
    container = ET.SubElement(element, "Single", {"Name": "VisualElemMemberList"})
    mlist = ET.SubElement(container, "List", {"Name": "VisualElemMemberList"})

    scalar = ET.SubElement(mlist, "Single")
    ET.SubElement(scalar, "Single", {"Name": "Id"}).text = "1"
    ET.SubElement(scalar, "Single", {"Name": "Value"}).text = "hello"

    ET.SubElement(mlist, "List")  # wrong tag: skipped

    ET.SubElement(mlist, "Single")  # no Id: skipped

    colour = ET.SubElement(mlist, "Single")
    ET.SubElement(colour, "Single", {"Name": "Id"}).text = "3"
    value = ET.SubElement(colour, "List", {"Name": "Value"})
    inner = ET.SubElement(value, "Single")
    ET.SubElement(inner, "Single", {"Name": "Color"}).text = "-1"
    ET.SubElement(inner, "Single", {"Name": "CanonicalName"}).text = (
        "Font-Default-Color"
    )

    slots = ET.SubElement(mlist, "Single")
    ET.SubElement(slots, "Single", {"Name": "Id"}).text = "4"
    slot_list = ET.SubElement(slots, "List", {"Name": "Value"})
    ET.SubElement(slot_list, "Single").text = "10"
    ET.SubElement(slot_list, "Single").text = "20"
    return element


class TestMemberListTraversal:
    def test_find_member_list_returns_the_list(self):
        mlist = xml_ns.find_member_list(_member_list_element())
        assert mlist is not None
        assert mlist.tag == "List"

    def test_find_member_list_none_when_absent(self):
        import xml.etree.ElementTree as ET

        assert xml_ns.find_member_list(ET.Element("Single")) is None

    def test_iter_member_list_skips_unusable_entries(self):
        pairs = list(xml_ns.iter_member_list(_member_list_element()))
        assert [id_text for id_text, _ in pairs] == ["1", "3", "4"]

    def test_iter_member_list_empty_without_a_list(self):
        import xml.etree.ElementTree as ET

        assert list(xml_ns.iter_member_list(ET.Element("Single"))) == []

    def test_member_map_reads_scalar_and_colour_members(self):
        mapped = xml_ns.member_map(_member_list_element())
        assert mapped[1] == {"kind": "scalar", "value": "hello"}
        assert mapped[3]["kind"] == "color"
        assert mapped[3]["color"] == "-1"
        assert mapped[3]["canonical_name"] == "Font-Default-Color"
        assert mapped[4] == {"kind": "list", "value": None}

    def test_member_map_empty_without_a_list(self):
        import xml.etree.ElementTree as ET

        assert xml_ns.member_map(ET.Element("Single")) == {}


class TestMemberReadersKeepTheirContracts:
    """``screen_xml._member_map`` and the two svg_export readers now share the
    traversal, but keep their own answers when the list is missing."""

    def test_screen_xml_member_map_returns_empty_dict(self):
        import xml.etree.ElementTree as ET

        assert screen_xml._member_map(ET.Element("Single")) == {}

    def test_svg_export_member_value_returns_none(self):
        import xml.etree.ElementTree as ET

        element = _member_list_element()
        assert svg_export._member_value(element, 1) == "hello"
        assert svg_export._member_value(element, 3)["color"] == "-1"
        assert svg_export._member_value(element, 99) is None
        assert svg_export._member_value(ET.Element("Single"), 1) is None

    def test_svg_export_member_list_values_returns_none(self):
        import xml.etree.ElementTree as ET

        element = _member_list_element()
        assert svg_export._member_list_values(element, 4) == ["10", "20"]
        assert svg_export._member_list_values(element, 1) is None
        assert svg_export._member_list_values(ET.Element("Single"), 4) is None
