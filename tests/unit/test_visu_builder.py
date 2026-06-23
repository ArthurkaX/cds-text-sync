# -*- coding: utf-8 -*-
"""
test_visu_builder.py -- Offline self-tests for the visu builder and catalog.

These tests use ``tmp_path`` for filesystem-heavy checks. They DO NOT talk to
CODESYS or the daemon — they verify that generated XML is structurally correct
and that invariants are enforced.
"""

import os
import re
import sys

import pytest

# -- Path setup: add project root so we can import ``cli.visu`` --------------
_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import builder
from cli.visu import catalog as _catalog


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def rectangle_catalog():
    return _catalog.load_catalog("rectangle")


@pytest.fixture
def placement():
    """Synthetic placement values for builder tests."""
    return {
        "parent_guid": "aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        "parent_svnode_guid": "ddc05353-f826-4861-84cf-5fd88f7a319e",
        "path": ["Runtime", "PLC Logic", "Application", "HMI"],
    }


@pytest.fixture
def empty_screen(placement):
    """Build a clean (empty) screen XML string using the builder."""
    return builder.build_screen(
        name="TestScreen",
        size_x=800,
        size_y=480,
        parent_guid=placement["parent_guid"],
        parent_svnode_guid=placement["parent_svnode_guid"],
        path_segments=placement["path"],
        is_start_visu=False,
        visu_guid=None,
    )


# ===================================================================
# Catalog tests
# ===================================================================


class TestCatalog:
    def test_rectangle_catalog_loads(self, rectangle_catalog):
        assert rectangle_catalog["type"] == "rectangle"
        assert rectangle_catalog["visualElementTypeName"] == "VisuFbElemSimple"
        assert "base_members" in rectangle_catalog
        assert len(rectangle_catalog["base_members"]) > 20
        assert "params" in rectangle_catalog

    def test_list_types(self):
        types = _catalog.list_types()
        assert "rectangle" in types

    def test_shape_value(self, rectangle_catalog):
        assert _catalog.shape_value(rectangle_catalog, "rectangle") == "VISU_ST_RECTANGLE"
        assert _catalog.shape_value(rectangle_catalog, "ellipse") == "VISU_ST_CIRCLE"
        assert _catalog.shape_value(rectangle_catalog, "rounded") == "VISU_ST_ROUNDRECT"
        assert _catalog.shape_value(rectangle_catalog, "bogus") is None

    def test_unknown_type_raises(self):
        with pytest.raises(_catalog.CatalogError):
            _catalog.load_catalog("nonexistent_type")


# ===================================================================
# Screen envelope tests
# ===================================================================


