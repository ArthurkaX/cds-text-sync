# -*- coding: utf-8 -*-
"""
svg_import.py - SVG -> CODESYS parser module.

Parses an SVG string and produces a list of ElementSpec dicts that can be
passed to ``builder.append_element``. Follows the interchange contract in
plan.md section 4 (SVG schema).
"""

from __future__ import print_function

import re
import xml.etree.ElementTree as ET

from . import stylesheet as _stylesheet
from . import style_roles as _style_roles
from . import themes as _themes

# ---------------------------------------------------------------------------
# SVG namespace
# ---------------------------------------------------------------------------

_SVG_NS = "http://www.w3.org/2000/svg"


def _strip_ns(tag):
    """Strip the SVG namespace prefix from an element tag."""
    if tag.startswith("{" + _SVG_NS + "}"):
        return tag[len(_SVG_NS) + 2 :]
    return tag


# ---------------------------------------------------------------------------
# Inline theme parsing
# ---------------------------------------------------------------------------

# Matches ``:root{ --role: #hex; ... }`` inside a <style> block.
_CSS_VAR_BLOCK_RE = re.compile(r":root\s*\{([^}]*)\}", re.IGNORECASE)
_CSS_VAR_DECL_RE = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);")


def _parse_inline_theme(svg_root):
    """Parse inline theme variables from ``<defs><style>:root{...}</style></defs>``.

    Returns a dict mapping dotted role names to hex colour strings,
    e.g. ``{"surface": "#1e1e1e"}``. Hyphenated CSS var names are converted
    to dotted roles: ``--text-muted`` -> ``text.muted``.
    """
    theme = {}
    style_elem = svg_root.find(".//{" + _SVG_NS + "}style")
    if style_elem is not None and style_elem.text:
        text = style_elem.text.strip()
        for block_match in _CSS_VAR_BLOCK_RE.finditer(text):
            body = block_match.group(1)
            for decl in _CSS_VAR_DECL_RE.finditer(body):
                role = decl.group(1).replace("-", ".")
                value = decl.group(2).strip()
                theme[role] = value
    return theme


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------


def _float(value, default=0.0):
    """Parse an attribute string as float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _int(value, default=0):
    """Parse an attribute string as int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _apply_opacity(fill_value, opacity_value):
    """Combine fill color and opacity attribute into single #AARRGGBB hex."""
    if fill_value is None:
        return None
    opacity_attr = opacity_value if opacity_value is not None else "1.0"
    try:
        opacity_ratio = float(opacity_attr)
        opacity_ratio = max(0.0, min(1.0, opacity_ratio))
    except (ValueError, TypeError):
        opacity_ratio = 1.0
    alpha_byte = int(round(opacity_ratio * 255))
    fill_value = fill_value.strip()
    if fill_value.startswith("#"):
        if len(fill_value) == 7:      # #RRGGBB
            return "#{:02X}{}".format(alpha_byte, fill_value[1:])
        elif len(fill_value) == 9:    # #AARRGGBB already present; replace alpha
            return "#{:02X}{}".format(alpha_byte, fill_value[3:])
    return fill_value  # var(--role) or other theme ref: opacity ignored


def _resolve(value, theme_colors):
    """Resolve a colour expression to an unsigned-int string.

    Accepts ``var(--role)`` (looked up in *theme_colors*), ``#rrggbb``,
    ``#rrggbbaa``, or ``None``.  Returns ``None`` when *value* is absent,
    empty, or the SVG literal ``"none"``.
    """
    if value is None:
        return None
    value = value.strip()
    if not value or value.lower() == "none":
        return None
    return _themes.resolve_color_unsigned(value, theme_colors)


# ---------------------------------------------------------------------------
# Element parsers (each returns an ElementSpec dict)
# ---------------------------------------------------------------------------


