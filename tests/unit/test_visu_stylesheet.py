# -*- coding: utf-8 -*-
"""
test_visu_stylesheet.py -- Tests for the semantic class stylesheet.

Verify that ``class="..."`` on an SVG element expands into themed colours via
the bundled stylesheet, that explicit colours still override a class, and that
interactive controls (button/textfield) ignore classes.
"""

import os
import re
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_text_sync.visu import stylesheet, svg_import, themes


def test_parse_stylesheet_keeps_only_allowed_props():
    rules = stylesheet.parse_stylesheet(
        ".a { fill: var(--panel); font-size: 20; color: red; }"
    )
    assert rules["a"] == {"fill": "var(--panel)", "font-size": "20"}


def test_bundled_stylesheet_has_core_classes():
    sheet = stylesheet.load_stylesheet()
    for name in ("panel", "title", "value", "divider", "ok", "warn", "alarm"):
        assert name in sheet, name


def test_class_expands_to_themed_fill():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<rect class="panel" x="0" y="0" width="50" height="50"/></svg>'
    )
    rect = svg_import.parse_svg(svg)["elements"][0]
    # panel -> var(--panel) -> resolved to a concrete unsigned colour int string.
    assert rect["params"]["fill"] is not None
    assert rect["params"]["fill"].isdigit()


def test_class_sets_label_font_color_and_size():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<text class="value" x="10" y="20">42</text></svg>'
    )
    label = svg_import.parse_svg(svg)["elements"][0]
    assert label["params"]["font_color"] is not None
    assert label["params"]["font_size"] == "28"


def test_explicit_fill_overrides_class():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<rect class="panel" fill="#123456" x="0" y="0" width="50" height="50"/>'
        "</svg>"
    )
    rect = svg_import.parse_svg(svg)["elements"][0]
    # #123456 opaque -> 0xFF123456
    assert rect["params"]["fill"] == str(0xFF123456)


def test_button_and_textfield_ignore_class():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<rect data-cds-type="button" class="alarm" x="0" y="0" '
        'width="80" height="30" data-text="Go"/></svg>'
    )
    button = svg_import.parse_svg(svg)["elements"][0]
    assert button["type"] == "button"
    # A class on a native control must not inject a fill/frame override.
    assert button["params"].get("fill") is None
    assert button["params"].get("frame") is None


def test_every_role_the_stylesheet_names_resolves_in_every_theme():
    """A class must never resolve to nothing, in any style the user can pick.

    ``svg_import.parse_svg`` layers the curated palette *under* the theme, so a
    role missing from a theme still works there and the hole stays invisible.
    ``builder`` resolves straight out of a theme dict for ``cts visu add`` --
    with nothing underneath, the same hole is a ThemeError. ``--text-bright``
    was exactly that: absent from all twelve presets, and reachable only
    through the one path that could not see it.
    """
    roles = set()
    for props in stylesheet.load_stylesheet().values():
        for value in props.values():
            roles.update(re.findall(r"var\(--([^)]+)\)", value))
    assert roles, "stylesheet declared no themed colours"

    missing = []
    for name in themes.list_themes():
        colors = themes.load_theme(name)
        for role in sorted(roles):
            try:
                themes.resolve_color("var(--{0})".format(role), colors)
            except themes.ThemeError:
                missing.append("{0}: --{1}".format(name, role))
    assert missing == []
