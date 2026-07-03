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
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import builder
from cli.visu import catalog as _catalog
from cli.visu import svg_import
from cli.visu import themes

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def rectangle_catalog():
    return _catalog.load_catalog("rectangle")


@pytest.fixture
def button_catalog():
    return _catalog.load_catalog("button")


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
        assert "line" in types
        assert "label" in types
        assert "button" in types
        assert "textfield" in types

    def test_shape_value(self, rectangle_catalog):
        assert (
            _catalog.shape_value(rectangle_catalog, "rectangle") == "VISU_ST_RECTANGLE"
        )
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
        assert ">aed6d2f4-6485-4017-982c-3b2fa7b0b4be<" in empty_screen
        assert ">ddc05353-f826-4861-84cf-5fd88f7a319e<" in empty_screen

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
                    ct = (
                        child.tag.split("}")[-1] if "}" in str(child.tag) else child.tag
                    )
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
        _, geometry, _ = builder.append_element(empty_screen, rectangle_catalog, params)
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
        params = {
            "x": "0",
            "y": "0",
            "width": "100",
            "height": "100",
            "shape": "ellipse",
        }
        new_xml, _, _ = builder.append_element(empty_screen, rectangle_catalog, params)
        shape_val = self._find_member(new_xml, 564465120)
        assert shape_val == "VISU_ST_CIRCLE"

    def test_unknown_shape_raises(self, empty_screen, rectangle_catalog):
        """Requesting an unknown shape raises BuilderError."""
        params = {
            "x": "0",
            "y": "0",
            "width": "100",
            "height": "100",
            "shape": "hexagon",
        }
        with pytest.raises(builder.BuilderError) as exc:
            builder.append_element(empty_screen, rectangle_catalog, params)
        assert "Unknown shape" in str(exc.value)

    def test_default_colors_uint_form(self, empty_screen, rectangle_catalog):
        """Primitives now emit fill/frame as uint literals (not struct).
        Alarm colors and font color keep their struct defaults.
        Fill param is resolved to uint form."""
        params = {
            "x": "0",
            "y": "0",
            "width": "100",
            "height": "100",
            "fill": "0xFFFF0000",
        }
        new_xml, _, _ = builder.append_element(empty_screen, rectangle_catalog, params)
        # Fill and frame are uint form -> no struct CanonicalName.
        # We check by scanning the member region for fill member 2812299069.
        fill_idx = new_xml.find('"Id" Type="long">2812299069')
        # After this, the next <Single Name="Value"> should be Type="uint"
        after_fill = new_xml[fill_idx : fill_idx + 200]
        assert 'Type="uint"' in after_fill, "Fill should be uint form"
        assert "BasicElement-Fill-Color" not in after_fill, (
            "Fill should NOT have struct CanonicalName"
        )
        # Alarm and font colors still use struct form.
        for cn in (
            "BasicElement-Alarm-Frame-Color",
            "BasicElement-Alarm-Fill-Color",
            "Font-Default-Color",
        ):
            assert cn in new_xml

    def test_custom_primitive_uses_custom_theme_roles(
        self, empty_screen, rectangle_catalog
    ):
        colors = themes.load_theme("flat-style")
        params = {"x": "0", "y": "0", "width": "100", "height": "100"}
        new_xml, _, _ = builder.append_element(
            empty_screen, rectangle_catalog, params, theme_colors=colors
        )
        assert self._find_member(new_xml, 2812299069) == themes.resolve_color_unsigned(
            "var(--custom-fill)", colors
        )
        assert self._find_member(new_xml, 494569607) == themes.resolve_color_unsigned(
            "var(--custom-frame)", colors
        )

    def test_native_button_without_explicit_colors_keeps_style_defaults(
        self, empty_screen, button_catalog
    ):
        colors = themes.load_theme("flat-style")
        params = {"x": "10", "y": "20", "width": "120", "height": "40"}
        new_xml, _, _ = builder.append_element(
            empty_screen, button_catalog, params, theme_colors=colors
        )
        assert "@@FILL_COLOR_UINT@@" not in new_xml
        assert "@@FRAME_COLOR_UINT@@" not in new_xml
        assert themes.resolve_color_unsigned("var(--custom-fill)", colors) not in new_xml

    def test_color_canonical_name_nonempty(self):
        """_render_color_member rejects empty canonical_name."""
        with pytest.raises(builder.BuilderError):
            builder._render_color_member(2812299069, "-1", "")

    def test_text_on_rectangle_supported(self, empty_screen, rectangle_catalog):
        """Text on a rectangle is now supported (Text-ID still needed for import).
        The builder accepts text params and passes them through to the template;
        Text-ID allocation is handled by textlist.py at the command layer."""
        params = {
            "x": "0",
            "y": "0",
            "width": "100",
            "height": "100",
            "text": "Hello",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, rectangle_catalog, params
        )
        assert geometry["x"] == 0
        assert geometry["y"] == 0
        assert geometry["width"] == 100
        assert geometry["height"] == 100

    def test_button_tap_variable_supported(self, empty_screen, button_catalog):
        params = {
            "x": "10",
            "y": "20",
            "width": "120",
            "height": "40",
            "tap_var": "HMI.PanelStart",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, button_catalog, params
        )
        assert geometry["x"] == 10
        assert "Visu_TapInput" in new_xml
        assert self._find_member(new_xml, 1186196937) == "HMI.PanelStart"
        assert self._find_member(new_xml, 1647042231) == "HMI.PanelStart"
        assert self._find_member(new_xml, 1999528970) == "HMI.PanelStart"

    def test_button_toggle_variable_supported(self, empty_screen, button_catalog):
        params = {
            "x": "10",
            "y": "20",
            "width": "120",
            "height": "40",
            "toggle_var": "HMI.PanelStart",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, button_catalog, params
        )
        assert geometry["x"] == 10
        assert "Visu_ToggleInput" in new_xml
        assert self._find_member(new_xml, 1186196937) == "HMI.PanelStart"
        assert self._find_member(new_xml, 2164770859) == "False"

    def test_button_input_actions_supported(self, empty_screen, button_catalog):
        params = {
            "x": "10",
            "y": "20",
            "width": "120",
            "height": "40",
            "input_actions": [
                {
                    "event": "OnMouseClick",
                    "type": "st_snippet",
                    "values": {"snippet": "HMI.PanelStart := TRUE;"},
                },
                {
                    "event": "OnMouseDown",
                    "type": "toggle_variable",
                    "values": {"variable": "HMI.PanelStart"},
                },
                {
                    "event": "OnMouseUp",
                    "type": "change_screen",
                    "values": {"screen": "CoolingTower"},
                },
            ],
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, button_catalog, params
        )
        assert "OnMouseClick" in new_xml
        assert "OnMouseDown" in new_xml
        assert "OnMouseUp" in new_xml
        assert "STSnippet" in new_xml
        assert "HMI.PanelStart := TRUE;" in new_xml
        assert "ToggleVariable" in new_xml
        assert "Assign33" in new_xml
        assert "CoolingTower" in new_xml

    def test_svg_button_action_parser(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120" viewBox="0 0 200 120">
          <defs><style>:root{ --primary:#2277cc; }</style></defs>
          <rect x="10" y="20" width="120" height="40" data-cds-type="button"
                data-text="Action"
                data-cds-action="TOGGLE HMI.PanelStart || OnMouseClick: ST HMI.PanelStart := TRUE;"/>
        </svg>"""
        parsed = svg_import.parse_svg(svg)
        button = parsed["elements"][0]
        assert button["type"] == "button"
        assert button["params"]["configured_inputs"][0]["type"] == "toggle"
        assert button["params"]["configured_inputs"][0]["values"]["variable"] == "HMI.PanelStart"
        assert button["params"]["input_actions"][0]["event"] == "OnMouseClick"
        assert button["params"]["input_actions"][0]["type"] == "st_snippet"

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
        xml2, _, info2 = builder.append_element(xml1, rectangle_catalog, params2)
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


class TestCodesysStyleThemes:
    def test_flat_style_loads_codesys_roles(self):
        colors = themes.load_theme("flat-style")
        assert colors["surface"] == "#FFFFE1"
        assert colors["primary"] == "#505050"

    def test_full_codesys_style_display_name_loads(self):
        colors = themes.load_theme(
            "Style 7, Gradient double linear 1, 3.5.12.0 "
            "(3S-Smart Software Solutions GmbH)"
        )
        assert colors["primary"] == "#5F5FA8"

    def test_legacy_dark_alias_maps_to_codesys_style(self):
        colors = themes.load_theme("dark")
        assert colors == themes.load_theme("flat-style")

    def test_screenshot_json_has_priority_over_builtin_fallback(self):
        colors = themes.load_theme("style-6")
        assert colors["primary"] == "#43A7D9"

    def test_layout_and_custom_roles_are_derived(self):
        colors = themes.load_theme("basic-style")
        assert colors["screen.background"] == "#FFFFE1"
        assert colors["custom.fill"] == colors["panel"]
        assert colors["custom.frame"] == colors["frame"]
        assert colors["divider"] == colors["border"]


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
        new_xml, _, _ = builder.append_element(empty_screen, rectangle_catalog, params)
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
        new_xml, _, _ = builder.append_element(empty_screen, rectangle_catalog, params)
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


@pytest.fixture
def lamp_catalog():
    return _catalog.load_catalog("lamp")


class TestLamp:
    """Reference indicator-lamp element (golden-template + template_params)."""

    def _find_member(self, xml_text, member_id):
        return TestElement._find_member(self, xml_text, member_id)

    def test_catalog_loads(self, lamp_catalog):
        assert lamp_catalog["type"] == "lamp"
        assert lamp_catalog["visualElementTypeName"] == "VisuFbElemLamp"
        assert "template_params" in lamp_catalog

    def test_append_lamp(self, empty_screen, lamp_catalog):
        params = {
            "x": "66",
            "y": "55",
            "width": "32",
            "height": "32",
            "style_role": "Element-Lamp-Lamp1-Red",
            "var": "HMI.PumpFault",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, lamp_catalog, params
        )
        assert geometry["x"] == 66
        assert geometry["y"] == 55
        assert "VisuFbElemLamp" in new_xml
        # template_params substitution landed on the right members.
        assert self._find_member(new_xml, 4062784938) == "Element-Lamp-Lamp1-Red"
        assert self._find_member(new_xml, 743958181) == "HMI.PumpFault"
        assert "@@" not in new_xml

    def test_template_param_default_used_when_missing(self, empty_screen, lamp_catalog):
        # No style_role/var supplied -> catalog defaults fill in.
        params = {"x": "0", "y": "0", "width": "32", "height": "32"}
        new_xml, _, _ = builder.append_element(empty_screen, lamp_catalog, params)
        assert self._find_member(new_xml, 4062784938) == "Element-Lamp-Lamp1-Green"
        assert self._find_member(new_xml, 743958181) == ""

    def test_svg_parse_lamp(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="lamp" data-color="red" data-var="HMI.Fault" '
            'x="66" y="55" width="32" height="32"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        lamp = parsed["elements"][0]
        assert lamp["type"] == "lamp"
        assert lamp["params"]["style_role"] == "Element-Lamp-Lamp1-Red"
        assert lamp["params"]["var"] == "HMI.Fault"

    def test_svg_parse_lamp_default_color(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="lamp" x="0" y="0" width="32" height="32"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        assert parsed["elements"][0]["params"]["style_role"] == (
            "Element-Lamp-Lamp1-Green"
        )

    def test_export_round_trip(self, empty_screen, lamp_catalog):
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        params = {
            "x": "66",
            "y": "55",
            "width": "32",
            "height": "32",
            "style_role": "Element-Lamp-Lamp1-Yellow",
            "var": "HMI.Ready",
        }
        new_xml, _, _ = builder.append_element(empty_screen, lamp_catalog, params)
        # Pull the appended lamp element node back out and decompile it.
        root = ET.fromstring(new_xml)
        lamp_node = None
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "Single":
                for child in list(el):
                    ct = (
                        child.tag.split("}")[-1]
                        if "}" in str(child.tag)
                        else child.tag
                    )
                    if (
                        ct == "Single"
                        and child.attrib.get("Name") == "VisualElementTypeName"
                        and (child.text or "") == "VisuFbElemLamp"
                    ):
                        lamp_node = el
                        break
            if lamp_node is not None:
                break
        assert lamp_node is not None
        out = svg_export._element_to_svg(lamp_node)
        assert 'data-cds-type="lamp"' in out
        assert 'data-color="yellow"' in out
        assert "HMI.Ready" in out


class TestLampGvl:
    def test_lamp_var_collected(self):
        from cli.visu import gvl

        elems = [{"type": "lamp", "params": {"var": "HMI.PumpFault"}}]
        assert gvl.collect_variables(elems) == {"HMI.PumpFault": "PumpFault"}

    def test_lamp_var_typed_bool(self):
        from cli.visu import gvl

        elems = [{"type": "lamp", "params": {"var": "HMI.PumpFault"}}]
        assert gvl.collect_variable_types(elems) == {"HMI.PumpFault": "BOOL"}


@pytest.fixture
def image_switcher_catalog():
    return _catalog.load_catalog("image-switcher")


class TestImageSwitcher:
    """Two-state image toggle element (golden-template + template_params)."""

    def _find_member(self, xml_text, member_id):
        return TestElement._find_member(self, xml_text, member_id)

    def test_catalog_loads(self, image_switcher_catalog):
        assert image_switcher_catalog["type"] == "image-switcher"
        assert image_switcher_catalog["visualElementTypeName"] == "VisuFbImageSwitcher"
        assert "template_params" in image_switcher_catalog

    def test_append_image_switcher(self, empty_screen, image_switcher_catalog):
        params = {
            "x": "66",
            "y": "55",
            "width": "70",
            "height": "70",
            "image_on": "ICONS.pump_run",
            "image_off": "ICONS.pump_stop",
            "var": "HMI.PumpRunning",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, image_switcher_catalog, params
        )
        assert geometry["x"] == 66
        assert geometry["y"] == 55
        assert "VisuFbImageSwitcher" in new_xml
        # template_params substitution landed on the right members.
        assert self._find_member(new_xml, 427565733) == "ICONS.pump_run"
        assert self._find_member(new_xml, 296037572) == "ICONS.pump_stop"
        assert self._find_member(new_xml, 743958181) == "HMI.PumpRunning"
        assert "@@" not in new_xml

    def test_template_param_default_used_when_missing(self, empty_screen, image_switcher_catalog):
        # No image_on/image_off/var supplied -> catalog defaults fill in.
        params = {"x": "0", "y": "0", "width": "70", "height": "70"}
        new_xml, _, _ = builder.append_element(empty_screen, image_switcher_catalog, params)
        assert self._find_member(new_xml, 427565733) == ""
        assert self._find_member(new_xml, 296037572) == ""
        assert self._find_member(new_xml, 743958181) == ""

    def test_svg_parse_image_switcher(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="image-switcher" data-image-on="ICONS.pump_run" '
            'data-image-off="ICONS.pump_stop" data-var="HMI.PumpRunning" '
            'x="66" y="55" width="70" height="70"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        elem = parsed["elements"][0]
        assert elem["type"] == "image-switcher"
        assert elem["params"]["image_on"] == "ICONS.pump_run"
        assert elem["params"]["image_off"] == "ICONS.pump_stop"
        assert elem["params"]["var"] == "HMI.PumpRunning"

    def test_svg_parse_image_switcher_defaults(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="image-switcher" x="0" y="0" width="70" height="70"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        elem = parsed["elements"][0]
        assert elem["params"]["image_on"] == ""
        assert elem["params"]["image_off"] == ""
        assert elem["params"]["var"] == ""

    def test_export_round_trip(self, empty_screen, image_switcher_catalog):
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        params = {
            "x": "66",
            "y": "55",
            "width": "70",
            "height": "70",
            "image_on": "ICONS.pump_run",
            "image_off": "ICONS.pump_stop",
            "var": "HMI.PumpRunning",
        }
        new_xml, _, _ = builder.append_element(empty_screen, image_switcher_catalog, params)
        # Pull the appended image-switcher element node back out and decompile it.
        root = ET.fromstring(new_xml)
        is_node = None
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "Single":
                for child in list(el):
                    ct = (
                        child.tag.split("}")[-1]
                        if "}" in str(child.tag)
                        else child.tag
                    )
                    if (
                        ct == "Single"
                        and child.attrib.get("Name") == "VisualElementTypeName"
                        and (child.text or "") == "VisuFbImageSwitcher"
                    ):
                        is_node = el
                        break
                if is_node is not None:
                    break
        assert is_node is not None
        out = svg_export._element_to_svg(is_node)
        assert 'data-cds-type="image-switcher"' in out
        assert 'data-image-on="ICONS.pump_run"' in out
        assert 'data-image-off="ICONS.pump_stop"' in out
        assert 'data-var="HMI.PumpRunning"' in out


class TestImageSwitcherGvl:
    def test_image_switcher_var_collected(self):
        from cli.visu import gvl

        elems = [{"type": "image-switcher", "params": {"var": "HMI.PumpRunning"}}]
        assert gvl.collect_variables(elems) == {"HMI.PumpRunning": "PumpRunning"}

    def test_image_switcher_var_typed_bool(self):
        from cli.visu import gvl

        elems = [{"type": "image-switcher", "params": {"var": "HMI.PumpRunning"}}]
        assert gvl.collect_variable_types(elems) == {"HMI.PumpRunning": "BOOL"}



@pytest.fixture
def combobox_catalog():
    return _catalog.load_catalog("combobox")


class TestComboBox:
    """Combobox dropdown element (golden-template + template_params)."""

    def _find_member(self, xml_text, member_id):
        return TestElement._find_member(self, xml_text, member_id)

    def test_catalog_loads(self, combobox_catalog):
        assert combobox_catalog["type"] == "combobox"
        assert combobox_catalog["visualElementTypeName"] == "VisuFbComboBoxInteger"
        assert "template_params" in combobox_catalog

    def test_append_combobox(self, empty_screen, combobox_catalog):
        params = {
            "x": "66",
            "y": "55",
            "width": "120",
            "height": "25",
            "items": "'RECIPES'",
            "var": "HMI.Recipe",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, combobox_catalog, params
        )
        assert geometry["x"] == 66
        assert geometry["y"] == 55
        assert "VisuFbComboBoxInteger" in new_xml
        # template_params substitution landed on the right members.
        assert self._find_member(new_xml, 2114174855) == "'RECIPES'"
        assert self._find_member(new_xml, 397264524) == "HMI.Recipe"
        assert "@@" not in new_xml

    def test_template_param_default_used_when_missing(self, empty_screen, combobox_catalog):
        # No items/var supplied -> catalog defaults fill in.
        params = {"x": "0", "y": "0", "width": "120", "height": "25"}
        new_xml, _, _ = builder.append_element(empty_screen, combobox_catalog, params)
        assert self._find_member(new_xml, 2114174855) == "''"
        assert self._find_member(new_xml, 397264524) == ""

    def test_svg_parse_combobox(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="combobox" data-items="\'RECIPES\'" '
            'data-var="HMI.Recipe" '
            'x="66" y="55" width="120" height="25"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        elem = parsed["elements"][0]
        assert elem["type"] == "combobox"
        assert elem["params"]["items"] == "'RECIPES'"
        assert elem["params"]["var"] == "HMI.Recipe"

    def test_svg_parse_combobox_defaults(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="combobox" x="0" y="0" width="120" height="25"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        elem = parsed["elements"][0]
        assert elem["params"]["items"] == ""
        assert elem["params"]["var"] == ""

    def test_export_round_trip(self, empty_screen, combobox_catalog):
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        params = {
            "x": "66",
            "y": "55",
            "width": "120",
            "height": "25",
            "items": "'RECIPES'",
            "var": "HMI.Recipe",
        }
        new_xml, _, _ = builder.append_element(empty_screen, combobox_catalog, params)
        # Pull the appended combobox element node back out and decompile it.
        root = ET.fromstring(new_xml)
        combo_node = None
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "Single":
                for child in list(el):
                    ct = (
                        child.tag.split("}")[-1]
                        if "}" in str(child.tag)
                        else child.tag
                    )
                    if (
                        ct == "Single"
                        and child.attrib.get("Name") == "VisualElementTypeName"
                        and (child.text or "") == "VisuFbComboBoxInteger"
                    ):
                        combo_node = el
                        break
                if combo_node is not None:
                    break
        assert combo_node is not None
        out = svg_export._element_to_svg(combo_node)
        assert 'data-cds-type="combobox"' in out
        assert "data-items" in out
        assert "data-var" in out


class TestComboBoxGvl:
    def test_combobox_var_collected(self):
        from cli.visu import gvl

        elems = [{"type": "combobox", "params": {"var": "HMI.Recipe"}}]
        assert gvl.collect_variables(elems) == {"HMI.Recipe": "Recipe"}

    def test_combobox_var_typed_int(self):
        from cli.visu import gvl

        elems = [{"type": "combobox", "params": {"var": "HMI.Recipe"}}]
        assert gvl.collect_variable_types(elems) == {"HMI.Recipe": "INT"}


@pytest.fixture
def alarm_banner_catalog():
    return _catalog.load_catalog("alarm-banner")


class TestAlarmBanner:
    """AlarmBanner element (geometry-only, no bound variable)."""

    def _find_member(self, xml_text, member_id):
        return TestElement._find_member(self, xml_text, member_id)

    def test_catalog_loads(self, alarm_banner_catalog):
        assert alarm_banner_catalog["type"] == "alarm-banner"
        assert alarm_banner_catalog["visualElementTypeName"] == "VisuFbElemAlarmBanner"
        assert alarm_banner_catalog["template_params"] == {}

    def test_append_alarm_banner(self, empty_screen, alarm_banner_catalog):
        params = {
            "x": "12",
            "y": "34",
            "width": "400",
            "height": "25",
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, alarm_banner_catalog, params
        )
        assert geometry["x"] == 12
        assert geometry["y"] == 34
        assert geometry["width"] == 400
        assert geometry["height"] == 25
        assert "VisuFbElemAlarmBanner" in new_xml
        assert "@@" not in new_xml

    def test_svg_parse_alarm_banner(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="alarm-banner" '
            'x="12" y="34" width="400" height="25"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        elem = parsed["elements"][0]
        assert elem["type"] == "alarm-banner"
        assert elem["params"]["x"] == "12"
        assert elem["params"]["y"] == "34"
        assert elem["params"]["width"] == "400"
        assert elem["params"]["height"] == "25"

    def test_svg_parse_alarm_banner_defaults(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="alarm-banner"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        elem = parsed["elements"][0]
        assert elem["params"]["x"] == "0"
        assert elem["params"]["y"] == "0"
        assert elem["params"]["width"] == "400"
        assert elem["params"]["height"] == "25"

    def test_export_round_trip(self, empty_screen, alarm_banner_catalog):
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        params = {
            "x": "12",
            "y": "34",
            "width": "400",
            "height": "25",
        }
        new_xml, _, _ = builder.append_element(empty_screen, alarm_banner_catalog, params)
        # Pull the appended alarm-banner element node back out and decompile it.
        root = ET.fromstring(new_xml)
        ab_node = None
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
            if tag == "Single":
                for child in list(el):
                    ct = (
                        child.tag.split("}")[-1]
                        if "}" in str(child.tag)
                        else child.tag
                    )
                    if (
                        ct == "Single"
                        and child.attrib.get("Name") == "VisualElementTypeName"
                        and (child.text or "") == "VisuFbElemAlarmBanner"
                    ):
                        ab_node = el
                        break
                if ab_node is not None:
                    break
        assert ab_node is not None
        out = svg_export._element_to_svg(ab_node)
        assert 'data-cds-type="alarm-banner"' in out
        assert 'x="12"' in out
        assert 'y="34"' in out
        assert 'width="400"' in out
        assert 'height="25"' in out


class TestFrameDecompile:
    """Frame element decompile tests (to-svg only, Stage A)."""

    def _make_frame_xml(self, extra=""):
        return (
            '<Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbFrame</Single>'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single>'
            '<Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">844</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">173</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">67</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">40</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2189774824</Single>'
            '<Single Name="Value" Type="string">5</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">1355317294</Single>'
            '<Single Name="Value" Type="string">1</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            '<Single Name="Wrapper">'
            '<Single Name="VisNodeRefs33" Type="string">PUMP_ICON</Single>'
            '<List Name="TypeNodeChildren">'
            '<Single>'
            '<Single Name="TypeNodeName" Type="string">pump_number</Single>'
            '<Single Name="TypeNodeIdLong" Type="long">2189774824</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="TypeNodeName" Type="string">down</Single>'
            '<Single Name="TypeNodeIdLong" Type="long">1355317294</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            + extra
            + '</Single>'
        )

    def test_render_frame_basic(self):
        """Full frame with geometry, visu ref, and params."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_frame_xml()
        node = ET.fromstring(xml)
        out = svg_export._render_frame(node)
        assert 'data-cds-type="frame"' in out
        assert 'data-visu="PUMP_ICON"' in out
        assert 'data-param-pump_number="5"' in out
        assert 'data-param-down="1"' in out
        assert 'x="844"' in out
        assert 'width="67"' in out
        assert 'y="173"' in out
        assert 'height="40"' in out

    def test_render_frame_no_decoy_params(self):
        """Decoy internal TypeNodeChildren does not leak into output."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        decoy = (
            '<Single Name="iX">'
            '<List Name="TypeNodeChildren">'
            '<Single>'
            '<Single Name="TypeNodeName" Type="string">iX</Single>'
            '<Single Name="TypeNodeIdLong" Type="long">999999999</Single>'
            '</Single>'
            '</List>'
            '</Single>'
        )
        xml = self._make_frame_xml(decoy)
        node = ET.fromstring(xml)
        out = svg_export._render_frame(node)
        assert 'data-cds-type="frame"' in out
        assert 'data-visu="PUMP_ICON"' in out
        assert 'data-param-pump_number="5"' in out
        assert 'data-param-down="1"' in out
        assert 'data-param-iX' not in out

    def test_dispatch_frame(self):
        """svg_export._element_to_svg routes VisuFbFrame to _render_frame."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_frame_xml()
        node = ET.fromstring(xml)
        out = svg_export._element_to_svg(node)
        assert 'data-cds-type="frame"' in out
        assert 'data-visu="PUMP_ICON"' in out
        assert 'data-param-pump_number="5"' in out
        assert 'data-param-down="1"' in out

    def test_frame_no_reference(self):
        """Frame with only Null VisNodeRefs33 still renders geometry, no data-visu."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = (
            '<Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbFrame</Single>'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single>'
            '<Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">100</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">200</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">300</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">400</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            '<Null Name="VisNodeRefs33"/>'
            '</Single>'
        )
        node = ET.fromstring(xml)
        out = svg_export._render_frame(node)
        assert 'data-cds-type="frame"' in out
        assert 'data-visu' not in out
        assert 'x="100"' in out
        assert 'y="200"' in out
        assert 'width="300"' in out
        assert 'height="400"' in out


class TestSliderDecompile:
    """Slider element decompile tests (to-svg only)."""

    def _make_slider_xml(self, extra=""):
        return (
            '<Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbElemSlider</Single>'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single>'
            '<Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">100</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">200</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">300</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">400</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">397264524</Single>'
            '<Single Name="Value" Type="string">DB_MATRIX.rProductivity</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2640826223</Single>'
            '<Single Name="Value" Type="string">VERTICAL</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">1404881523</Single>'
            '<Single Name="Value" Type="float">20</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">3837067714</Single>'
            '<Single Name="Value" Type="float">100</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            + extra
            + '</Single>'
        )

    def _make_minimal_slider_xml(self):
        """Slider with only geometry members, no slider-specific attrs."""
        return (
            '<Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbElemSlider</Single>'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single>'
            '<Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">50</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">60</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">200</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">30</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            '</Single>'
        )

    def test_render_slider_basic(self):
        """Full slider with geometry, var, orientation, min, max."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_slider_xml()
        node = ET.fromstring(xml)
        out = svg_export._render_slider(node)
        assert 'data-cds-type="slider"' in out
        assert 'data-var="DB_MATRIX.rProductivity"' in out
        assert 'data-orientation="VERTICAL"' in out
        assert 'data-min="20"' in out
        assert 'data-max="100"' in out
        assert 'x="100"' in out
        assert 'y="200"' in out
        assert 'width="300"' in out
        assert 'height="400"' in out

    def test_dispatch_slider(self):
        """svg_export._element_to_svg routes VisuFbElemSlider to _render_slider."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_slider_xml()
        node = ET.fromstring(xml)
        out = svg_export._element_to_svg(node)
        assert 'data-cds-type="slider"' in out
        assert 'data-var="DB_MATRIX.rProductivity"' in out
        assert 'data-orientation="VERTICAL"' in out
        assert 'data-min="20"' in out
        assert 'data-max="100"' in out

    def test_slider_minimal(self):
        """Slider with only geometry renders data-cds-type, no optional attrs, no raise."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_minimal_slider_xml()
        node = ET.fromstring(xml)
        out = svg_export._render_slider(node)
        assert 'data-cds-type="slider"' in out
        assert 'data-var' not in out
        assert 'data-orientation' not in out
        assert 'data-min' not in out
        assert 'data-max' not in out
        assert 'x="50"' in out
        assert 'y="60"' in out
        assert 'width="200"' in out
        assert 'height="30"' in out


# ===================================================================
# Capture-frame tests (spec 1/2)
# ===================================================================


class TestCaptureFrame:
    """Tests for _extract_frame_params, _tokenize_frame, _build_frame_catalog."""

    @staticmethod
    def _make_frame_xml():
        """Minimal VisuFbFrame XML for capture-frame tests.

        Includes geometry members, the 363316305 member with interface
        definition (params a=111/INT, b=222/INT), identifier, and
        VisualElementId.
        """
        return (
            '<Single Type="{f86c2928-8614-4cca-824b-e819ac4d58c4}" Method="IArchivable">'
            '<Array Name="ConfiguredComplexInputs" />'
            '<List Name="Elements" />'
            '<Null Name="VisualElementDescription" />'
            '<Single Name="VisualElemMemberList" Type="{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}" Method="IArchivable">'
            '<List Name="VisualElemMemberList" Type="{a4b83bea-3742-489c-9fe8-d96d68dba7ab}">'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">100</Single>'
            '</Single>'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">200</Single>'
            '</Single>'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">300</Single>'
            '</Single>'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">400</Single>'
            '</Single>'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">550940142</Single>'
            '<Single Name="Value" Type="int">250</Single>'
            '</Single>'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">1473355128</Single>'
            '<Single Name="Value" Type="int">400</Single>'
            '</Single>'
            '<Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">'
            '<Single Name="Id" Type="long">363316305</Single>'
            '<Single Name="Value" Type="{503c5b2e-e80e-4ee7-ae00-c5b93a62b1aa}" Method="IArchivable">'
            '<Single Name="StructuredTypeNodeIsAnimation" Type="bool">False</Single>'
            '<List Name="TypeNodeChildren" Type="System.Collections.ArrayList">'
            '<Single Type="{f8db32ff-bdd5-49e9-9014-6d9a6dea5d8c}" Method="IArchivable">'
            '<Single Name="VisuNodeReferenceGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>'
            '<Null Name="VisuNodeReference" />'
            '<Single Name="VisNodeRefs33" Type="string">test_frame</Single>'
            '<List Name="TypeNodeChildren" Type="System.Collections.ArrayList">'
            '<Single Type="{f7e1e748-ea0f-4fcb-b563-94837ee17e8d}" Method="IArchivable">'
            '<Single Name="TypeNodeName" Type="string">a</Single>'
            '<Single Name="TypeNodeIdLong" Type="long">111</Single>'
            '<Single Name="TypeNodeType" Type="{b12a9636-e818-4598-ae0d-fb6a2446102c}" Method="IArchivable">'
            '<Single Name="QualifiedName" Type="string">INT</Single>'
            '</Single>'
            '</Single>'
            '<Single Type="{f7e1e748-ea0f-4fcb-b563-94837ee17e8d}" Method="IArchivable">'
            '<Single Name="TypeNodeName" Type="string">b</Single>'
            '<Single Name="TypeNodeIdLong" Type="long">222</Single>'
            '<Single Name="TypeNodeType" Type="{b12a9636-e818-4598-ae0d-fb6a2446102c}" Method="IArchivable">'
            '<Single Name="QualifiedName" Type="string">INT</Single>'
            '</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            '</List>'
            '</Single>'
            '</Single>'
            '</List>'
            '</Single>'
            '<Single Name="VisualElementName" Type="string">Frame</Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbFrame</Single>'
            '<Single Name="VisualElementIsRectangle" Type="bool">True</Single>'
            '<Single Name="VisualElementIdentifier" Type="string">GenElemInst_5</Single>'
            '<Single Name="VisualElementId" Type="int">42</Single>'
            '</Single>'
        )

    def test_extract_params(self):
        """_extract_frame_params returns expected params a(111,INT), b(222,INT)."""
        import xml.etree.ElementTree as ET
        from cli.visu import builder

        xml = self._make_frame_xml()
        node = ET.fromstring(xml)
        params, visu_name = builder._extract_frame_params(node)

        assert visu_name == "test_frame"
        assert len(params) == 2
        assert params[0]["name"] == "a"
        assert params[0]["member_id"] == 111
        assert params[0]["iec_type"] == "INT"
        assert params[1]["name"] == "b"
        assert params[1]["member_id"] == 222
        assert params[1]["iec_type"] == "INT"

    def test_tokenize_geometry(self):
        """_tokenize_frame replaces geometry, identifier, VE id and inserts
        @@PARAM_MEMBERS@@."""
        import xml.etree.ElementTree as ET
        from cli.visu import builder

        xml = self._make_frame_xml()
        node = ET.fromstring(xml)
        fragment = ET.tostring(node, encoding="unicode")
        param_ids = {111, 222}
        template = builder._tokenize_frame(fragment, param_ids)

        assert "@@X@@" in template
        assert "@@WIDTH@@" in template
        assert "@@IDENTIFIER@@" in template
        assert "@@VISUAL_ELEMENT_ID@@" in template
        assert "@@PARAM_MEMBERS@@" in template

        # Raw value 100 should be replaced by @@X@@, 300 by @@WIDTH@@
        assert ">100<" not in template.replace("@@X@@", "MARK")
        assert ">300<" not in template.replace("@@WIDTH@@", "MARK")

    def test_tokenize_preserves_interface(self):
        """_tokenize_frame does not corrupt the interface definition or
        sub-visu name."""
        import xml.etree.ElementTree as ET
        from cli.visu import builder

        xml = self._make_frame_xml()
        node = ET.fromstring(xml)
        fragment = ET.tostring(node, encoding="unicode")
        param_ids = {111, 222}
        template = builder._tokenize_frame(fragment, param_ids)

        # Interface param ids are NOT tokenized.
        assert 'TypeNodeIdLong" Type="long">111' in template
        assert 'TypeNodeIdLong" Type="long">222' in template
        # Sub-visu name preserved.
        assert "test_frame" in template

    def test_catalog_shape(self):
        """_build_frame_catalog produces the expected catalog shape."""
        from cli.visu import builder

        params = [
            {"name": "a", "member_id": 111, "iec_type": "INT", "default": ""},
            {"name": "b", "member_id": 222, "iec_type": "INT", "default": ""},
        ]
        catalog = builder._build_frame_catalog("test_frame", params)

        assert catalog["type"] == "frame"
        assert catalog["visualElementTypeName"] == "VisuFbFrame"
        assert catalog["visu"] == "test_frame"
        assert len(catalog["params"]) == 2
        assert catalog["params"][0]["member_id"] == 111
        assert catalog["params"][1]["name"] == "b"


class TestFrameCompile:
    """Frame element compile tests (parse, param member synthesis, compile, error)."""

    def test_parse_frame(self):
        """_parse_frame extracts geometry, visu, and data-param-* attrs."""
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
            '<rect data-cds-type="frame" data-visu="X" '
            'data-param-a="7" data-param-b="9" '
            'x="10" y="20" width="200" height="100"/></svg>'
        )
        parsed = svg_import.parse_svg(svg)
        assert len(parsed["elements"]) == 1
        elem = parsed["elements"][0]
        assert elem["type"] == "frame"
        assert elem["params"]["visu"] == "X"
        assert elem["params"]["params"] == {"a": "7", "b": "9"}
        assert elem["params"]["x"] == "10"
        assert elem["params"]["y"] == "20"
        assert elem["params"]["width"] == "200"
        assert elem["params"]["height"] == "100"

    def test_render_param_members(self):
        """_render_frame_param_members resolves values, defaults, skips empty."""
        catalog = {
            "type": "frame",
            "visualElementTypeName": "VisuFbFrame",
            "visu": "test_visu",
            "golden_template": "test.xml.tmpl",
            "base_members": [],
            "params": [
                {"name": "a", "member_id": 111, "iec_type": "INT", "default": ""},
                {"name": "b", "member_id": 222, "iec_type": "INT", "default": "5"},
            ],
        }
        params = {"params": {"a": "7"}}
        result = builder._render_frame_param_members(catalog, params)
        # a=7 was provided -> should appear.
        assert 'Name="Id" Type="long">111' in result
        assert 'Name="Value" Type="string">7' in result
        # b not provided, default is "5" -> should appear.
        assert 'Name="Id" Type="long">222' in result
        assert 'Name="Value" Type="string">5' in result
        # Correct _MEMBER_TYPE guid.
        assert "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" in result

    def test_compile_frame_end_to_end(self, empty_screen):
        """append_element with golden_template_text substitutes all placeholders
        and renders param members."""
        tmpl = (
            '<Single Type="{f86c2928-8614-4cca-824b-e819ac4d58c4}" Method="IArchivable">'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single>'
            '<Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value">@@X@@</Single>'
            '</Single>'
            '<Single>'
            '<Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value">@@Y@@</Single>'
            '</Single>'
            '@@PARAM_MEMBERS@@'
            '</List>'
            '</Single>'
            '<Single Name="VisualElementIdentifier">@@IDENTIFIER@@</Single>'
            '<Single Name="VisualElementId">@@VISUAL_ELEMENT_ID@@</Single>'
            '</Single>'
        )
        cat = {
            "type": "frame",
            "visualElementTypeName": "VisuFbFrame",
            "visu": "test_visu",
            "golden_template": "test.xml.tmpl",
            "base_members": [],
            "params": [
                {"name": "a", "member_id": 111, "iec_type": "INT", "default": ""},
            ],
        }
        params = {
            "x": "10",
            "y": "20",
            "width": "200",
            "height": "100",
            "visu": "test_visu",
            "params": {"a": "7"},
        }
        new_xml, geometry, info = builder.append_element(
            empty_screen, cat, params,
            golden_template_text=tmpl,
        )
        # No unresolved placeholders.
        assert "@@" not in new_xml
        # Geometry members present.
        assert 'Name="Id" Type="long">1649127785' in new_xml
        assert 'Name="Id" Type="long">357335551' in new_xml
        # Param a=7 landed with correct member id.
        assert 'Name="Id" Type="long">111' in new_xml
        assert 'Name="Value" Type="string">7' in new_xml

    def test_frame_catalog_missing(self, tmp_path):
        from cli.visu import catalog as _catalog

        with pytest.raises(_catalog.CatalogError) as exc:
            _catalog.load_frame_catalog(str(tmp_path), "nonexistent")
        assert "capture-frame" in str(exc.value)


# ===================================================================
# Dialog-open decompile tests (Stage C, read-only)
# ===================================================================


class TestDialogDecompile:
    """Dialog-open input-action decompile tests (to-svg only)."""

    def _make_opener_xml(self):
        """VisuFbElemSimple with OnMouseClick dialog-open and ST snippet."""
        return (
            '<Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbElemSimple</Single>'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single><Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">100</Single></Single>'
            '<Single><Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">200</Single></Single>'
            '<Single><Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">300</Single></Single>'
            '<Single><Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">400</Single></Single>'
            '</List>'
            '</Single>'
            '<Dictionary Name="VisualElementInputActions">'
            '<Entry>'
            '<Key><Single Type="string">OnMouseClick</Single></Key>'
            '<Value>'
            '<Array Type="{69265815-6ecb-4b71-9d97-8ce14e84f3cb}">'
            '<Single Type="{c01cd804-0a56-4714-ba1b-1040cfc48b6b}" Method="IArchivable">'
            '<Null Name="Dialog" />'
            '<Single Name="Dialog33" Type="string">pump_faceplate</Single>'
            '<Dictionary Name="Parameters" />'
            '<Dictionary Name="Selected" />'
            '<Single Name="OpenModal" Type="bool">True</Single>'
            '<Single Name="OpenCentered" Type="bool">True</Single>'
            '<Single Name="PositionX" Type="string" />'
            '<Single Name="PositionY" Type="string" />'
            '</Single>'
            '<Single Type="{6302d3fe-6ea5-4c42-819a-a9734a133b3d}" Method="IArchivable">'
            '<Single Name="STSnippet" Type="string">DB_DRV.x:=1;</Single>'
            '</Single>'
            '</Array>'
            '</Value>'
            '</Entry>'
            '</Dictionary>'
            '</Single>'
        )

    def _make_plain_xml(self):
        """VisuFbElemSimple with NO input-actions (geometry only)."""
        return (
            '<Single>'
            '<Single Name="VisualElementTypeName" Type="string">VisuFbElemSimple</Single>'
            '<Single Name="VisualElemMemberList">'
            '<List Name="VisualElemMemberList">'
            '<Single><Single Name="Id" Type="long">1649127785</Single>'
            '<Single Name="Value" Type="int">100</Single></Single>'
            '<Single><Single Name="Id" Type="long">357335551</Single>'
            '<Single Name="Value" Type="int">200</Single></Single>'
            '<Single><Single Name="Id" Type="long">2422045748</Single>'
            '<Single Name="Value" Type="int">300</Single></Single>'
            '<Single><Single Name="Id" Type="long">2134141914</Single>'
            '<Single Name="Value" Type="int">400</Single></Single>'
            '</List>'
            '</Single>'
            '</Single>'
        )

    def test_dialog_attrs_emitted(self):
        """decompile emits data-open-dialog and related data attrs."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_opener_xml()
        node = ET.fromstring(xml)
        out = svg_export._element_to_svg(node)
        assert 'data-open-dialog="pump_faceplate"' in out
        assert 'data-dialog-modal="true"' in out
        assert 'data-dialog-centered="true"' in out
        assert 'data-dialog-st="DB_DRV.x:=1;"' in out

    def test_no_dialog_no_attrs(self):
        """decompile of a plain element emits NO data-open-dialog."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        xml = self._make_plain_xml()
        node = ET.fromstring(xml)
        out = svg_export._element_to_svg(node)
        assert 'data-open-dialog' not in out

    def test_dialog_helper_none(self):
        """_read_dialog_action returns None for plain, dict for opener."""
        from cli.visu import svg_export
        import xml.etree.ElementTree as ET

        plain_xml = self._make_plain_xml()
        plain_node = ET.fromstring(plain_xml)
        assert svg_export._read_dialog_action(plain_node) is None

        opener_xml = self._make_opener_xml()
        opener_node = ET.fromstring(opener_xml)
        info = svg_export._read_dialog_action(opener_node)
        assert info is not None
        assert info["dialog"] == "pump_faceplate"
        assert info["modal"] == "true"
        assert info["centered"] == "true"
        assert info["st"] == "DB_DRV.x:=1;"


# ===================================================================
# Dialog-open COMPILE tests (Stage C, button-only)
# ===================================================================


class TestDialogCompile:
 """Dialog-open input-action compile tests (from-svg and builder)."""

 def test_render_open_dialog_action(self):
  """_render_input_action with open_dialog spec produces correct XML."""
  spec = builder._visual_input_action("open_dialog")
  values = {"dialog": "pump_faceplate", "modal": "True", "centered": "True"}
  result = builder._render_input_action(spec, values)
  # Type guid.
  assert "{c01cd804-0a56-4714-ba1b-1040cfc48b6b}" in result
  # Dialog null before Dialog33.
  dialog_null_pos = result.find('<Null Name="Dialog"')
  dialog33_pos = result.find("Dialog33")
  assert dialog_null_pos >= 0, "Missing <Null Name='Dialog' />"
  assert dialog33_pos >= 0, "Missing Dialog33"
  assert dialog_null_pos < dialog33_pos, (
   "Dialog null must appear before Dialog33"
  )
  # Empty Parameters and Selected dicts between Dialog33 and OpenModal.
  assert '<Dictionary Type="System.Collections.Hashtable" Name="Parameters" />' in result
  assert '<Dictionary Type="System.Collections.Hashtable" Name="Selected" />' in result
  params_pos = result.find('Name="Parameters"')
  selected_pos = result.find('Name="Selected"')
  open_modal_pos = result.find("OpenModal")
  assert params_pos < open_modal_pos, "Parameters dict before OpenModal"
  assert selected_pos < open_modal_pos, "Selected dict before OpenModal"
  # Boolean fields.
  assert ">True<" in result
  # Field order: Dialog null -> Dialog33 -> Parameters -> Selected -> OpenModal -> OpenCentered -> PositionX -> PositionY.
  pos_dialog = result.find('<Null Name="Dialog"')
  pos_dialog33 = result.find("Dialog33")
  pos_params = result.find('Name="Parameters"')
  pos_selected = result.find('Name="Selected"')
  pos_modal = result.find("OpenModal")
  pos_centered = result.find("OpenCentered")
  pos_posx = result.find("PositionX")
  pos_posy = result.find("PositionY")
  order = [pos_dialog, pos_dialog33, pos_params, pos_selected,
      pos_modal, pos_centered, pos_posx, pos_posy]
  assert order == sorted(order), (
   "Field order must match the golden template: "
   "Dialog null, Dialog33, Parameters dict, Selected dict, "
   "OpenModal, OpenCentered, PositionX, PositionY"
  )

 def test_dict_field_kind(self):
  """A field with kind='dict' renders a self-closing Dictionary."""
  spec = builder._visual_input_action("open_dialog")
  values = {"dialog": "test", "modal": "True", "centered": "True"}
  result = builder._render_input_action(spec, values)
  assert '<Dictionary Type="System.Collections.Hashtable" Name="Parameters" />' in result

 def test_parse_dialog_attrs(self):
  """SVG parse of a button with data-open-dialog produces input_actions."""
  svg = (
   '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
   '<rect x="10" y="20" width="120" height="40" data-cds-type="button"'
   ' data-text="Open"'
   ' data-open-dialog="pump_faceplate"'
   ' data-dialog-modal="true"'
   ' data-dialog-st="X:=1;"'
   '/></svg>'
  )
  parsed = svg_import.parse_svg(svg)
  button = parsed["elements"][0]
  assert button["type"] == "button"
  actions = button["params"].get("input_actions", [])
  assert len(actions) == 2, "Expected open_dialog + st_snippet"
  # First action: open_dialog
  assert actions[0]["event"] == "OnMouseClick"
  assert actions[0]["type"] == "open_dialog"
  assert actions[0]["values"]["dialog"] == "pump_faceplate"
  assert actions[0]["values"]["modal"] == "True"
  assert actions[0]["values"]["centered"] == "True"
  # Second action: st_snippet
  assert actions[1]["event"] == "OnMouseClick"
  assert actions[1]["type"] == "st_snippet"
  assert actions[1]["values"]["snippet"] == "X:=1;"

 def test_parse_dialog_wrong_element(self):
  """data-open-dialog on a non-button raises ValueError."""
  svg = (
   '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
   '<rect x="10" y="20" width="120" height="40"'
   ' data-open-dialog="pump_faceplate"/>'
   '</svg>'
  )
  with pytest.raises(ValueError) as exc:
   svg_import.parse_svg(svg)
  assert "data-open-dialog is only supported on a button" in str(exc.value)

 def test_compile_round_trip(self, empty_screen, button_catalog):
  """Compile a button with dialog input_actions and verify XML output."""
  from cli.visu import svg_export
  import xml.etree.ElementTree as ET

  params = {
   "x": "10",
   "y": "20",
   "width": "120",
   "height": "40",
   "text": "Open",
   "input_actions": [
    {
     "event": "OnMouseClick",
     "type": "open_dialog",
     "values": {
      "dialog": "pump_faceplate",
      "modal": "True",
      "centered": "True",
      "position_x": "",
      "position_y": "",
     },
    },
    {
     "event": "OnMouseClick",
     "type": "st_snippet",
     "values": {"snippet": "X:=1;"},
    },
   ],
  }
  new_xml, geometry, info = builder.append_element(
   empty_screen, button_catalog, params
  )
  # Compile verification: Dialog33 and STSnippet in output.
  assert "Dialog33" in new_xml
  assert "pump_faceplate" in new_xml
  assert "STSnippet" in new_xml
  assert "X:=1;" in new_xml
  # Decompile verification (round-trip): extract the button node back to SVG.
  root = ET.fromstring(new_xml)
  btn_node = None
  for el in root.iter():
   tag = el.tag.split("}")[-1] if "}" in str(el.tag) else el.tag
   if tag == "Single":
    for child in list(el):
     ct = (
      child.tag.split("}")[-1]
      if "}" in str(child.tag)
      else child.tag
     )
     if (
      ct == "Single"
      and child.attrib.get("Name") == "VisualElementTypeName"
      and (child.text or "") == "VisuFbElemButton"
     ):
      btn_node = el
      break
   if btn_node is not None:
    break
  assert btn_node is not None, "Button node not found in compiled XML"
  out = svg_export._element_to_svg(btn_node)
  assert 'data-open-dialog="pump_faceplate"' in out
  assert 'data-dialog-modal="true"' in out
  assert 'data-dialog-st="X:=1;"' in out