def _parse_rect(elem, theme):
    """Parse a plain ``<rect>`` -> rectangle / rounded-rectangle."""
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 100)
    h = _float(elem.get("height"), 100)
    rx = elem.get("rx")

    fill = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)
    stroke = _resolve(_apply_opacity(elem.get("stroke"), elem.get("stroke-opacity")), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
    }

    if rx is not None:
        params["shape"] = "rounded"
        params["corner_radius"] = str(int(_float(rx)))
    else:
        params["shape"] = "rectangle"

    if fill is not None:
        params["fill"] = fill
    if stroke is not None:
        params["frame"] = stroke

    return {"type": "rectangle", "params": params}


def _parse_circle(elem, theme):
    """Parse a ``<circle>`` -> rectangle with shape=ellipse (via bounding-box)."""
    cx = _float(elem.get("cx"), 0)
    cy = _float(elem.get("cy"), 0)
    r = _float(elem.get("r"), 0)

    x = cx - r
    y = cy - r
    w = 2.0 * r
    h = 2.0 * r

    fill = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)
    stroke = _resolve(_apply_opacity(elem.get("stroke"), elem.get("stroke-opacity")), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "shape": "ellipse",
    }

    if fill is not None:
        params["fill"] = fill
    if stroke is not None:
        params["frame"] = stroke

    return {"type": "rectangle", "params": params}


def _parse_ellipse(elem, theme):
    """Parse an ``<ellipse>`` -> rectangle with shape=ellipse (via bounding-box)."""
    cx = _float(elem.get("cx"), 0)
    cy = _float(elem.get("cy"), 0)
    rx = _float(elem.get("rx"), 0)
    ry = _float(elem.get("ry"), 0)

    x = cx - rx
    y = cy - ry
    w = 2.0 * rx
    h = 2.0 * ry

    fill = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)
    stroke = _resolve(_apply_opacity(elem.get("stroke"), elem.get("stroke-opacity")), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "shape": "ellipse",
    }

    if fill is not None:
        params["fill"] = fill
    if stroke is not None:
        params["frame"] = stroke

    return {"type": "rectangle", "params": params}


def _parse_line(elem, theme):
    """Parse a ``<line>`` -> line with endpoint geometry."""
    x1 = _int(elem.get("x1"), 0)
    y1 = _int(elem.get("y1"), 0)
    x2 = _int(elem.get("x2"), 100)
    y2 = _int(elem.get("y2"), 100)

    x = min(x1, x2)
    y = min(y1, y2)
    w = abs(x2 - x1)
    h = abs(y2 - y1)

    fill = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)
    stroke = _resolve(_apply_opacity(elem.get("stroke"), elem.get("stroke-opacity")), theme)

    params = {
        "x": str(x),
        "y": str(y),
        "width": str(w if w > 0 else 1),
        "height": str(h if h > 0 else 1),
        "x1": str(x1),
        "y1": str(y1),
        "x2": str(x2),
        "y2": str(y2),
    }

    if fill is not None:
        params["fill"] = fill
    if stroke is not None:
        params["frame"] = stroke

    return {"type": "line", "params": params}


# Character advance widths in 1/1000 em, approximating the Arial-like
# proportional face CODESYS uses for its default UI font. A single average
# cannot stand in for these: 0.65 em/char is about right for uppercase, but it
# overstates mixed-case text by a quarter, and this estimate is load-bearing in
# four places -- the default box width of a <text> with no data-width, and the
# lint text-overflow, overlap and crowding rules, all of which read that width
# back. An inflated box reports overflow that is not there and collides with
# neighbours it does not touch, which pushes an author into a sparser layout to
# silence findings that were never real.
_EM_NARROW = " .,:;'`|!ijlI"
_EM_THIN = "ft()[]{}/\\-\"J"
_EM_WIDE = "ABCDEFGHKLNOPQRSTUVXYZ&$#"
_EM_WIDEST = "mwMW%@"
_EM_DEFAULT = 556


def _char_em(ch):
    if ch in _EM_NARROW:
        return 280
    if ch in _EM_THIN:
        return 333
    if ch in _EM_WIDE:
        return 667
    if ch in _EM_WIDEST:
        return 833
    return _EM_DEFAULT


