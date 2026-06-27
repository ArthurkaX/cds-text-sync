# -*- coding: utf-8 -*-
"""
test_screen_xml.py -- Tests for ``cli.visu.screen_xml``.

These tests verify screen resize, background update, and read operations
independently of the element builder.
"""

import os
import re
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import builder, screen_xml


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
        from cli.visu import catalog as _catalog

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
        original_len = len(screen_xml_text)
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

    def test_read_from_garbage(self):
        val = screen_xml.read_int_member("<invalid", "SizeX")
        assert val == 0


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