class TestScreenEnvelope:
    def test_root_type(self, empty_screen):
        """Root element is a ``<Single Type="{6198ad31-...}">``."""
        assert 'Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}"' in empty_screen

    def test_regenerated_blocks_absent(self, empty_screen):
        """GeneratedLMMDescriptions, TextDocument, VisuSizeManager should be
        absent — CODESYS regenerates them on import."""
        assert "GeneratedLMMDescriptions" not in empty_screen
        assert "TextDocument" not in empty_screen
        assert "VisuSizeManager" not in empty_screen

    def test_placement_filled(self, empty_screen):
        """ParentGuid and ParentSVNodeGuid are present and non-empty."""
        assert '>aed6d2f4-6485-4017-982c-3b2fa7b0b4be<' in empty_screen
        assert '>ddc05353-f826-4861-84cf-5fd88f7a319e<' in empty_screen

    def test_path_present(self, empty_screen):
        """Path array contains the expected segments."""
        assert "Runtime" in empty_screen
        assert "PLC Logic" in empty_screen
        assert "Application" in empty_screen
        assert "HMI" in empty_screen

    def test_size(self, empty_screen):
        """SizeX and SizeY are set."""
        assert "800" in empty_screen
        assert "480" in empty_screen

    def test_name(self, empty_screen):
        """Screen name is set."""
        assert "TestScreen" in empty_screen

    def test_visual_elem_list_empty(self, empty_screen):
        """VisualElementList has no children (empty screen)."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(empty_screen)
        # Find VisualElementList.
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "List" and el.attrib.get("Name") == "VisualElementList":
                children = list(el)
                assert len(children) == 0
                break
        else:
            pytest.fail("VisualElementList not found")


# ===================================================================
# Element rendering tests
# ===================================================================


class TestElement:
    def _count_elements(self, xml_text):
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        # VisualElementList is under Object > VisualElemList > List.
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "List" and el.attrib.get("Name") == "VisualElementList":
                return len(list(el))
        return 0

    def _find_member(self, xml_text, member_id):
        """Find a member block's first-level sub-element by Name."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        for member in root.iter():
            tag = member.tag.split("}")[-1] if "}" in str(member.tag) else member.tag
            if tag != "Single":
                continue
            id_el = None
            for child in list(member):
                ct = child.tag.split("}")[-1] if "}" in str(child.tag) else child.tag
                if ct == "Single" and child.attrib.get("Name") == "Id":
                    id_el = child
                    break
            if id_el is not None and (id_el.text or "").strip() == str(member_id):
                val_el = None
                for child in list(member):
                    ct = child.tag.split("}")[-1] if "}" in str(child.tag) else child.tag
                    if ct == "Single" and child.attrib.get("Name") == "Value":
                        val_el = child
                        break
                if val_el is not None:
                    return val_el.text or ""
                return None
        return None

    def test_append_element(self, empty_screen, rectangle_catalog):
        """Adding a rectangle produces one element with correct geometry and
        auto-computed Center."""
        params = {"x": "50", "y": "30", "width": "200", "height": "100"}
        new_xml, geometry, info = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        # One element now.
        assert self._count_elements(new_xml) == 1
        # Geometry.
        assert geometry["x"] == 50
        assert geometry["y"] == 30
        assert geometry["width"] == 200
        assert geometry["height"] == 100
        # Center auto-computed.
        assert geometry["center_x"] == 150  # 50 + 200/2
        assert geometry["center_y"] == 80  # 30 + 100/2
        # Verify in the XML.
        assert self._find_member(new_xml, 1649127785) == "50"  # X
        assert self._find_member(new_xml, 357335551) == "30"  # Y
        assert self._find_member(new_xml, 2422045748) == "200"  # Width
        assert self._find_member(new_xml, 2134141914) == "100"  # Height
        assert self._find_member(new_xml, 550940142) == "150"  # CenterX
        assert self._find_member(new_xml, 1473355128) == "80"  # CenterY

    def test_append_element_default_center(self, empty_screen, rectangle_catalog):
        """Center auto-computes even when not explicitly set."""
        params = {"x": "10", "y": "20", "width": "100", "height": "100"}
        _, geometry, _ = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        assert geometry["center_x"] == 60  # 10 + 100/2
        assert geometry["center_y"] == 70  # 20 + 100/2

    def test_bounds_violation_rejected(self, empty_screen, rectangle_catalog):
        """X+Width exceeding SizeX raises BuilderError."""
        params = {"x": "700", "y": "0", "width": "200", "height": "100"}
        with pytest.raises(builder.BuilderError) as exc:
            builder.append_element(empty_screen, rectangle_catalog, params)
        assert "exceeds" in str(exc.value) or "SizeX" in str(exc.value)

    def test_bounds_height_violation(self, empty_screen, rectangle_catalog):
        """Y+Height exceeding SizeY raises BuilderError."""
        params = {"x": "0", "y": "400", "width": "100", "height": "200"}
        with pytest.raises(builder.BuilderError) as exc:
            builder.append_element(empty_screen, rectangle_catalog, params)
        assert "exceeds" in str(exc.value) or "SizeY" in str(exc.value)

    def test_negative_xy_fails(self, empty_screen, rectangle_catalog):
        """Negative X or Y raises BuilderError."""
        params = {"x": "-10", "y": "0", "width": "100", "height": "100"}
        with pytest.raises(builder.BuilderError):
            builder.append_element(empty_screen, rectangle_catalog, params)

    def test_shape_variant(self, empty_screen, rectangle_catalog):
        """Requesting a known shape variant sets the correct VISU_ST_* value."""
        params = {"x": "0", "y": "0", "width": "100", "height": "100", "shape": "ellipse"}
        new_xml, _, _ = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        shape_val = self._find_member(new_xml, 564465120)
        assert shape_val == "VISU_ST_CIRCLE"

    def test_unknown_shape_raises(self, empty_screen, rectangle_catalog):
        """Requesting an unknown shape raises BuilderError."""
        params = {"x": "0", "y": "0", "width": "100", "height": "100", "shape": "hexagon"}
        with pytest.raises(builder.BuilderError) as exc:
            builder.append_element(empty_screen, rectangle_catalog, params)
        assert "Unknown shape" in str(exc.value)

    def test_default_colors_preserved(self, empty_screen, rectangle_catalog):
        """Golden template preserves IDE-default colors (Step 1: colors deferred).
        All five color struct canonical names must be present verbatim from the
        template; fill param is accepted but does NOT override in Step 1."""
        params = {"x": "0", "y": "0", "width": "100", "height": "100", "fill": "0xFFFF0000"}
        new_xml, _, _ = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        for cn in (
            "BasicElement-Fill-Color",
            "BasicElement-Frame-Color",
            "BasicElement-Alarm-Frame-Color",
            "BasicElement-Alarm-Fill-Color",
            "Font-Default-Color",
        ):
            assert cn in new_xml

    def test_color_canonical_name_nonempty(self):
        """_render_color_member rejects empty canonical_name."""
        with pytest.raises(builder.BuilderError):
            builder._render_color_member(2812299069, "-1", "")

    def test_text_on_rectangle_raises(self, empty_screen, rectangle_catalog):
        """Non-empty text on a rectangle raises because Text ID is not yet supported."""
        params = {
            "x": "0",
            "y": "0",
            "width": "100",
            "height": "100",
            "text": "Hello",
        }
        with pytest.raises(builder.BuilderError) as exc:
            builder.append_element(empty_screen, rectangle_catalog, params)
        assert "Text ID" in str(exc.value)

    def test_invalid_color_raises(self):
        with pytest.raises(builder.BuilderError):
            builder.parse_color("not-a-color")

    def test_color_0x_format(self):
        """0xAARRGGBB hex is parsed correctly to signed int."""
        result = builder.parse_color("0xFFFF0000")
        assert result == "-65536"  # 0xFFFF0000 as signed 32-bit

    def test_color_hash_format(self):
        """#RRGGBB (no alpha) is parsed as opaque."""
        result = builder.parse_color("#FF0000")
        assert result == "-65536"  # 0xFFFF0000 as signed

    def test_color_plain_int(self):
        """A plain integer string passes through."""
        result = builder.parse_color("-1")
        assert result == "-1"

    def test_identifier_sequential(self, empty_screen, rectangle_catalog):
        """Elements get sequential GenElemInst_N identifiers and counters
        are bumped."""
        params1 = {"x": "0", "y": "0", "width": "100", "height": "100"}
        xml1, _, info1 = builder.append_element(
            empty_screen, rectangle_catalog, params1
        )
        assert info1["identifier"] == "GenElemInst_2"
        # Add second element.
        params2 = {"x": "200", "y": "0", "width": "50", "height": "50"}
        xml2, _, info2 = builder.append_element(
            xml1, rectangle_catalog, params2
        )
        assert info2["identifier"] == "GenElemInst_3"
        # Verify counters in XML.
        assert 'LastUsedIdForIdentifier" Type="int">3' in xml2
        assert 'UniqueIdGenerator" Type="string">' in xml2