def _estimate_text_width(text, font_size=12):
    """Estimate the rendered width of ``text`` in px.

    Sums per-character advances rather than assuming one average width, so a
    label of lowercase prose is not measured as though it were an all-caps tag.
    The trailing 8px is padding, matching what the box needs to keep the glyphs
    off its own frame.
    """
    if not text:
        return 20
    em = sum(_char_em(ch) for ch in text)
    return _to_grid(max(20, int(em * int(font_size) / 1000.0) + 8))


def _estimate_text_height(font_size=12):
    return _to_grid(max(16, int(int(font_size) * 1.4)))


def _to_grid(value, grid=4):
    """Round *value* up to the next multiple of *grid*.

    The estimates below are what a label gets when the author wrote no
    data-width/data-height, and they land on arbitrary pixels -- so the box the
    sketch compiled to failed the project's own 4px grid rule, and ``lint`` then
    reported a finding against a number no one had written. Rounding *up* keeps
    the box at least as wide as the glyphs need.
    """
    return int((value + grid - 1) // grid * grid)


# Fully transparent, for shapes that genuinely have no fill or no frame.
# Written as 8-digit #AARRGGBB on purpose: ``themes.resolve_color`` forces
# alpha to FF on any expression of 6 hex digits or fewer, so the shorter
# spellings ("0", "#000000") would come back as *opaque black*.
TRANSPARENT_ARGB = "#00000000"


_int_attrs = ("x", "y", "width", "height")


def _parse_text(elem, theme):
    """Parse a ``<text>`` -> label with caption text.

    SVG ``x``/``y`` uses top-left origin for x and **baseline** for y.
    CODESYS labels use a bounding box with alignment, so we convert:
    - y = SVG_y - font_size  (baseline -> top of box)
    - default alignment: LEFT / TOP (not HCENTER/VCENTER)
    - ``text-anchor="middle"`` maps to HCENTER
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    fs = elem.get("font-size")
    font_size = int(_float(fs, 12))
    text_content = (elem.text or "").strip()

    # Default data-width / data-height from text content estimate.
    def_w = _estimate_text_width(text_content, font_size)
    def_h = _estimate_text_height(font_size)
    w = _float(elem.get("data-width"), def_w)
    h = _float(elem.get("data-height"), def_h)

    # Convert SVG baseline-y to CODESYS top-y.
    y_top = y - font_size

    font_color = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y_top)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text_content,
        # An SVG <text> has no box. Without an explicit fill/frame the builder
        # would resolve the label's ``custom-fill`` role and paint an opaque
        # rectangle behind every caption -- visible as a pale block wherever a
        # label sits on a panel. Transparent ARGB keeps the glyphs only; author
        # a <rect> behind the <text> when a boxed label is what you want.
        "fill": TRANSPARENT_ARGB,
        "frame": TRANSPARENT_ARGB,
    }

    # SVG text-anchor -> CODESYS h_align. Note that x stays the box LEFT edge in
    # every case: CODESYS places text inside a box, so the anchor picks where the
    # glyphs sit *within* data-width rather than moving the box. Real SVG instead
    # reads x as the centre (middle) or the right edge (end) -- see SKILL.md,
    # which has to state this because it is the one place the sketch format does
    # not mean what an SVG viewer would show.
    anchor = elem.get("text-anchor")
    if anchor == "middle":
        params["h_align"] = "HCENTER"
        params["v_align"] = "VCENTER"
        # Restore y to baseline-centered for middle anchor.
        params["y"] = str(int(y - h / 2))
    elif anchor == "end":
        params["h_align"] = "RIGHT"
        params["v_align"] = "TOP"
    else:
        # CODESYS template defaults are HCENTER/VCENTER; override to LEFT/TOP.
        params["h_align"] = "LEFT"
        params["v_align"] = "TOP"

    if font_color is not None:
        params["font_color"] = font_color

    if fs is not None:
        params["font_size"] = str(font_size)

    ff = elem.get("font-family")
    if ff is not None:
        params["font_name"] = ff

    return {"type": "label", "params": params}


def _parse_button(elem, theme):
    """Parse a ``<rect data-cds-type="button">`` -> button control.

    Emits fill/frame as overridable uint literals (themeable) so buttons
    get visible colors, not just style-linked defaults.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 100)
    h = _float(elem.get("height"), 100)
    text = elem.get("data-text", "")
    text_id = elem.get("data-text-id", "")
    tap_var = _parse_tap_var(elem.get("data-cds-tap", ""))
    actions = _parse_button_actions(elem.get("data-cds-action", ""))

    fill = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)
    stroke = _resolve(_apply_opacity(elem.get("stroke"), elem.get("stroke-opacity")), theme)
    font_color = _resolve("var(--button-text)", theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text,
    }

    if fill is not None:
        params["fill"] = fill
    if stroke is not None:
        params["frame"] = stroke
    if font_color is not None:
        # Same reasoning as the textfield: a native control skips class
        # expansion, so it never picks up ``fill: var(--text)`` and would fall
        # back to the builder's opaque white. ``button.text`` tracks the button
        # face rather than the panel behind it, and in light it *is* that white
        # -- so naming the role changes nothing here and everything in dark.
        params["font_color"] = font_color
    if tap_var:
        params["tap_var"] = tap_var
    if actions["configured_inputs"]:
        params["configured_inputs"] = actions["configured_inputs"]
    if actions["input_actions"]:
        params["input_actions"] = actions["input_actions"]
    if text_id:
        params["text_id"] = text_id

    return {"type": "button", "params": params}


