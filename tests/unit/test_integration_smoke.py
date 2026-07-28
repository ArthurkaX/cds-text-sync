# -*- coding: utf-8 -*-
"""Integration smoke tests for the full visu pipeline.

Exercises SVG import -> GVL detection -> screen build -> read-back -> SVG export
end to end, so a break anywhere along the seam surfaces as a failing test rather
than a module-collection error.
"""

import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import builder, catalog, gvl, screen_xml, svg_export, svg_import, themes


SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">
  <defs><style>:root{ --surface:#1e1e1e; --primary:#0078d4; }</style></defs>
  <text x="20" y="30" font-size="14"
        data-cds-type="textfield" data-width="150" data-height="24"
        data-text-var="HMI.Temperature">%.1f C</text>
  <rect x="20" y="60" width="120" height="40"
        data-cds-type="button" data-text="Start" data-cds-tap="TAP HMI.StartPump"/>
</svg>"""


@pytest.fixture
def parsed_elements():
    return svg_import.parse_svg(SAMPLE_SVG)["elements"]


@pytest.fixture
def built_screen():
    xml = builder.build_screen(
        name="IntegrationTest",
        size_x=400,
        size_y=200,
        parent_guid="aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        parent_svnode_guid="ddc05353-f826-4861-84cf-5fd88f7a319e",
        path_segments=["HMI"],
    )
    rect_cat = catalog.load_catalog("rectangle")
    xml, geom, _info = builder.append_element(
        xml,
        rect_cat,
        {"x": "10", "y": "10", "width": "100", "height": "50"},
        theme_colors=themes.load_theme("flat-style"),
    )
    return xml, geom


def test_parse_svg_extracts_all_elements(parsed_elements):
    assert len(parsed_elements) == 2


def test_gvl_detects_bound_variables(parsed_elements):
    detected = gvl.collect_variables(parsed_elements)
    assert "HMI.Temperature" in detected
    assert "HMI.StartPump" in detected


def test_gvl_file_created_with_detected_vars(tmp_path, parsed_elements):
    td = str(tmp_path)
    os.makedirs(os.path.join(td, "POUs"))

    gvl_path = gvl.ensure_gvl(td, parsed_elements, gvl_name="VisuVars")
    assert gvl_path is not None
    with open(gvl_path) as f:
        content = f.read()
    assert "Temperature" in content
    assert "StartPump" in content


def test_gvl_second_call_is_idempotent(tmp_path, parsed_elements):
    td = str(tmp_path)
    os.makedirs(os.path.join(td, "POUs"))

    first = gvl.ensure_gvl(td, parsed_elements, gvl_name="VisuVars")
    second = gvl.ensure_gvl(td, parsed_elements, gvl_name="VisuVars")
    assert second == first


def test_append_element_sets_geometry(built_screen):
    _xml, geom = built_screen
    assert geom["x"] == 10


def test_screen_xml_reads_back_element_and_size(built_screen):
    xml, _geom = built_screen
    elems = screen_xml.list_elements(xml)
    assert len(elems) == 1
    assert elems[0]["x"] == "10"
    assert screen_xml.read_screen_size(xml) == (400, 200)


def test_svg_export_roundtrip(built_screen):
    xml, _geom = built_screen
    svg_out = svg_export.screen_to_svg(xml)
    assert "<svg" in svg_out
    assert "</svg>" in svg_out


# A CODESYS text element is a box plus an alignment, an SVG <text> is a baseline
# plus an anchor, and the import converts between them. The export used to emit
# the box top as the baseline and drop the alignment entirely, so a compile ->
# decompile round trip quietly moved every caption: centred ones went flush left
# and all of them rose by one font-size.
TEXT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">
  <text x="40" y="120" data-width="112" data-height="16" font-size="11"
        text-anchor="middle">Centred</text>
  <text x="200" y="120" data-width="48" data-height="16" font-size="11"
        text-anchor="end">Right</text>
  <text x="300" y="120" font-size="12">Left</text>
  <text data-cds-type="textfield" x="40" y="160" data-width="144" data-height="24"
        font-size="16" data-text-var="HMI.V" text-anchor="middle">%d</text>
</svg>"""


@pytest.fixture
def text_screen_svg():
    """TEXT_SVG compiled to a screen and decompiled back to a sketch."""
    parsed = svg_import.parse_svg(TEXT_SVG)
    xml = builder.build_screen(
        name="TextRoundTrip",
        size_x=400,
        size_y=200,
        parent_guid="aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        parent_svnode_guid="ddc05353-f826-4861-84cf-5fd88f7a319e",
        path_segments=["HMI"],
    )
    theme = themes.load_theme("flat-style")
    for element in parsed["elements"]:
        xml, _geom, _info = builder.append_element(
            xml, catalog.load_catalog(element["type"]), element["params"],
            theme_colors=theme,
        )
    return svg_export.screen_to_svg(xml)


@pytest.mark.parametrize("anchor", ['text-anchor="middle"', 'text-anchor="end"'])
def test_export_restores_text_anchor(text_screen_svg, anchor):
    assert anchor in text_screen_svg


def test_export_leaves_left_aligned_text_unanchored(text_screen_svg):
    assert text_screen_svg.count("text-anchor") == 3  # two labels + textfield


@pytest.mark.parametrize("baseline", ['y="120"', 'y="160"'])
def test_export_restores_text_baseline(text_screen_svg, baseline):
    """Every <text> in TEXT_SVG sits on y=120 or y=160; none may drift."""
    assert baseline in text_screen_svg
    assert text_screen_svg.count("<text") == text_screen_svg.count('y="120"') + (
        text_screen_svg.count('y="160"')
    )


# A button's behaviour is split across two places in the compiled XML: tap and
# toggle land in ConfiguredComplexInputs, per-event actions in
# VisualElementInputActions. The export read back neither, so a decompiled
# sketch had buttons that looked right and did nothing -- and recompiling it
# stripped the wiring out of a screen that had it.
BUTTON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">
  <rect data-cds-type="button" x="24" y="24" width="160" height="48"
        data-text="Start" data-cds-tap="TAP HMI.xStart"/>
  <rect data-cds-type="button" x="24" y="88" width="160" height="48"
        data-text="Auto" data-cds-action="TOGGLE HMI.xAuto"/>
  <rect data-cds-type="button" x="200" y="88" width="160" height="48"
        data-text="Bump" data-cds-action="OnMouseClick: ST HMI.r := HMI.r + 0.5;"/>
</svg>"""


@pytest.fixture
def button_screen_svg():
    """BUTTON_SVG compiled to a screen and decompiled back to a sketch."""
    parsed = svg_import.parse_svg(BUTTON_SVG)
    xml = builder.build_screen(
        name="ButtonRoundTrip",
        size_x=400,
        size_y=200,
        parent_guid="aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        parent_svnode_guid="ddc05353-f826-4861-84cf-5fd88f7a319e",
        path_segments=["HMI"],
    )
    theme = themes.load_theme("flat-style")
    for element in parsed["elements"]:
        xml, _geom, _info = builder.append_element(
            xml, catalog.load_catalog(element["type"]), element["params"],
            theme_colors=theme,
        )
    return svg_export.screen_to_svg(xml)


@pytest.mark.parametrize(
    "clause",
    [
        "TAP HMI.xStart",
        "TOGGLE HMI.xAuto",
        "OnMouseClick: ST HMI.r := HMI.r + 0.5;",
    ],
)
def test_export_restores_button_actions(button_screen_svg, clause):
    assert 'data-cds-action="{0}"'.format(clause.replace(">", "&gt;")) in (
        button_screen_svg
    )


def test_decompiled_buttons_recompile_to_the_same_wiring():
    """The round trip has to be a fixed point, not merely non-empty."""
    first = svg_import.parse_svg(BUTTON_SVG)["elements"]
    xml = builder.build_screen(
        name="ButtonRoundTrip",
        size_x=400,
        size_y=200,
        parent_guid="aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        parent_svnode_guid="ddc05353-f826-4861-84cf-5fd88f7a319e",
        path_segments=["HMI"],
    )
    theme = themes.load_theme("flat-style")
    for element in first:
        xml, _geom, _info = builder.append_element(
            xml, catalog.load_catalog(element["type"]), element["params"],
            theme_colors=theme,
        )
    second = svg_import.parse_svg(svg_export.screen_to_svg(xml))["elements"]

    def wiring(elements):
        return [
            (e["params"].get("tap_var", ""),
             e["params"].get("configured_inputs", []),
             e["params"].get("input_actions", []))
            for e in elements
        ]

    # data-cds-tap and data-cds-action="TAP ..." are two spellings of one thing,
    # so compare the compiled effect rather than which attribute carried it.
    def normalised(entry):
        tap, configured, actions = entry
        if tap:
            configured = configured + [
                {"type": "tap", "values": {"variable": tap}}
            ]
        return sorted(map(repr, configured)), actions

    assert [normalised(e) for e in wiring(second)] == [
        normalised(e) for e in wiring(first)
    ]


@pytest.mark.parametrize("font_size,height", [(11, 16), (12, 16), (16, 24), (22, 32)])
def test_unsized_text_box_lands_on_the_4px_grid(font_size, height):
    """An estimated box the author never wrote must not fail the grid rule."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
        '<text x="40" y="160" font-size="{0}">Sample text</text>'
        "</svg>"
    ).format(font_size)
    params = svg_import.parse_svg(svg)["elements"][0]["params"]
    assert int(params["height"]) == height
    assert int(params["width"]) % 4 == 0
