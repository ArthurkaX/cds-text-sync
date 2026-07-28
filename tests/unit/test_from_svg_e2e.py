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


def test_recompiling_replaces_the_screen_instead_of_adding_to_it(tmp_path, capsys):
    """A second run must leave the screen with one copy of the sketch.

    ``--screen`` is the documented way to recompile, and it appended: 31
    elements became 62, every one of them sitting exactly on top of its twin,
    so the screen still looked right in the tool and was doubled in CODESYS.
    """
    pv = str(tmp_path)
    path = _make_screen(pv, "Screen1")
    svg_path = _write_svg(pv)

    commands.from_svg(pv, svg_path, "Screen1", "", None, "", False, "")
    commands.from_svg(pv, svg_path, "Screen1", "", None, "", False, "")

    with open(path, "r", encoding="utf-8") as handle:
        result_xml = handle.read()
    assert len(screen_xml.list_elements(result_xml)) == 2
    assert "Replacing 2 existing element(s)" in capsys.readouterr().err


def test_recompiling_drops_what_the_author_deleted(tmp_path):
    """The sketch is the screen: a removed rect must leave the screen too."""
    pv = str(tmp_path)
    path = _make_screen(pv, "Screen1")
    svg_path = _write_svg(pv)
    commands.from_svg(pv, svg_path, "Screen1", "", None, "", False, "")

    one_rect = SAMPLE_SVG.replace(
        '  <rect x="10" y="70" width="120" height="40" data-cds-type="rectangle"\n'
        '        fill="#0078d4"/>\n',
        "",
    )
    assert one_rect != SAMPLE_SVG  # the edit above actually removed a rect
    _write_svg(pv, one_rect)
    commands.from_svg(pv, svg_path, "Screen1", "", None, "", False, "")

    with open(path, "r", encoding="utf-8") as handle:
        assert len(screen_xml.list_elements(handle.read())) == 1


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


def test_from_svg_without_a_screen_says_so(tmp_path, capsys):
    """No --screen must not be reported as a screen that went missing.

    An empty name used to build "<project-view>/.xml" and come back as
    "Screen file not found: ...\\.xml", which reads as damage to the project
    rather than a missing argument -- and points at a file the author never
    named.
    """
    pv = str(tmp_path)
    _make_screen(pv, "Screen1")
    svg_path = _write_svg(pv)

    with pytest.raises(SystemExit):
        commands.from_svg(pv, svg_path, "", "", None, None, False, "")

    message = capsys.readouterr().err
    assert "--screen" in message
    assert ".xml" not in message


def test_create_screen_refuses_to_clobber_and_says_how(tmp_path, capsys):
    """The error has to name the way forward, or the only way out is rm."""
    pv = str(tmp_path)
    _make_screen(pv, "Sibling")  # placement source
    svg_path = _write_svg(pv)

    commands.from_svg(pv, svg_path, "", "", None, "", True, "Made")
    with pytest.raises(SystemExit):
        commands.from_svg(pv, svg_path, "", "", None, "", True, "Made")

    assert "--replace" in capsys.readouterr().err


def test_replace_recompiles_a_screen_and_keeps_its_identity(tmp_path):
    """The Guid is the screen's identity on import.

    Rebuilding with a fresh one would make a recompile add a second screen in
    CODESYS rather than update the one already there.
    """
    pv = str(tmp_path)
    _make_screen(pv, "Sibling")
    svg_path = _write_svg(pv)

    commands.from_svg(pv, svg_path, "", "", None, "", True, "Made")
    path = os.path.join(pv, "Made.xml")
    first_guid = commands._read_screen_guid(path)

    # One rect fewer, so a stale screen would show up as the wrong count.
    _write_svg(pv, SAMPLE_SVG.replace(
        '  <rect x="10" y="70" width="120" height="40" data-cds-type="rectangle"\n'
        '        fill="#0078d4"/>\n',
        "",
    ))
    commands.from_svg(pv, svg_path, "", "", None, "", True, "Made", replace=True)

    with open(path, "r", encoding="utf-8") as handle:
        assert len(screen_xml.list_elements(handle.read())) == 1
    assert commands._read_screen_guid(path) == first_guid
    assert first_guid

