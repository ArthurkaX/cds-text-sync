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
