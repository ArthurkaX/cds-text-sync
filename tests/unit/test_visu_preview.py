# -*- coding: utf-8 -*-
"""
test_visu_preview.py -- Tests for the resolved-colour preview renderer.

The preview exists so that a screen can be *seen* before it reaches the IDE.
Its one hard requirement is fidelity: it must not become a second, drifting
opinion about where an element sits or what colour it is. These tests pin that
requirement -- geometry and colour come from the same resolution path the
compiler uses, and every element type the catalog knows renders without
raising.
"""

import os
import sys
import xml.etree.ElementTree as ET

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import catalog, preview, style_roles, svg_import, themes


def _svg(body, width=800, height=480):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}">'
        "{2}</svg>".format(width, height, body)
    )


def _render(body, **kwargs):
    parsed = svg_import.parse_svg(_svg(body), **kwargs)
    return preview.render(parsed), parsed


def _root(markup):
    return ET.fromstring(markup)


# ---------------------------------------------------------------------------
# uint <-> rgba
# ---------------------------------------------------------------------------


def test_uint_to_rgba_splits_alpha_from_colour():
    assert preview.uint_to_rgba(str(0xFF3F9142)) == ("#3F9142", 1.0)
    assert preview.uint_to_rgba(str(0x00000000)) == ("#000000", 0.0)


def test_uint_to_rgba_tolerates_missing_and_junk_values():
    """Native controls come back with ``None`` fills; junk must not crash a preview."""
    assert preview.uint_to_rgba(None) == (None, 0.0)
    assert preview.uint_to_rgba("") == (None, 0.0)
    assert preview.uint_to_rgba("not-a-number") == (None, 0.0)


# ---------------------------------------------------------------------------
# Document shape
# ---------------------------------------------------------------------------


def test_render_is_well_formed_and_sized_to_the_canvas():
    markup, _ = _render('<rect class="panel" x="24" y="88" width="368" height="296"/>')
    root = _root(markup)
    assert root.get("width") == "800"
    assert root.get("height") == "480"
    assert root.get("viewBox") == "0 0 800 480"


def test_first_node_is_a_full_canvas_background_from_the_palette():
    """The sketch never paints its own background, so the preview has to.

    Without this the preview would show panels floating on viewer-white and
    hide exactly the contrast problem it exists to reveal.
    """
    markup, _ = _render('<rect class="panel" x="24" y="88" width="368" height="296"/>')
    first = list(_root(markup))[0]
    assert first.tag.endswith("rect")
    assert (first.get("width"), first.get("height")) == ("800", "480")
    assert first.get("fill") == style_roles.role_palette(None)["screen"]


def test_text_content_is_escaped():
    markup, _ = _render('<text class="label" x="24" y="100">A &amp; B &lt;raw&gt;</text>')
    assert "A & B <raw>" in [node.text for node in _root(markup).iter() if node.text]


def test_grid_overlay_is_opt_in():
    parsed = svg_import.parse_svg(_svg('<rect x="24" y="88" width="16" height="16"/>'))
    assert "stroke-opacity" not in preview.render(parsed)
    gridded = preview.render(parsed, grid=8)
    lines = [n for n in _root(gridded).iter() if n.tag.endswith("line")]
    assert len(lines) == 800 // 8 + 480 // 8


# ---------------------------------------------------------------------------
# Fidelity: the preview must agree with the compiler
# ---------------------------------------------------------------------------


def test_label_is_drawn_back_on_the_baseline_the_author_wrote():
    """The round trip baseline -> box top -> baseline has to be lossless.

    ``parse_svg`` converts an SVG baseline into a CODESYS top-left box; the
    preview converts it back. If the two ever disagree, every preview would be
    a font-size off vertically and the layout it shows would be a fiction.
    """
    markup, parsed = _render('<text class="label" x="24" y="100">Speed</text>')
    assert int(parsed["elements"][0]["params"]["y"]) == 88  # 100 - 12px font
    text = [n for n in _root(markup).iter() if n.tag.endswith("text")][0]
    assert float(text.get("y")) == 100.0


def test_a_label_is_drawn_at_the_x_the_author_wrote():
    """Horizontally too: ``x="24"`` must put glyphs at 24, not near it.

    The preview used to inset every left-aligned text by 2px, borrowing the gap
    a native field keeps inside its frame. A plain label has no frame, so the
    only thing the inset did was make a label look misaligned against the card
    edge it was lined up with -- in the one view an author uses to check
    alignment.
    """
    markup, _ = _render('<text class="label" x="24" y="100">Speed</text>')
    text = [n for n in _root(markup).iter() if n.tag.endswith("text")][0]
    assert float(text.get("x")) == 24.0


def test_a_field_keeps_the_gap_inside_its_frame():
    """A textfield does have a frame, and CODESYS does not print on it."""
    markup, _ = _render(
        '<text data-cds-type="textfield" x="24" y="100" data-width="120"'
        ' data-height="24" data-text-var="GVL.Speed">%d</text>'
    )
    text = [n for n in _root(markup).iter() if n.tag.endswith("text")][0]
    assert float(text.get("x")) == 26.0


