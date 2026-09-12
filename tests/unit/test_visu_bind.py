# -*- coding: utf-8 -*-
"""
test_visu_bind.py -- `cts visu bind` patches only binding attributes.

`bind_element` is the enforcement mechanism for "drawing" and "wiring
signals" being two separate passes: it must be structurally incapable of
touching geometry, fill, stroke or gradients, only the small set of
``data-*`` binding attributes on the one flagged element. Every test here
diffs the sketch file before/after to prove nothing else moved.
"""

import os
import re
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest  # noqa: E402

from cds_text_sync.visu import builder, catalog, svg_import  # noqa: E402
from cds_text_sync.visu.commands import (  # noqa: E402
    VisuCommandError,
    bind_element,
)


def _write(tmp_path, body, defs=""):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
        "<defs>{0}</defs>{1}</svg>".format(defs, body)
    )
    path = tmp_path / "sketch.svg"
    path.write_text(svg, encoding="utf-8")
    return str(path)


def _compile(svg_text):
    parsed = svg_import.parse_svg(svg_text)
    out = builder.build_screen(
        name="T",
        size_x=parsed["canvas"]["width"],
        size_y=parsed["canvas"]["height"],
        parent_guid="11111111-1111-1111-1111-111111111111",
        parent_svnode_guid="22222222-2222-2222-2222-222222222222",
        path_segments=["HMI"],
        is_start_visu=False,
    )
    for spec in parsed["elements"]:
        params = dict(spec["params"])
        if params.get("text") and not params.get("text_id"):
            params["text_id"] = "1000"
        out, _geom, _info = builder.append_element(
            out,
            catalog.load_catalog(spec["type"]),
            params,
            theme_colors=parsed["theme"],
            scheme=parsed["scheme"],
        )
    return out


# ---------------------------------------------------------------------------
# Binding sets the right attribute, and only that attribute
# ---------------------------------------------------------------------------


def test_bind_var_on_lamp_touches_only_data_var(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20" '
        'fill="#ff0000" stroke="#000000"/>',
    )
    before = open(path, encoding="utf-8").read()

    bind_element(svg_path=path, elem_index=0, var="VisuVars.xRunning")

    after = open(path, encoding="utf-8").read()
    assert 'data-var="VisuVars.xRunning"' in after
    # everything else about the tag is unchanged
    assert 'fill="#ff0000"' in after
    assert 'stroke="#000000"' in after
    assert 'x="40"' in after and 'y="40"' in after and 'width="20"' in after
    # the only diff is the appended attribute
    assert after.replace(' data-var="VisuVars.xRunning"', "") == before


def test_bind_color_on_lamp(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20"/>',
    )
    bind_element(svg_path=path, elem_index=0, color="green")
    after = open(path, encoding="utf-8").read()
    assert 'data-color="green"' in after


def test_bind_text_var_on_textfield(tmp_path):
    path = _write(
        tmp_path,
        '<text data-cds-type="textfield" x="10" y="20" '
        'font-size="16">0.0</text>',
    )
    bind_element(svg_path=path, elem_index=0, text_var="VisuVars.rSpeed")
    after = open(path, encoding="utf-8").read()
    assert 'data-text-var="VisuVars.rSpeed"' in after
    assert ">0.0<" in after  # text content untouched


def test_bind_tap_on_button_uses_tap_prefix(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="button" data-text="Start" '
        'x="0" y="0" width="80" height="30"/>',
    )
    bind_element(svg_path=path, elem_index=0, tap_var="VisuVars.xStart")
    after = open(path, encoding="utf-8").read()
    assert 'data-cds-tap="tap:VisuVars.xStart"' in after


def test_bind_toggle_on_button_uses_toggle_prefix(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="button" data-text="Toggle" '
        'x="0" y="0" width="80" height="30"/>',
    )
    bind_element(svg_path=path, elem_index=0, toggle_var="VisuVars.xEnable")
    after = open(path, encoding="utf-8").read()
    assert 'data-cds-tap="toggle:VisuVars.xEnable"' in after


def test_bind_action_appends_with_double_pipe(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="button" data-text="Go" '
        'data-cds-action="TAP HMI.A" x="0" y="0" width="80" height="30"/>',
    )
    bind_element(svg_path=path, elem_index=0, action="TAP HMI.B")
    after = open(path, encoding="utf-8").read()
    assert 'data-cds-action="TAP HMI.A || TAP HMI.B"' in after


def test_bind_action_on_rectangle(tmp_path):
    path = _write(
        tmp_path, '<rect x="0" y="0" width="80" height="30" fill="#123456"/>'
    )
    bind_element(
        svg_path=path, elem_index=0, action="OnMouseClick: ST HMI.x := TRUE;"
    )
    after = open(path, encoding="utf-8").read()
    assert 'data-cds-action="OnMouseClick: ST HMI.x := TRUE;"' in after


# ---------------------------------------------------------------------------
# Refuses a binding flag the element type does not support
# ---------------------------------------------------------------------------


def test_bind_tap_on_lamp_is_refused(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20"/>',
    )
    before = open(path, encoding="utf-8").read()
    with pytest.raises(VisuCommandError):
        bind_element(svg_path=path, elem_index=0, tap_var="VisuVars.xFoo")
    after = open(path, encoding="utf-8").read()
    assert after == before  # refused before any write


def test_bind_var_on_button_is_refused(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="button" data-text="Go" '
        'x="0" y="0" width="80" height="30"/>',
    )
    with pytest.raises(VisuCommandError):
        bind_element(svg_path=path, elem_index=0, var="VisuVars.xFoo")


def test_bind_with_no_flags_and_no_clear_is_refused(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20"/>',
    )
    with pytest.raises(VisuCommandError):
        bind_element(svg_path=path, elem_index=0)


def test_bind_elem_out_of_range_is_refused(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20"/>',
    )
    with pytest.raises(VisuCommandError):
        bind_element(svg_path=path, elem_index=5, var="VisuVars.xFoo")


# ---------------------------------------------------------------------------
# --clear removes bindings
# ---------------------------------------------------------------------------


def test_bind_clear_removes_all_binding_attributes(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20" '
        'data-var="VisuVars.xRunning" data-color="green" fill="#ff0000"/>',
    )
    bind_element(svg_path=path, elem_index=0, clear=True)
    after = open(path, encoding="utf-8").read()
    assert "data-var" not in after
    assert "data-color" not in after
    assert 'fill="#ff0000"' in after  # geometry/style untouched


# ---------------------------------------------------------------------------
# Bound sketch still compiles, and the binding reaches the XML
# ---------------------------------------------------------------------------


def test_bound_sketch_compiles_and_binding_reaches_xml(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20" '
        'fill="#ff0000"/>',
    )
    bind_element(svg_path=path, elem_index=0, var="VisuVars.xRunning")
    svg_text = open(path, encoding="utf-8").read()
    xml_text = _compile(svg_text)
    assert "xRunning" in xml_text


def test_bind_preserves_element_count(tmp_path):
    path = _write(
        tmp_path,
        '<rect data-cds-type="lamp" x="40" y="40" width="20" height="20"/>'
        '<rect data-cds-type="button" data-text="Go" '
        'x="0" y="0" width="80" height="30"/>',
    )
    bind_element(svg_path=path, elem_index=1, tap_var="VisuVars.xGo")
    after = open(path, encoding="utf-8").read()
    parsed = svg_import.parse_svg(after)
    assert len(parsed["elements"]) == 2
    assert 'data-cds-tap="tap:VisuVars.xGo"' in after