def _parse_tap_var(raw):
    """Return variable name from a simple tap/toggle data-cds-tap action."""
    text = (raw or "").strip()
    if not text:
        return ""
    lower = text.lower()
    for prefix in ("tap:", "tap ", "toggle:", "toggle "):
        if lower.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _parse_button_actions(raw):
    """Parse data-cds-action for native button actions.

    Supported forms:
    - TAP HMI.Var
    - TOGGLE HMI.Var
    - OnMouseClick: ST HMI.Var := TRUE;
    - OnMouseClick: toggle HMI.Var
    - OnMouseClick: screen CoolingTower
    Multiple actions can be separated with ``||``.
    """
    result = {"configured_inputs": [], "input_actions": []}
    text = (raw or "").strip()
    if not text:
        return result
    for part in [p.strip() for p in text.split("||") if p.strip()]:
        if ":" in part and part.split(":", 1)[0].strip().lower().startswith("on"):
            event, body = part.split(":", 1)
            result["input_actions"].append(_parse_event_action(event.strip(), body.strip()))
        else:
            result["configured_inputs"].append(_parse_complex_action(part))
    return result


def _parse_complex_action(text):
    lower = text.lower()
    for prefix in ("tap:", "tap "):
        if lower.startswith(prefix):
            return {
                "type": "tap",
                "values": {"variable": text[len(prefix) :].strip()},
            }
    for prefix in ("toggle:", "toggle "):
        if lower.startswith(prefix):
            return {
                "type": "toggle",
                "values": {
                    "variable": text[len(prefix) :].strip(),
                    "toggle_on": "False",
                },
            }
    raise ValueError("Unsupported data-cds-action complex action: {0}".format(text))


def _parse_event_action(event, body):
    lower = body.lower()
    if lower.startswith("st "):
        return {
            "event": event,
            "type": "st_snippet",
            "values": {"snippet": body[3:].strip()},
        }
    if lower.startswith("st:"):
        return {
            "event": event,
            "type": "st_snippet",
            "values": {"snippet": body[3:].strip()},
        }
    if lower.startswith("toggle "):
        return {
            "event": event,
            "type": "toggle_variable",
            "values": {"variable": body[7:].strip()},
        }
    if lower.startswith("toggle:"):
        return {
            "event": event,
            "type": "toggle_variable",
            "values": {"variable": body[7:].strip()},
        }
    if lower.startswith("screen "):
        return {
            "event": event,
            "type": "change_screen",
            "values": {"screen": body[7:].strip()},
        }
    if lower.startswith("screen:"):
        return {
            "event": event,
            "type": "change_screen",
            "values": {"screen": body[7:].strip()},
        }
    raise ValueError(
        "Unsupported data-cds-action event action: {0}: {1}".format(event, body)
    )


