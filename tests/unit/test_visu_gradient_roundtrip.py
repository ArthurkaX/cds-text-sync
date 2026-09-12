# -*- coding: utf-8 -*-
"""
test_visu_gradient_roundtrip.py -- Gradient fills survive SVG -> XML -> SVG.

A gradient is the one fill that lives in a *list* member rather than a scalar:
``m_bUseGradient`` (1375557818) plus ``m_GradientData`` (494542316), a 9-slot
positional ArrayList. Two things about that shape have already gone wrong once
each, so both are pinned here:

* **Encoding.** Colour slots must be plain ``<Single Type="uint">`` scalars. The
  named-style colour struct crashes CODESYS's property view, which casts every
  slot to ``INamedStyleColor`` -- and a whole screen shipped in that broken form
  before this was understood.
* **Decompilation.** ``svg_export`` had no gradient handling at all, so
  ``to-svg`` silently flattened every gradient to its (stale, style-linked)
  solid fill member. A ``to-svg`` / ``from-svg`` round trip -- the only way to
  edit a screen whose sketch is gone -- therefore destroyed the gradients it
  passed through.

See products/cds-text-sync memory "codesys-visu-gradient-fill" for the slot
tables and the dead ends behind them.
"""

import os
import re
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_text_sync.visu import (  # noqa: E402
    builder,
    catalog,
    svg_export,
    svg_import,
)

_MID_GRADIENT_DATA = 494542316
_MID_USE_GRADIENT = 1375557818

_GRAD_RE = re.compile(
    r'<Single Name="Id" Type="long">{0}</Single>\s*'
    r'<List Name="Value"[^>]*>(.*?)</List>'.format(_MID_GRADIENT_DATA),
    re.S,
)
_SLOT_RE = re.compile(r'<Single Type="(\w+)">([^<]*)</Single>')


def _svg(body, defs=""):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480">'
        "<defs>{0}</defs>{1}</svg>".format(defs, body)
    )


def _compile(svg_text):
    """Compile every element of *svg_text* into one screen XML."""
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


def _gradient_slots(xml_text):
    """Every gradient member in document order, as [(xml_type, text), ...]."""
    return [_SLOT_RE.findall(m.group(1)) for m in _GRAD_RE.finditer(xml_text)]


_LINEAR = _svg(
    '<rect x="10" y="20" width="100" height="50" fill="url(#g)"/>',
    defs=(
        '<linearGradient id="g" x1="50%" y1="0%" x2="50%" y2="100%">'
        '<stop offset="0%" stop-color="#DCE0E5"/>'
        '<stop offset="100%" stop-color="#A9AFB7"/>'
        "</linearGradient>"
    ),
)

_RADIAL = _svg(
    '<circle cx="72" cy="200" r="14" fill="url(#g)"/>',
    defs=(
        '<radialGradient id="g" cx="35%" cy="35%" r="50%">'
        '<stop offset="0%" stop-color="#F2F4F6"/>'
        '<stop offset="100%" stop-color="#5A6067"/>'
        "</radialGradient>"
    ),
)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def test_gradient_slots_are_plain_scalars_not_colour_structs():
    """The struct form is what crashed the property view -- see the module docstring."""
    xml_text = _compile(_LINEAR)
    slots = _gradient_slots(xml_text)
    assert len(slots) == 1
    assert [t for t, _ in slots[0]] == [
        "uint",  # 0 Color1
        "uint",  # 1 Color2
        "int",  # 2 Angle
        "int",  # 3 CenterX
        "int",  # 4 CenterY
        "int",  # 5 Type
        "int",  # 6 unused
        "int",  # 7 unused
        "uint",  # 8 Color1's alpha byte
    ]
    grad_block = _GRAD_RE.search(xml_text).group(1)
    assert "fa491db2-51ff-4bc1-9cd0-ce8c94ff6216" not in grad_block


def test_linear_gradient_fills_the_documented_slots():
    slots = _gradient_slots(_compile(_LINEAR))[0]
    values = [v for _, v in slots]
    # 0/1 colours, 2 angle (top -> bottom is 90 deg), 3/4 centre, 5 linear,
    # 6/7 unused, 8 Color1's alpha byte alone.
    assert values[0] == str(0xFFDCE0E5)
    assert values[1] == str(0xFFA9AFB7)
    assert values[2] == "90"
    assert values[3:6] == ["50", "50", "0"]
    assert values[6:8] == ["0", "0"]
    assert values[8] == str(0xFF000000)


