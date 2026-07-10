# -*- coding: utf-8 -*-
"""End-to-end tests for commands.from_svg (the SVG -> screen orchestrator).

The smoke tests exercise the individual pieces (parse_svg, append_element, gvl)
but never from_svg itself, so its orchestration -- screen resolution, resize,
the per-element append loop, output write, and GVL emission -- was untested.
These tests drive the whole command against a temp project-view and assert the
compiled output and side effects, guarding refactors of the function body.
"""

import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import builder, commands, screen_xml


# Primitive rectangles only: no text (no Text-ID allocation) and no bound
# variables, so the fixture needs no textlist or GVL setup, keeping the test
# hermetic while still driving the full append-and-write path.
SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">
  <rect x="10" y="10" width="120" height="40" data-cds-type="rectangle"/>
  <rect x="10" y="70" width="120" height="40" data-cds-type="rectangle"
        fill="#0078d4"/>
</svg>"""


def _make_screen(project_view_dir, name, size_x=400, size_y=200):
    xml = builder.build_screen(
        name=name,
        size_x=size_x,
        size_y=size_y,
        parent_guid="aed6d2f4-6485-4017-982c-3b2fa7b0b4be",
        parent_svnode_guid="ddc05353-f826-4861-84cf-5fd88f7a319e",
        path_segments=[],
    )
    path = os.path.join(project_view_dir, name + ".xml")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml)
    return path


def _write_svg(project_view_dir, text=SAMPLE_SVG):
    svg_path = os.path.join(project_view_dir, "input.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return svg_path


def test_from_svg_compiles_elements_into_out_path(tmp_path, capsys):
    pv = str(tmp_path)
    _make_screen(pv, "Screen1")
    svg_path = _write_svg(pv)
    out_path = os.path.join(pv, "compiled.xml")

    commands.from_svg(
        pv, svg_path, "Screen1", "", None, out_path, False, "",
    )

    assert os.path.isfile(out_path)
    with open(out_path, "r", encoding="utf-8") as handle:
        result_xml = handle.read()
    elems = screen_xml.list_elements(result_xml)
    assert len(elems) == 2
    # from_svg prints the output path as its last stdout line.
    assert out_path in capsys.readouterr().out


def test_from_svg_resizes_screen_to_canvas(tmp_path, capsys):
    pv = str(tmp_path)
    _make_screen(pv, "Screen1", size_x=800, size_y=480)  # differs from canvas
    svg_path = _write_svg(pv)
    out_path = os.path.join(pv, "compiled.xml")

    commands.from_svg(pv, svg_path, "Screen1", "", None, out_path, False, "")

    with open(out_path, "r", encoding="utf-8") as handle:
        result_xml = handle.read()
    assert screen_xml.read_screen_size(result_xml) == (400, 200)


def test_from_svg_missing_screen_exits(tmp_path):
    pv = str(tmp_path)
    svg_path = _write_svg(pv)
    with pytest.raises(SystemExit):
        commands.from_svg(pv, svg_path, "NoSuchScreen", "", None, None, False, "")


def test_from_svg_missing_svg_exits(tmp_path):
    pv = str(tmp_path)
    _make_screen(pv, "Screen1")
    with pytest.raises(SystemExit):
        commands.from_svg(
            pv, os.path.join(pv, "absent.svg"), "Screen1", "", None, None, False, "",
        )