def _parse_textfield(elem, theme):
    """Parse a ``<text data-cds-type="textfield">`` -> textfield control.

    Textfield is like Label but can show runtime variable values.
    ``fill`` controls the font colour. Alignment same as SVG ``<text>``.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    text = elem.text or ""
    text = text.strip() if text else ""
    text_var = elem.get("data-text-var", "")
    fs = elem.get("font-size")
    font_size = int(_float(fs, 12)) if fs else 12
    font_name = elem.get("font-family", "Arial")

    # Same estimate a plain <text> gets. A flat 100x100 default was a box the
    # author never asked for: it overflowed whatever card held the field, which
    # the lint then reported as an overlap, and the compiled control really was
    # 100px tall on screen. A field without an explicit size is still worth
    # writing one for -- that is a lint finding -- but the guess it falls back
    # to should be the documented one.
    w = _float(elem.get("data-width"), _estimate_text_width(text, font_size))
    h = _float(elem.get("data-height"), _estimate_text_height(font_size))

    y_top = y - font_size

    font_color = _resolve(_apply_opacity(elem.get("fill"), elem.get("fill-opacity")), theme)
    if font_color is None:
        # Native controls skip class expansion, so a textfield never picks up
        # ``fill: var(--text)`` the way a plain <text> does -- and the builder's
        # last-resort font colour is opaque white, which is invisible on the
        # light field the CODESYS style paints. Resolve the field's own text
        # role instead: it tracks the *field box*, not the panel behind it, so
        # the pairing survives a scheme flip in either direction.
        font_color = _resolve("var(--field-text)", theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y_top)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text,
        "text_var": text_var,
        "font_size": str(font_size),
        "font_name": font_name,
    }

    anchor = elem.get("text-anchor")
    if anchor == "middle":
        params["h_align"] = "HCENTER"
        params["v_align"] = "VCENTER"
        params["y"] = str(int(y - h / 2))
    elif anchor == "end":
        params["h_align"] = "RIGHT"
        params["v_align"] = "TOP"
    else:
        params["h_align"] = "LEFT"
        params["v_align"] = "TOP"

    if font_color is not None:
        params["font_color"] = font_color

    return {"type": "textfield", "params": params}


# ---------------------------------------------------------------------------
# Native indicator/control elements (golden-template backed)
# ---------------------------------------------------------------------------

# Friendly lamp colour -> VisualizationStyle role. CODESYS appends -On/-Off
# from the bound variable at runtime, so the role name stops at the colour.
_LAMP_COLOR_ROLES = {
    "red": "Element-Lamp-Lamp1-Red",
    "green": "Element-Lamp-Lamp1-Green",
    "yellow": "Element-Lamp-Lamp1-Yellow",
    "blue": "Element-Lamp-Lamp1-Blue",
    "gray": "Element-Lamp-Lamp1-Gray",
    "grey": "Element-Lamp-Lamp1-Gray",
}


def _parse_lamp(elem, theme):
    """Parse a ``<rect data-cds-type="lamp">`` -> indicator lamp control.

    A lamp is a native status light bound to a BOOL variable. The friendly
    ``data-color`` (red|green|yellow|blue|gray) selects the bitmap role; the
    On/Off state is driven at runtime by ``data-var``.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 32)
    h = _float(elem.get("height"), 32)

    color = (elem.get("data-color") or "green").strip().lower()
    style_role = _LAMP_COLOR_ROLES.get(color, _LAMP_COLOR_ROLES["green"])
    var = elem.get("data-var", "") or elem.get("data-text-var", "")

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "style_role": style_role,
        "var": var,
    }
    return {"type": "lamp", "params": params}

 
def _parse_image_switcher(elem, theme):
    """Parse a <rect data-cds-type="image-switcher"> -> ImageSwitcher control.

    An ImageSwitcher shows one of two ImagePool images based on a BOOL
    variable. data-image-on / data-image-off specify the two image
    references; data-var is the bound BOOL variable.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 70)
    h = _float(elem.get("height"), 70)

    image_on = (elem.get("data-image-on") or "").strip()
    image_off = (elem.get("data-image-off") or "").strip()
    var = elem.get("data-var", "") or ""

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "image_on": image_on,
        "image_off": image_off,
        "var": var,
    }
    return {"type": "image-switcher", "params": params}


def _parse_combobox(elem, theme):
    """Parse a <rect data-cds-type="combobox"> -> ComboBoxInteger control.

    A combobox is a dropdown bound to an INT variable, using labels from
    a GlobalTextList reference.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 120)
    h = _float(elem.get("height"), 25)

    items = (elem.get("data-items") or "").strip()
    var = elem.get("data-var", "") or ""

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "items": items,
        "var": var,
    }
    return {"type": "combobox", "params": params}