# ===================================================================
# Color parsing
# ===================================================================


class TestColorParsing:
    def test_opaque_rrggbb(self):
        assert builder.parse_color("#336699") is not None

    def test_aarrggbb(self):
        assert builder.parse_color("0x80FF0000") is not None

    def test_none_returns_none(self):
        assert builder.parse_color(None) is None

    def test_empty_returns_none(self):
        assert builder.parse_color("") is None


# ===================================================================
# Bounds validation
# ===================================================================


class TestBoundsValidation:
    def test_valid_bounds(self):
        errors = builder.validate_bounds(
            {"x": 10, "y": 20, "width": 100, "height": 50}, size_x=800, size_y=480
        )
        assert errors == []

    def test_negative_x(self):
        errors = builder.validate_bounds(
            {"x": -1, "y": 0, "width": 100, "height": 100}, 800, 480
        )
        assert any("X" in e for e in errors)

    def test_negative_y(self):
        errors = builder.validate_bounds(
            {"x": 0, "y": -5, "width": 100, "height": 100}, 800, 480
        )
        assert any("Y" in e for e in errors)

    def test_exceeds_width(self):
        errors = builder.validate_bounds(
            {"x": 750, "y": 0, "width": 100, "height": 100}, 800, 480
        )
        assert any("Width" in e for e in errors)

    def test_exceeds_height(self):
        errors = builder.validate_bounds(
            {"x": 0, "y": 400, "width": 100, "height": 100}, 800, 480
        )
        assert any("Height" in e for e in errors)


