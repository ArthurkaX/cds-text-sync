# -*- coding: utf-8 -*-
"""
test_visu_scheme.py -- Tests for the light/dark colour scheme.

An author never writes a colour: they write ``class="panel"`` and the palette
decides. That makes a second scheme almost free -- and it makes the failure mode
silent, because nothing in a sketch says whether the result is readable. A dark
panel painted from the dark palette with text sampled from a light CODESYS style
compiles cleanly, imports cleanly, and is white-on-white on the plant floor.

So these tests pin the two things that keep it honest:

* **contrast** -- every text role clears a minimum ratio against the surface it
  actually sits on, in *both* schemes. This is the rule that would have caught
  white-on-white before it reached the IDE.
* **ownership** -- in dark the palette is authoritative, so no shipped style can
  drag a light ``text`` back in, and light is unchanged from what it was before
  the scheme existed.
"""

import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_text_sync.visu import (  # noqa: E402
    builder,
    catalog,
    commands,
    preview,
    style_roles,
    svg_export,
    svg_import,
    themes,
)


def _svg(body="", width=800, height=480, scheme_attr=""):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}"{2}>'
        "{3}</svg>".format(width, height, scheme_attr, body)
    )


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


def _luminance(hex_color):
    """WCAG relative luminance of a ``#RRGGBB`` string."""
    raw = hex_color.lstrip("#")[:6]
    channels = []
    for i in (0, 2, 4):
        c = int(raw[i : i + 2], 16) / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    """WCAG contrast ratio between two ``#RRGGBB`` strings (1.0 .. 21.0)."""
    a, b = _luminance(fg), _luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_helper_matches_known_wcag_values():
    """Guard the guard: a broken ratio would make every case below pass."""
    assert _contrast("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert _contrast("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, abs=0.01)
    assert _contrast("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.05)


# (text role, the surface it is actually drawn on). Each pairing is one the
# compiler can really produce -- a label on a panel, a field's value inside the
# field box, a button caption on the button.
_TEXT_ON_SURFACE = [
    ("text", "screen"),
    ("text", "panel"),
    ("text", "card"),
    ("text.muted", "panel"),
    ("text.muted", "card"),
    ("panel.header.text", "panel.header"),
    ("custom.text", "custom.fill"),
    ("field.text", "field.fill"),
    ("button.text", "button.fill"),
]

# 4.5:1 is the WCAG AA threshold for body text. HMI screens are read at a
# distance, under plant lighting, by someone who is not looking for subtlety --
# so this is a floor, not a target.
_MIN_TEXT_CONTRAST = 4.5


@pytest.mark.parametrize("scheme", style_roles.SCHEMES)
@pytest.mark.parametrize("fg_role,bg_role", _TEXT_ON_SURFACE)
def test_text_roles_are_readable_on_their_surface(scheme, fg_role, bg_role):
    palette = style_roles.role_palette(None, scheme)
    fg, bg = palette[fg_role], palette[bg_role]
    ratio = _contrast(fg, bg)
    assert ratio >= _MIN_TEXT_CONTRAST, (
        "{0} scheme: {1} ({2}) on {3} ({4}) is only {5:.2f}:1".format(
            scheme, fg_role, fg, bg_role, bg, ratio
        )
    )


# A status colour has to be *distinguishable* rather than readable -- it is a
# fill, not body text -- so it clears a lower bar against the surface behind it.
_MIN_STATUS_CONTRAST = 2.5


@pytest.mark.parametrize("scheme", style_roles.SCHEMES)
@pytest.mark.parametrize("role", ["success", "warning", "error", "alarm.fill"])
def test_status_colours_stand_out_from_the_panel(scheme, role):
    palette = style_roles.role_palette(None, scheme)
    ratio = _contrast(palette[role], palette["panel"])
    assert ratio >= _MIN_STATUS_CONTRAST, (
        "{0} scheme: {1} ({2}) on panel ({3}) is only {4:.2f}:1".format(
            scheme, role, palette[role], palette["panel"], ratio
        )
    )


@pytest.mark.parametrize("scheme", style_roles.SCHEMES)
def test_surfaces_are_distinguishable_from_each_other(scheme):
    """screen / panel / card must read as three layers, not one flat field."""
    palette = style_roles.role_palette(None, scheme)
    assert palette["screen"] != palette["panel"]
    assert palette["panel"] != palette["card"]


# ---------------------------------------------------------------------------
# Scheme resolution
# ---------------------------------------------------------------------------


def test_default_scheme_is_light():
    assert svg_import.parse_svg(_svg())["scheme"] == "light"


def test_attribute_selects_the_scheme():
    parsed = svg_import.parse_svg(_svg(scheme_attr=' data-cds-scheme="dark"'))
    assert parsed["scheme"] == "dark"


def test_explicit_argument_beats_the_attribute():
    """``--scheme`` is a one-off override, so it wins over the sketch."""
    dark_sketch = _svg(scheme_attr=' data-cds-scheme="dark"')
    assert svg_import.parse_svg(dark_sketch, scheme="light")["scheme"] == "light"
    assert svg_import.parse_svg(_svg(), scheme="dark")["scheme"] == "dark"


def test_unknown_scheme_falls_back_to_light():
    """A typo must not produce a half-painted screen."""
    assert svg_import.parse_svg(_svg(), scheme="drak")["scheme"] == "light"
    assert svg_import.parse_svg(_svg(scheme_attr=' data-cds-scheme="pink"'))[
        "scheme"
    ] == "light"


def test_read_scheme_agrees_with_parse_svg():
    """The pre-parse helper exists only to answer this earlier -- not differently."""
    for attr, override in (
        ("", None),
        (' data-cds-scheme="dark"', None),
        (' data-cds-scheme="dark"', "light"),
        ("", "dark"),
        ("", "nonsense"),
    ):
        text = _svg(scheme_attr=attr)
        assert svg_import.read_scheme(text, override) == svg_import.parse_svg(
            text, scheme=override
        )["scheme"]


def test_read_scheme_does_not_raise_on_a_malformed_sketch():
    """Reporting the parse error is parse_svg's job; doing it twice buries it."""
    assert svg_import.read_scheme("<svg not xml") == "light"
    assert svg_import.read_scheme("<svg not xml", "dark") == "dark"


def test_inline_root_vars_still_win_over_the_dark_palette():
    """The per-sketch escape hatch outranks the scheme, in either direction."""
    body = "<defs><style>:root{--panel:#ABCDEF;}</style></defs>"
    parsed = svg_import.parse_svg(_svg(body), scheme="dark")
    assert parsed["theme"]["panel"] == "#ABCDEF"


# ---------------------------------------------------------------------------
# Ownership: what the palette curates, and what the CODESYS style keeps
# ---------------------------------------------------------------------------


def test_light_curated_set_is_unchanged():
    assert style_roles.curated_roles("light") == style_roles.CURATED_ROLES


def test_dark_curates_a_superset_of_light():
    dark = style_roles.curated_roles("dark")
    assert style_roles.CURATED_ROLES <= dark
    # The roles the light scheme deliberately leaves to CODESYS -- and which a
    # light style therefore cannot be allowed to own on a dark screen.
    for role in ("text", "text.muted", "field.fill", "field.text", "button.fill"):
        assert role in dark
        assert role not in style_roles.curated_roles("light")


@pytest.mark.parametrize("name", themes.list_themes())
def test_every_preset_returns_the_dark_palette_in_dark(name):
    """Every shipped style is light, so none of them may leak into dark."""
    colors = themes.load_theme(name, "dark")
    dark_palette = style_roles.role_palette(None, "dark")
    for role in style_roles.curated_roles("dark"):
        if role in dark_palette:
            assert colors[role] == dark_palette[role], role


@pytest.mark.parametrize("name", themes.list_themes())
def test_light_presets_still_defer_to_the_style_for_its_own_roles(name):
    """The two new roles must not quietly override a real style colour.

    ``field.text`` and ``button.fill`` are newer than every style snapshot, so
    nothing names them. Left to their literal fallback they would ignore the
    project style -- a black caption silently becoming #1F1F1F. They are derived
    from the role each one refines instead, which is what this pins.
    """
    colors = themes.load_theme(name, "light")
    assert colors["field.text"] == colors["text"]
    assert colors["button.fill"] == colors["primary"]


# Roles a theme dict carries that no sketch can name: they are not in
# ``_ROLE_DEFS``, no stylesheet class maps to them, and only some presets define
# them at all (the four with a sampled ``themes/*.json`` snapshot do not). They
# still differ between styles in dark, and that is allowed -- nothing paints
# from them. ``background`` in particular is unreachable even through
# ``--background style``, which tries the curated ``surface`` first.
_NON_AUTHORING_ROLES = frozenset(
    ["background", "custom.accent.fill", "custom.accent.text"]
)


@pytest.mark.parametrize("name", themes.list_themes())
def test_dark_output_does_not_depend_on_the_chosen_style(name):
    """Two different styles must paint the same dark screen.

    Compared over the authoring vocabulary rather than the raw dict -- see
    ``_NON_AUTHORING_ROLES`` for what is excluded and why.
    """
    mine = themes.load_theme(name, "dark")
    reference = themes.load_theme("flat-style", "dark")
    for role in style_roles.roles():
        assert mine[role] == reference[role], "{0}: {1}".format(name, role)


@pytest.mark.parametrize("name", themes.list_themes())
def test_nothing_paintable_escapes_the_dark_palette(name):
    """Guard the narrowing above: the exclusion list must not quietly grow.

    A role added to a style preset but not to ``_ROLE_DEFS`` would be invisible
    to the test above while still resolving through ``var(--role)``. Pin the
    exact set instead, so adding one is a decision rather than an accident.
    """
    mine = themes.load_theme(name, "dark")
    reference = themes.load_theme("flat-style", "dark")
    differing = {
        role
        for role in set(mine) | set(reference)
        if mine.get(role) != reference.get(role)
    }
    assert differing <= _NON_AUTHORING_ROLES, "{0}: {1}".format(
        name, sorted(differing - _NON_AUTHORING_ROLES)
    )


def test_lamp_colours_are_the_same_in_both_schemes():
    """An indicator that changed meaning with the scheme is a safety problem."""
    assert "lamp" not in " ".join(style_roles.curated_roles("dark"))
    light = svg_import.parse_svg(
        _svg('<rect data-cds-type="lamp" x="8" y="8" width="16" height="16" '
             'data-lamp-color="green" data-var="PLC.ok"/>')
    )
    dark = svg_import.parse_svg(
        _svg('<rect data-cds-type="lamp" x="8" y="8" width="16" height="16" '
             'data-lamp-color="green" data-var="PLC.ok"/>'),
        scheme="dark",
    )
    assert (
        light["elements"][0]["params"]["style_role"]
        == dark["elements"][0]["params"]["style_role"]
    )


# ---------------------------------------------------------------------------
# What the compiler emits
# ---------------------------------------------------------------------------

_TEXTFIELD = (
    '<text data-cds-type="textfield" x="40" y="60" data-width="200" '
    'data-height="24" data-text-var="PLC.speed">%3.1f</text>'
)
_BUTTON = (
    '<rect data-cds-type="button" x="40" y="120" width="120" height="40" '
    'data-text="Start" data-cds-tap="PLC.start"/>'
)
_LABEL = '<text class="h2" x="40" y="200">Process</text>'


def _compile_one(body, scheme):
    """Append a single element to a screen and return the emitted XML."""
    parsed = svg_import.parse_svg(_svg(body), scheme=scheme)
    spec = parsed["elements"][0]
    xml_text = builder.build_screen(
        name="T",
        size_x=800,
        size_y=480,
        parent_guid="11111111-1111-1111-1111-111111111111",
        parent_svnode_guid="22222222-2222-2222-2222-222222222222",
        path_segments=["HMI"],
        is_start_visu=False,
    )
    params = dict(spec["params"])
    if params.get("text") and not params.get("text_id"):
        params["text_id"] = "1000"
    out, _geom, _info = builder.append_element(
        xml_text,
        catalog.load_catalog(spec["type"]),
        params,
        theme_colors=parsed["theme"],
        scheme=parsed["scheme"],
    )
    return out


def _uint_for_member(xml_text, member_id):
    """The short-form literal written for *member_id*, or ``None`` if absent."""
    import re

    m = re.search(
        r'<Single Name="Id" Type="long">{0}</Single>\s*'
        r'<Single Name="Value" Type="uint">(\d+)</Single>'.format(member_id),
        xml_text,
    )
    return int(m.group(1)) if m else None


def _hex_to_uint(hex_color):
    return int(hex_color.lstrip("#"), 16) | 0xFF000000


def _member(type_name, slot):
    """The member id a catalog uses for its ``fill``/``frame`` colour.

    Asked of the catalog rather than hard-coded, because button and textfield
    happen to share both ids (a member id is a hash of the property path, and
    the path is the same for the two control types). A shared constant here
    would let the button case keep passing while testing the textfield's
    member, or the reverse.
    """
    return catalog.load_catalog(type_name)["themeable_colors"][slot]["member_id"]


def test_light_textfield_keeps_the_style_linked_struct():
    """A struct with a CanonicalName is the encoding CODESYS resolves from the
    project style. Light wants exactly that: the control matches the IDE."""
    out = _compile_one(_TEXTFIELD, "light")
    assert "Element-Fill-Color" in out
    assert "Element-Frame-Color" in out
    assert _uint_for_member(out, _member("textfield", "fill")) is None


def test_dark_textfield_overrides_the_style_with_a_literal():
    """The short form is the only encoding that beats the style -- the literal
    beside a CanonicalName is ignored, and blanking the name crashes the build."""
    out = _compile_one(_TEXTFIELD, "dark")
    palette = style_roles.role_palette(None, "dark")
    assert "Element-Fill-Color" not in out
    assert _uint_for_member(out, _member("textfield", "fill")) == _hex_to_uint(
        palette["field.fill"]
    )
    assert _uint_for_member(out, _member("textfield", "frame")) == _hex_to_uint(
        palette["field.frame"]
    )


def test_a_member_id_appears_only_once_after_the_swap():
    """The short form *replaces* the struct; two entries for one id is invalid."""
    out = _compile_one(_TEXTFIELD, "dark")
    marker = '<Single Name="Id" Type="long">{0}</Single>'.format(
        _member("textfield", "fill")
    )
    assert out.count(marker) == 1


def test_light_button_defers_to_the_style():
    out = _compile_one(_BUTTON, "light")
    assert _uint_for_member(out, _member("button", "fill")) is None


def test_dark_button_is_a_dark_surface_not_the_accent():
    """A button painted with the brightened dark accent shouts; it is a surface."""
    out = _compile_one(_BUTTON, "dark")
    palette = style_roles.role_palette(None, "dark")
    assert _uint_for_member(out, _member("button", "fill")) == _hex_to_uint(
        palette["button.fill"]
    )
    assert palette["button.fill"] != palette["accent"]


# ---------------------------------------------------------------------------
# Font colour
#
# A font colour is written in three places per element, and only one of them
# decides what is drawn. A probe screen carrying all four combinations was
# imported into a live IDE: the label stayed the style's black until the font
# descriptor's ``NamedColor`` link was nulled, and switching the colour member
# (663104332) to the short form changed nothing at all. These tests pin that
# result -- the light case is not a formality, it is the reason the defect went
# unnoticed, since a curated light ``text`` and the style's black look alike.
# ---------------------------------------------------------------------------


def _font_descriptor(xml_text):
    """The element's own font descriptor member (3729828405)."""
    import re

    m = re.search(
        r'<Single Name="Id" Type="long">3729828405</Single>.*?</List>',
        xml_text,
        re.DOTALL,
    )
    assert m, "element carries no font descriptor"
    return m.group(0)


def _explicit_color(descriptor):
    import re

    m = re.search(
        r'<Single Name="ExplicitColor" Type="int">(-?\d+)</Single>', descriptor
    )
    return int(m.group(1)) & 0xFFFFFFFF if m else None


def test_light_font_stays_linked_to_the_style():
    """Light curates surfaces but leaves text to the style, so a generated
    screen keeps following the project's own visual style."""
    descriptor = _font_descriptor(_compile_one(_LABEL, "light"))
    assert "Font-Default-Color" in descriptor
    assert '<Null Name="NamedColor" />' not in descriptor


def test_dark_font_is_unlinked_so_the_literal_wins():
    """While ``NamedColor`` points at Font-Default-Color the ExplicitColor
    beside it is ignored -- and every shipped CODESYS style paints it black."""
    descriptor = _font_descriptor(_compile_one(_LABEL, "dark"))
    palette = style_roles.role_palette(None, "dark")
    assert '<Null Name="NamedColor" />' in descriptor
    assert "Font-Default-Color" not in descriptor
    assert _explicit_color(descriptor) == _hex_to_uint(palette["text"])


def test_dark_button_text_is_not_the_template_black():
    """The button template hard-codes a black ExplicitColor, so unlinking alone
    would swap unreadable-black-on-dark for unreadable-black-on-dark."""
    descriptor = _font_descriptor(_compile_one(_BUTTON, "dark"))
    palette = style_roles.role_palette(None, "dark")
    assert _explicit_color(descriptor) == _hex_to_uint(palette["button.text"])


def test_light_button_text_is_byte_identical_to_the_old_fallback():
    """Naming the role must not disturb light: ``button.text`` is the opaque
    white the builder already fell back to when no font colour was resolved."""
    descriptor = _font_descriptor(_compile_one(_BUTTON, "light"))
    assert "Font-Default-Color" in descriptor
    assert style_roles.role_palette(None, "light")["button.text"] == "#FFFFFF"


def test_dark_textfield_text_tracks_the_field_not_the_panel():
    descriptor = _font_descriptor(_compile_one(_TEXTFIELD, "dark"))
    palette = style_roles.role_palette(None, "dark")
    assert '<Null Name="NamedColor" />' in descriptor
    assert _explicit_color(descriptor) == _hex_to_uint(palette["field.text"])


# ---------------------------------------------------------------------------
# Preview and skeleton
# ---------------------------------------------------------------------------


def test_preview_paints_a_dark_background():
    parsed = svg_import.parse_svg(_svg(), scheme="dark")
    markup = preview.render(parsed)
    assert style_roles.role_palette(None, "dark")["screen"] in markup


def test_preview_grid_is_visible_on_a_dark_screen():
    """A black hairline on #10141A reads as '--grid is broken'."""
    dark = preview.render(svg_import.parse_svg(_svg(), scheme="dark"), grid=8)
    light = preview.render(svg_import.parse_svg(_svg()), grid=8)
    assert 'stroke="#FFFFFF" stroke-opacity="0.06"' in dark
    assert 'stroke="#000000" stroke-opacity="0.06"' in light


def test_preview_follows_the_sketch_without_being_told():
    """render() takes its scheme from the parse result, so the two cannot drift."""
    parsed = svg_import.parse_svg(_svg(scheme_attr=' data-cds-scheme="dark"'))
    assert style_roles.role_palette(None, "dark")["screen"] in preview.render(parsed)


def test_skeleton_records_a_dark_scheme_and_stays_lint_clean():
    from cds_text_sync.visu import lint as _lint

    text = commands.compose_skeleton(800, 480, "Demo", "dark")
    assert 'data-cds-scheme="dark"' in text
    findings, parsed = _lint.lint_svg(text)
    assert parsed["scheme"] == "dark"
    assert [f for f in findings if f.severity == "error"] == []


def test_light_skeleton_carries_no_scheme_attribute():
    """Light is the default; stamping it everywhere is noise to keep in sync."""
    for scheme in (None, "light"):
        assert "data-cds-scheme" not in commands.compose_skeleton(
            800, 480, "Demo", scheme
        )


# ---------------------------------------------------------------------------
# Decompile: the scheme survives the round trip
# ---------------------------------------------------------------------------
#
# A compiled screen does not record which scheme produced it -- the two differ
# only in the colours they resolved to. Without recovering it, `to-svg` handed
# back a sketch with no attribute, and recompiling that sketch repainted a dark
# screen light.


def _compiled_screen(scheme):
    """A screen XML compiled in *scheme*, background and all."""
    parsed = svg_import.parse_svg(_svg(_LABEL), scheme=scheme)
    return builder.build_screen(
        name="T",
        size_x=800,
        size_y=480,
        parent_guid="11111111-1111-1111-1111-111111111111",
        parent_svnode_guid="22222222-2222-2222-2222-222222222222",
        path_segments=["HMI"],
        is_start_visu=False,
        bg_color=parsed["bg_color"],
    )


def test_decompiled_dark_screen_is_stamped_dark():
    assert 'data-cds-scheme="dark"' in svg_export.screen_to_svg(
        _compiled_screen("dark")
    )


def test_decompiled_light_screen_carries_no_attribute():
    assert "data-cds-scheme" not in svg_export.screen_to_svg(_compiled_screen("light"))


def test_scheme_survives_compile_then_decompile():
    """The whole point: to-svg output re-reads as the scheme it came from."""
    for scheme in ("light", "dark"):
        sketch = svg_export.screen_to_svg(_compiled_screen(scheme))
        assert svg_import.read_scheme(sketch) == scheme


def test_decompiled_dark_sketch_carries_the_dark_palette():
    """A dark stamp over light ``:root`` vars would contradict itself."""
    markup = svg_export.screen_to_svg(_compiled_screen("dark"))
    assert "--surface:{0}".format(style_roles.role_palette(None, "dark")["surface"]) in (
        markup
    )


def test_explicit_scheme_beats_the_inferred_one():
    light_screen = _compiled_screen("light")
    assert 'data-cds-scheme="dark"' in svg_export.screen_to_svg(
        light_screen, scheme="dark"
    )
    assert "data-cds-scheme" not in svg_export.screen_to_svg(
        _compiled_screen("dark"), scheme="light"
    )


@pytest.mark.parametrize(
    "bg,expected",
    [
        (None, "light"),  # BgColor=False -- same fallback as a bare sketch
        ("", "light"),
        ("#F4F5F7", "light"),
        ("#10141A", "dark"),
        ("#000000", "dark"),
        ("#FFFFFF", "light"),
        ("nonsense", "light"),
        ("#12345", "light"),  # malformed: guess rather than raise
    ],
)
def test_scheme_inference_from_background(bg, expected):
    assert svg_export._infer_scheme(bg) == expected