def _parse_alarm_banner(elem, theme):
    """Parse a ``<rect data-cds-type="alarm-banner">`` -> AlarmBanner control.

    An AlarmBanner is a native scrolling alarm ticker. It has no bound
    variable -- the alarm filtering is carried by literal members in the
    golden template. Geometry only.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 400)
    h = _float(elem.get("height"), 25)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
    }
    return {"type": "alarm-banner", "params": params}


def _parse_frame(elem, theme):
    """Parse a ``<rect data-cds-type="frame">`` -> VisuFbFrame element.

    A frame embeds a sub-visualisation (visu). Geometry only; all other
    parameters are literals carried by data-param-* attributes.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 100)
    h = _float(elem.get("height"), 100)

    visu = (elem.get("data-visu") or "").strip()

    params_map = {}
    for attr_name, attr_val in elem.attrib.items():
        if attr_name.startswith("data-param-"):
            params_map[attr_name[len("data-param-"):]] = attr_val

    return {
        "type": "frame",
        "params": {
            "x": str(int(x)),
            "y": str(int(y)),
            "width": str(int(w)),
            "height": str(int(h)),
            "visu": visu,
            "params": params_map,
        },
    }


def _apply_dialog_attrs(child, element_dict):
    """Parse data-open-dialog attrs into element's input_actions.

    Called AFTER the element has been parsed and appended to the elements
    list.  In this version, only button elements support dialog-open at
    compile time.  Decompile still reads openers on any element; compile is
    button-only (only element_button.xml.tmpl has @@VISUAL_ELEMENT_INPUT_ACTIONS@@).
    """
    dialog = child.get("data-open-dialog")
    if dialog is None:
        return

    element_type = element_dict.get("type")
    if element_type not in ("button", "rectangle"):
        raise ValueError(
            'data-open-dialog is only supported on a button or a simple '
            'rectangle/circle/ellipse element in this version'
        )

    modal_raw = (child.get("data-dialog-modal") or "True").strip()
    modal = "True" if modal_raw.lower() == "true" else "False"

    centered_raw = (child.get("data-dialog-centered") or "True").strip()
    centered = "True" if centered_raw.lower() == "true" else "False"

    actions = element_dict.setdefault("params", {}).setdefault(
        "input_actions", []
    )
    # Collect data-dialog-param-<name> attrs (mirrors _parse_frame).
    params_map = {}
    for attr_name, attr_val in child.attrib.items():
        if attr_name.startswith("data-dialog-param-"):
            params_map[attr_name[len("data-dialog-param-"):]] = attr_val
    values = {
        "dialog": dialog,
        "modal": modal,
        "centered": centered,
        "position_x": "",
        "position_y": "",
    }
    if params_map:
        values["params"] = params_map
    actions.append({
        "event": "OnMouseClick",
        "type": "open_dialog",
        "values": values,
    })

    st = child.get("data-dialog-st")
    if st:
        actions.append({
            "event": "OnMouseClick",
            "type": "st_snippet",
            "values": {"snippet": st},
        })


_ELEMENT_PARSERS = {
    "rect": _parse_rect,
    "circle": _parse_circle,
    "ellipse": _parse_ellipse,
    "line": _parse_line,
    "text": _parse_text,
}