# ===================================================================
# Sibling discovery tests (synthetic)
# ===================================================================


class TestSibling:
    def test_no_sibling_returns_none(self, tmp_path):
        """find_sibling_object on an empty dir returns None."""
        assert builder.find_sibling_object(str(tmp_path)) is None

    def test_non_visu_xml_skipped(self, tmp_path):
        """An XML file without ParentSVNodeGuid is skipped."""
        import xml.etree.ElementTree as ET

        root = ET.Element("Single", {"Type": "{abc}"})
        tree = ET.ElementTree(root)
        path = os.path.join(str(tmp_path), "other.xml")
        tree.write(path, encoding="utf-8", xml_declaration=True)
        assert builder.find_sibling_object(str(tmp_path)) is None

    def test_creates_screen_to_file(self, tmp_path, rectangle_catalog, placement):
        """End-to-end: create a screen file, then add a rectangle to it via the
        commands layer (simulated)."""
        # Build screen via builder directly (avoids sibling requirement).
        xml_text = builder.build_screen(
            name="E2ETest",
            size_x=800,
            size_y=480,
            parent_guid=placement["parent_guid"],
            parent_svnode_guid=placement["parent_svnode_guid"],
            path_segments=placement["path"],
            is_start_visu=True,
        )
        screen_path = os.path.join(str(tmp_path), "E2ETest.xml")
        with open(screen_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(xml_text)
        assert os.path.isfile(screen_path)

        # Add a rectangle.
        with open(screen_path, "r", encoding="utf-8") as f:
            orig = f.read()
        params = {"x": "10", "y": "20", "width": "300", "height": "150"}
        new_xml, geometry, info = builder.append_element(
            orig, rectangle_catalog, params
        )
        with open(screen_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_xml)

        # Verify contents.
        with open(screen_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'VisualElementIdentifier" Type="string">GenElemInst_2' in content
        assert "E2ETest" in content
        assert geometry["center_x"] == 160  # 10 + 300/2
        assert geometry["center_y"] == 95  # 20 + 150/2
        # IsStartVisu should be True.
        assert "IsStartVisu" in content
        assert "True" in content
        # Regenerated blocks absent.
        assert "GeneratedLMMDescriptions" not in content
        assert "TextDocument" not in content
        assert "VisuSizeManager" not in content


# ===================================================================
# Structural comparison against ground truth
# ===================================================================


class TestStructuralFidelity:
    """Verify that generated member order matches the ground-truth rectangle."""

    def test_member_count(self, empty_screen, rectangle_catalog):
        """A rectangle with defaults produces the same number of members as the
        catalog's base_members."""
        params = {"x": "0", "y": "0", "width": "100", "height": "100"}
        new_xml, _, _ = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        # Extract member count by counting the member block pattern.
        # Each member is: <Single Type="{c694e3a2...}" Method="IArchivable">
        member_count = new_xml.count(
            'Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable"'
        )
        expected = len(rectangle_catalog["base_members"])
        assert member_count == expected

    def test_member_ids_in_order(self, empty_screen, rectangle_catalog):
        """The first few member IDs match the catalog order."""
        import xml.etree.ElementTree as ET

        params = {"x": "0", "y": "0", "width": "100", "height": "100"}
        new_xml, _, _ = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        root = ET.fromstring(new_xml)
        # Find the member list.
        ids_in_order = []
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "List" and el.attrib.get("Name") == "VisualElemMemberList":
                for member in list(el):
                    for child in list(member):
                        ct = (
                            child.tag.split("}")[-1]
                            if "}" in str(child.tag)
                            else child.tag
                        )
                        if ct == "Single" and child.attrib.get("Name") == "Id":
                            ids_in_order.append(int((child.text or "0").strip()))
                            break
                break

        # Compare first 5 and last 5 against catalog.
        catalog_ids = [m["id"] for m in rectangle_catalog["base_members"]]
        assert ids_in_order[:5] == catalog_ids[:5]
        assert ids_in_order[-5:] == catalog_ids[-5:]
        assert len(ids_in_order) == len(catalog_ids)