def test_radial_gradient_carries_the_centre_and_type():
    values = [v for _, v in _gradient_slots(_compile(_RADIAL))[0]]
    assert values[3:6] == ["35", "35", "1"]


# ---------------------------------------------------------------------------
# Decompilation
# ---------------------------------------------------------------------------


def test_to_svg_emits_a_gradient_def_instead_of_a_solid_fill():
    out = svg_export.screen_to_svg(_compile(_LINEAR))
    assert "<linearGradient" in out
    assert 'fill="url(#cts-grad-0)"' in out


def test_to_svg_emits_a_radial_def_with_the_centre():
    out = svg_export.screen_to_svg(_compile(_RADIAL))
    assert '<radialGradient id="cts-grad-0" cx="35%" cy="35%"' in out
    assert 'fill="url(#cts-grad-0)"' in out


def test_round_trip_reproduces_every_gradient_slot():
    """to-svg -> from-svg must be an identity on the gradient member."""
    for source in (_LINEAR, _RADIAL):
        first = _compile(source)
        second = _compile(svg_export.screen_to_svg(first))
        assert _gradient_slots(second) == _gradient_slots(first)


def test_axial_survives_the_round_trip_via_the_marker():
    """SVG has no axial construct, so the type rides on a data attribute.

    Without it a round trip would quietly downgrade an axial gradient -- built
    by hand in the IDE, since from-svg never emits one -- to linear.
    """
    original = _compile(_LINEAR)
    block = _GRAD_RE.search(original).group(1)
    slot_tags = _SLOT_RE.findall(block)
    assert slot_tags[5] == ("int", "0")  # the linear type we are about to bend
    patched_block = block.replace(
        '<Single Type="int">0</Single>', '<Single Type="int">2</Single>', 1
    )
    xml_text = original.replace(block, patched_block, 1)
    assert [v for _, v in _gradient_slots(xml_text)[0]][5] == "2"

    svg_text = svg_export.screen_to_svg(xml_text)
    assert 'data-cds-gradient-type="axial"' in svg_text
    assert [v for _, v in _gradient_slots(_compile(svg_text))[0]][5] == "2"


def test_a_translucent_stop_round_trips_through_stop_opacity():
    """An 8-digit stop-color would come back opaque: _apply_opacity overwrites a
    hex alpha with the (defaulted) opacity attribute, so the alpha must leave as
    stop-opacity instead."""
    source = _svg(
        '<rect x="10" y="20" width="100" height="50" fill="url(#g)"/>',
        defs=(
            '<linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="0%">'
            '<stop offset="0%" stop-color="#112233" stop-opacity="0.5"/>'
            '<stop offset="100%" stop-color="#445566"/>'
            "</linearGradient>"
        ),
    )
    first = _compile(source)
    assert [v for _, v in _gradient_slots(first)[0]][0] == str(0x80112233)
    svg_text = svg_export.screen_to_svg(first)
    assert "stop-opacity" in svg_text
    assert _gradient_slots(_compile(svg_text)) == _gradient_slots(first)


def test_an_element_without_a_gradient_keeps_its_solid_fill():
    """The gradient path must not steal the plain fill from everything else."""
    plain = _svg('<rect x="10" y="20" width="100" height="50" fill="#123456"/>')
    out = svg_export.screen_to_svg(_compile(plain))
    assert "Gradient" not in out
    assert 'fill="#123456"' in out


def test_gradient_ids_stay_unique_across_elements():
    source = _svg(
        '<rect x="10" y="20" width="100" height="50" fill="url(#a)"/>'
        '<rect x="10" y="90" width="100" height="50" fill="url(#b)"/>',
        defs=(
            '<linearGradient id="a" x1="0%" y1="0%" x2="0%" y2="100%">'
            '<stop offset="0%" stop-color="#111111"/>'
            '<stop offset="100%" stop-color="#222222"/></linearGradient>'
            '<linearGradient id="b" x1="0%" y1="0%" x2="0%" y2="100%">'
            '<stop offset="0%" stop-color="#333333"/>'
            '<stop offset="100%" stop-color="#444444"/></linearGradient>'
        ),
    )
    out = svg_export.screen_to_svg(_compile(source))
    assert 'fill="url(#cts-grad-0)"' in out
    assert 'fill="url(#cts-grad-1)"' in out
    assert out.count("<linearGradient") == 2