_SUPPORTED = set(_ELEMENT_PARSERS.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _apply_class_attributes(elem, sheet):
    """Expand a ``class`` attribute into SVG presentation attributes.

    Classes are the primary authoring mechanism: ``class="panel"`` becomes
    ``fill="var(--panel)"`` etc. Values are applied only where the element does
    not already carry an explicit attribute, so a hand-written ``fill``/
    ``stroke`` always wins (escape hatch / back-compat). Colours stay as
    ``var(--role)`` and resolve through the theme like any other value.
    """
    class_value = elem.get("class")
    if not class_value:
        return
    for attr, value in _stylesheet.class_attributes(class_value, sheet).items():
        if elem.get(attr) is None:
            elem.set(attr, value)


def read_scheme(svg_text, override=None):
    """Resolve the colour scheme of a sketch without parsing its elements.

    Same precedence as :func:`parse_svg`: an explicit *override* wins, then
    ``data-cds-scheme`` on the root ``<svg>``, then ``light``.

    This exists because the scheme has to be known *before* the theme is loaded:
    ``load_theme`` decides there which roles the CODESYS style is allowed to own,
    and a light theme layered over a dark base palette would repaint the whole
    screen light again. A malformed document resolves to the override (or light)
    rather than raising -- reporting the parse error is ``parse_svg``'s job, and
    doing it twice would only bury it.
    """
    if override is not None:
        return _style_roles.normalize_scheme(override)
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return "light"
    return _style_roles.normalize_scheme(root.get("data-cds-scheme"))


def _parse_error_message(svg_text, exc):
    """Turn an ElementTree ParseError into something an author can act on.

    A sketch is hand-written, so the first ``cts visu lint`` on a new file is
    exactly when a typo surfaces -- and a raw ``xml.etree`` traceback names
    neither the offending line nor the rule it broke. The commonest cause by a
    wide margin is a decorative comment: ``<!-- ---- Supply air ---- -->`` looks
    like every other section header a programmer writes, and is not valid XML.
    """
    parts = ["malformed SVG: {0}".format(exc)]
    line = getattr(exc, "position", (0, 0))[0]
    lines = svg_text.splitlines()
    if 0 < line <= len(lines):
        source = lines[line - 1].strip()
        parts.append("  {0}".format(source))
        inner = source
        if inner.startswith("<!--"):
            inner = inner[4:]
        if inner.endswith("-->"):
            inner = inner[:-3]
        if "--" in inner:
            parts.append(
                'XML reserves "--" for the comment delimiter, so it cannot '
                'appear inside a comment. Rule a separator off with "====".'
            )
    return "\n".join(parts)


def parse_svg(svg_text, theme=None, project_dir=None, background=None, scheme=None):
    """Parse an SVG string and return a dict of ElementSpec entries.

    Args:
        svg_text: Raw SVG XML string.
        theme: Optional dict of role -> hex colour for ``var(--role)``
               resolution (e.g. ``{"surface": "#1e1e1e"}``).  May be
               overridden by inline ``:root`` variables found in a
               ``<defs><style>`` block inside the SVG.
        project_dir: Optional directory searched for a project ``visu.css``.
        background: ``auto`` (default, curated neutral), ``style`` (the CODESYS
               style's own element background) or an explicit ``#RRGGBB``.
        scheme: ``light`` / ``dark``, or ``None`` to read ``data-cds-scheme``
               off the root ``<svg>`` (defaulting to ``light``). An explicit
               argument wins so a one-off ``--scheme`` render does not have to
               edit the sketch.

    Returns:
        A dict with keys:

        - **canvas**: ``{"width": int, "height": int}``
        - **elements**: list of ElementSpec dicts (see below)
        - **theme**: merged theme dict (inline vars take priority)
        - **scheme**: the resolved scheme name

    ElementSpec format::

        {
            "type": "rectangle" | "label" | "line" | "button" | "textfield",
            "params": {
                "x": "...", "y": "...",
                "width": "...", "height": "...",
                "fill": "...", "frame": "...",   # optional, unsigned int str
                ...
            }
        }

    Raises:
        ValueError: On unsupported SVG elements, or on XML that will not parse.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise ValueError(_parse_error_message(svg_text, exc))

    # -- Canvas size -------------------------------------------------------
    width = _int(root.get("width"), 800)
    height = _int(root.get("height"), 480)

    # -- Scheme ------------------------------------------------------------
    # The sketch carries its own scheme so preview and compile cannot disagree
    # about it; the caller can still override for a single render.
    resolved_scheme = _style_roles.normalize_scheme(
        scheme if scheme is not None else root.get("data-cds-scheme")
    )

    # -- Inline theme ------------------------------------------------------
    inline_theme = _parse_inline_theme(root)

    # Merge role -> hex layers, later wins:
    #   1. built-in style_roles fallbacks for the active scheme (so any
    #      documented var(--role) always resolves -- no "white element" from an
    #      unmapped role);
    #   2. caller-provided theme;
    #   3. inline :root overrides.
    merged_theme = _style_roles.role_palette(None, resolved_scheme)
    if theme is not None:
        merged_theme.update(theme)
    merged_theme.update(inline_theme)

    # Semantic class stylesheet (bundled defaults + optional project visu.css).
    sheet = _stylesheet.load_stylesheet(project_dir)

    # -- SVG elements ------------------------------------------------------
    elements = []

    for child in root:
        tag = _strip_ns(child.tag)
        if tag == "defs":
            continue  # already handled by _parse_inline_theme

        # Expand class="..." into fill/stroke/font-size before parsing, so the
        # existing per-element parsers see plain attributes and need no change.
        # Native controls (button/textfield) intentionally ignore classes: they
        # inherit the CODESYS visual style, so we never inject colour into them.
        if child.get("data-cds-type") is None:
            _apply_class_attributes(child, sheet)

        # Promote <rect data-cds-type="button"> to button.
        if tag == "rect" and child.get("data-cds-type") == "button":
            elements.append(_parse_button(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        # Promote <text data-cds-type="textfield"> to textfield.
        if tag == "text" and child.get("data-cds-type") == "textfield":
            elements.append(_parse_textfield(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        # Promote <rect data-cds-type="lamp"> to indicator lamp.
        if tag == "rect" and child.get("data-cds-type") == "lamp":
            elements.append(_parse_lamp(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        # Promote <rect data-cds-type="image-switcher"> to ImageSwitcher.
        if tag == "rect" and child.get("data-cds-type") == "image-switcher":
            elements.append(_parse_image_switcher(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        # Promote <rect data-cds-type="combobox"> to ComboBoxInteger.
        if tag == "rect" and child.get("data-cds-type") == "combobox":
            elements.append(_parse_combobox(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        # Promote <rect data-cds-type="alarm-banner"> to AlarmBanner.
        if tag == "rect" and child.get("data-cds-type") == "alarm-banner":
            elements.append(_parse_alarm_banner(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        # Promote <rect data-cds-type="frame"> to VisuFbFrame.
        if tag == "rect" and child.get("data-cds-type") == "frame":
            elements.append(_parse_frame(child, merged_theme))
            _apply_dialog_attrs(child, elements[-1])
            continue

        parser = _ELEMENT_PARSERS.get(tag)
        if parser is None:
            raise ValueError(
                "Unsupported SVG element: <{0}>. Supported: {1}".format(
                    tag, ", ".join(sorted(_SUPPORTED))
                )
            )
        elements.append(parser(child, merged_theme))
        _apply_dialog_attrs(child, elements[-1])

    # Determine background colour from theme.
    bg_color = resolve_background(background, merged_theme)

    return {
        "canvas": {"width": width, "height": height},
        "elements": elements,
        "theme": merged_theme,
        "bg_color": bg_color,
        "scheme": resolved_scheme,
    }


def resolve_background(mode, theme_colors):
    """Pick the screen background colour for a ``--background`` mode.

    ``auto`` (the default) uses the curated ``screen`` role, a neutral field
    chosen so panels, status colours and native controls all read cleanly on
    it. ``style`` uses whatever the project's CODESYS style puts behind an
    element, which on several shipped styles is a saturated tint. Anything
    starting with ``#`` is taken literally.
    """
    text = str(mode or "auto").strip().lower()
    if text.startswith("#"):
        return str(mode).strip()
    keys = ("surface", "background") if text == "style" else ("screen", "surface", "background")
    for key in keys:
        val = (theme_colors or {}).get(key)
        if val:
            return val
    return None
