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

    fill = _resolve(elem.get("fill"), theme)
    stroke = _resolve(elem.get("stroke"), theme)

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

    fill = _resolve(elem.get("fill"), theme)
    stroke = _resolve(elem.get("stroke"), theme)

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

    fill = _resolve(elem.get("fill"), theme)
    stroke = _resolve(elem.get("stroke"), theme)

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

    fill = _resolve(elem.get("fill"), theme)
    stroke = _resolve(elem.get("stroke"), theme)

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


def _estimate_text_width(text, font_size=12):
    """Rough estimate of CSS text width in px."""
    if not text:
        return 20
    avg = int(font_size) * 0.65
    return max(20, int(len(text) * avg) + 8)


def _estimate_text_height(font_size=12):
    return max(16, int(font_size) * 1.4)


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

    font_color = _resolve(elem.get("fill"), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y_top)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text_content,
    }

    # SVG text-anchor="middle" -> HCENTER
    anchor = elem.get("text-anchor")
    if anchor == "middle":
        params["h_align"] = "HCENTER"
        params["v_align"] = "VCENTER"
        # Restore y to baseline-centered for middle anchor.
        params["y"] = str(int(y - h / 2))
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

    fill = _resolve(elem.get("fill"), theme)
    stroke = _resolve(elem.get("stroke"), theme)

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
    w = _float(elem.get("data-width"), 100)
    h = _float(elem.get("data-height"), 100)
    text = elem.text or ""
    text = text.strip() if text else ""
    text_var = elem.get("data-text-var", "")
    fs = elem.get("font-size")
    font_size = int(_float(fs, 12)) if fs else 12
    font_name = elem.get("font-family", "Arial")

    y_top = y - font_size

    font_color = _resolve(elem.get("fill"), theme)

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
    actions.append({
        "event": "OnMouseClick",
        "type": "open_dialog",
        "values": {
            "dialog": dialog,
            "modal": modal,
            "centered": centered,
            "position_x": "",
            "position_y": "",
        },
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


def parse_svg(svg_text, theme=None, project_dir=None):
    """Parse an SVG string and return a dict of ElementSpec entries.

    Args:
        svg_text: Raw SVG XML string.
        theme: Optional dict of role -> hex colour for ``var(--role)``
               resolution (e.g. ``{"surface": "#1e1e1e"}``).  May be
               overridden by inline ``:root`` variables found in a
               ``<defs><style>`` block inside the SVG.

    Returns:
        A dict with keys:

        - **canvas**: ``{"width": int, "height": int}``
        - **elements**: list of ElementSpec dicts (see below)
        - **theme**: merged theme dict (inline vars take priority)

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
        ValueError: On unsupported SVG elements.
    """
    root = ET.fromstring(svg_text)

    # -- Canvas size -------------------------------------------------------
    width = _int(root.get("width"), 800)
    height = _int(root.get("height"), 480)

    # -- Inline theme ------------------------------------------------------
    inline_theme = _parse_inline_theme(root)

    # Merge role -> hex layers, later wins:
    #   1. built-in style_roles fallbacks (so any documented var(--role) always
    #      resolves -- no "white element" from an unmapped role);
    #   2. caller-provided theme;
    #   3. inline :root overrides.
    merged_theme = _style_roles.role_palette(None)
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
    bg_color = None
    for key in ("surface", "background"):
        val = merged_theme.get(key)
        if val:
            bg_color = val
            break

    return {
        "canvas": {"width": width, "height": height},
        "elements": elements,
        "theme": merged_theme,
        "bg_color": bg_color,
    }