def test_a_sizeless_field_falls_back_to_the_documented_estimate():
    """Not to 100x100, which is a box nobody asked for.

    The flat default made a field taller than the card holding it, so the lint
    reported an overlap the author had not drawn -- and the compiled control
    really was 100px tall in the IDE. The estimate a plain <text> gets is the
    documented fallback, so it is the one a field should get too.
    """
    _markup, parsed = _render(
        '<text data-cds-type="textfield" x="24" y="100" font-size="16"'
        ' data-text-var="GVL.Speed">%d</text>'
    )
    params = parsed["elements"][0]["params"]
    assert int(params["height"]) == int(svg_import._estimate_text_height(16))
    assert int(params["width"]) == svg_import._estimate_text_width("%d", 16)


def test_class_colour_reaches_the_preview_unchanged():
    markup, _ = _render('<rect class="ok" x="40" y="144" width="16" height="16"/>')
    shape = list(_root(markup))[1]
    assert shape.get("fill") == style_roles.role_palette(None)["success"]


def test_native_control_gets_a_concrete_colour_the_style_would_paint():
    """The compiler leaves a button's fill unset so CODESYS owns it at runtime.

    A preview that honoured that literally would draw an invisible button. It
    samples the role the style anchor points at instead -- so the assertion is
    that *something concrete* is painted, not that we know the style's answer.
    """
    parsed = svg_import.parse_svg(
        _svg(
            '<rect data-cds-type="button" x="24" y="408" width="160" height="48"'
            ' data-text="Start" data-cds-tap="TAP HMI.Start"/>'
        )
    )
    fill, fill_a, frame, _frame_a, font = preview._resolved_colors(
        parsed["elements"][0], parsed["theme"]
    )
    for value in (fill, frame, font):
        assert value and value.startswith("#") and len(value) == 7
    assert fill_a == 1.0
    assert 'fill="none"' not in preview.render(parsed).split("\n")[2]


def test_lamp_colour_follows_its_style_role():
    red, _ = _render(
        '<rect data-cds-type="lamp" x="40" y="144" width="20" height="20"'
        ' data-color="red" data-var="HMI.Fault"/>'
    )
    green, _ = _render(
        '<rect data-cds-type="lamp" x="40" y="144" width="20" height="20"'
        ' data-color="green" data-var="HMI.Run"/>'
    )
    red_circle = [n for n in _root(red).iter() if n.tag.endswith("circle")][0]
    green_circle = [n for n in _root(green).iter() if n.tag.endswith("circle")][0]
    assert red_circle.get("fill") != green_circle.get("fill")
    assert red_circle.get("fill") == preview._LAMP_HEX["Element-Lamp-Lamp1-Red"]


def test_theme_choice_changes_native_controls_but_not_curated_shapes():
    """Switching styles must move exactly the things CODESYS owns, and nothing else.

    A button borrows ``primary`` from the visual style, so it re-colours with
    the project. A plain ``<rect>`` lands on ``custom.fill``/``custom.frame``,
    which we curate so that an unclassed shape matches ``panel``/``divider`` --
    letting a style move one and not the other is what painted two shapes of
    identical intent differently. Same preview code, opposite expectations.
    """
    body = (
        '<rect x="24" y="88" width="368" height="296"/>'
        '<rect data-cds-type="button" x="24" y="408" width="160" height="48"'
        ' data-text="Go" data-cds-tap="TAP HMI.Go"/>'
    )

    def _fills(style):
        parsed = svg_import.parse_svg(_svg(body), theme=themes.load_theme(style))
        shapes = [n for n in _root(preview.render(parsed)) if n.tag.endswith("rect")]
        return shapes[1].get("fill"), shapes[2].get("fill")  # [0] is the background

    white_shape, white_button = _fills("white-style")
    basic_shape, basic_button = _fills("basic-style")

    assert white_shape == basic_shape == style_roles.role_palette(None)["panel"]
    assert white_button != basic_button


# ---------------------------------------------------------------------------
# Coverage of the whole catalog
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("type_name", sorted(catalog.list_types()))
def test_every_catalog_type_renders_without_raising(type_name):
    """A type added to the catalog must not be able to break the preview.

    Types without a bespoke branch fall through to a labelled placeholder,
    which is honest about "a native control goes here" -- an exception during
    preview, on the other hand, would block a compile that would have worked.
    """
    spec = {
        "type": type_name,
        "params": {"x": 24, "y": 88, "width": 160, "height": 48, "text": "x"},
    }
    markup = preview.render(
        {"canvas": {"width": 800, "height": 480}, "elements": [spec]},
        themes.load_theme("flat-style"),
    )
    _root(markup)  # raises if the branch emitted malformed markup


# ---------------------------------------------------------------------------
# Rasterisation
# ---------------------------------------------------------------------------


def test_find_browser_returns_an_existing_file_or_none():
    """No browser is a normal outcome, not a failure -- the SVG is still written."""
    found = preview.find_browser()
    assert found is None or os.path.isfile(found) or os.path.basename(found) != found


def test_rasterize_returns_none_when_no_browser_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "find_browser", lambda: None)
    svg_path = tmp_path / "s.svg"
    svg_path.write_text(_svg(""), encoding="utf-8")
    assert preview.rasterize(str(svg_path), str(tmp_path / "s.png"), 800, 480) is None
