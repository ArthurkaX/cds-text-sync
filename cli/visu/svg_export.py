# -*- coding: utf-8 -*-
"""
svg_export.py - Reverse CODESYS → SVG conversion.

Reads a CODESYS screen XML and produces an SVG string with themed
elements.  Follows plan.md §4 (SVG schema) and §5 (color model) for the
reverse direction.

Usage::

    from cli.visu.svg_export import screen_to_svg

    svg = screen_to_svg(xml_text)
"""

from __future__ import print_function

import json
import os
import xml.etree.ElementTree as ET

_THEME_DIR = os.path.join(os.path.dirname(__file__), "themes")


class SvgExportError(Exception):
    """Raised on unsupported element types or malformed data."""

    pass


# ---------------------------------------------------------------------------
# XML helpers  (mirroring builder.py conventions)
# ---------------------------------------------------------------------------


def _strip_ns(tag):
    return tag.split("}")[-1] if "}" in str(tag) else tag


def _find_named(parent, tag_name, name):
    for child in list(parent):
        if _strip_ns(child.tag) == tag_name and child.attrib.get("Name") == name:
            return child
    return None


def _named_text(parent, name):
    child = _find_named(parent, "Single", name)
    return (child.text or "").strip() if child is not None and child.text else ""


# ---------------------------------------------------------------------------
# Member extraction
# ---------------------------------------------------------------------------


def _member_value(element, member_id):
    """Return the value for a given *member_id* from an element's member list.

    For **scalar** members (short-form ``<Single Name="Value">``) returns the
    value as a plain string.

    For **color struct** members (``<List Name="Value">`` with a nested
    ``<Single Name="Color">``) returns a dict with keys ``color`` (the signed
    int string) and ``canonical_name``.

    Returns ``None`` when the member id is not present in the element.
    """
    member_container = _find_named(element, "Single", "VisualElemMemberList")
    mlist = (
        _find_named(member_container, "List", "VisualElemMemberList")
        if member_container is not None
        else None
    )
    if mlist is None:
        return None
    for member in list(mlist):
        if _strip_ns(member.tag) != "Single":
            continue
        idc = _find_named(member, "Single", "Id")
        if idc is None or not idc.text:
            continue
        mid = int(idc.text.strip())
        if mid != member_id:
            continue

        # Scalar (short-form) value.
        scalar = _find_named(member, "Single", "Value")
        if scalar is not None:
            return (scalar.text or "").strip()

        # Struct (color) value.
        listval = _find_named(member, "List", "Value")
        if listval is not None:
            inner = list(listval)
            if inner and _find_named(inner[0], "Single", "Color") is not None:
                color_el = _find_named(inner[0], "Single", "Color")
                cn_el = _find_named(inner[0], "Single", "CanonicalName")
                return {
                    "color": (
                        (color_el.text or "").strip() if color_el is not None else ""
                    ),
                    "canonical_name": ((cn_el.text or "") if cn_el is not None else ""),
                }
    return None


# ---------------------------------------------------------------------------
# Color helpers  (§5 reverse rules)
# ---------------------------------------------------------------------------


def _uint_to_svg_color(uint_str):
    """Convert a (possibly signed) ARGB integer string to SVG ``#rrggbb[aa]``.

    Drops the alpha byte when it is ``0xFF`` (fully opaque).
    Handles both positive unsigned (e.g. ``4294967295``) and signed negative
    (e.g. ``-1``) representations.
    """
    if uint_str is None or uint_str == "":
        return None
    try:
        val = int(uint_str) & 0xFFFFFFFF
    except (ValueError, TypeError):
        return None
    a = (val >> 24) & 0xFF
    r = (val >> 16) & 0xFF
    g = (val >> 8) & 0xFF
    b = val & 0xFF
    if a == 0xFF:
        return "#{:02x}{:02x}{:02x}".format(r, g, b)
    return "#{:02x}{:02x}{:02x}{:02x}".format(a, r, g, b)


# Mapping from CanonicalName → CSS variable role (plan.md §5).
_CANONICAL_TO_ROLE = {
    "BasicElement-Fill-Color": "fill",
    "BasicElement-Frame-Color": "frame",
    "Font-Default-Color": "text",
    "BasicElement-Alarm-Frame-Color": "alarm-frame",
    "BasicElement-Alarm-Fill-Color": "alarm-fill",
}


def _canonical_to_role(canonical_name):
    """Derive a CSS variable role name from a *CanonicalName* string."""
    if canonical_name in _CANONICAL_TO_ROLE:
        return _CANONICAL_TO_ROLE[canonical_name]
    # Fallback heuristic: strip known prefixes and the "-Color" suffix,
    # then convert to hyphen-case.
    name = canonical_name
    for prefix in ("BasicElement-", "Font-", "Alarm-"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    if name.endswith("-Color"):
        name = name[: -len("-Color")]
    parts = name.split("-")
    return "-".join(p.lower() for p in parts)


def _resolve_color_value(value):
    """Return an SVG color string from a ``_member_value`` result.

    **Struct with non-empty CanonicalName**
        → ``var(--<role>)``    (§5 reverse rule 1)

    **Short-form uint scalar** (or struct with empty CanonicalName)
        → ``#rrggbb[aa]``     (§5 reverse rule 2)

    Returns ``None`` when *value* is ``None`` or empty.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        cn = value.get("canonical_name", "")
        if cn:
            role = _canonical_to_role(cn)
            return "var(--{0})".format(role)
        # Struct with empty CanonicalName → literal from the Color field.
        c = value.get("color", "")
        if c:
            return _uint_to_svg_color(c)
        return None
    # Short-form uint scalar.
    v = str(value).strip()
    if not v:
        return None
    return _uint_to_svg_color(v)


# ---------------------------------------------------------------------------
# XML / SVG escaping
# ---------------------------------------------------------------------------


def _esc_xml(value):
    if value is None:
        return ""
    value = str(value)
    value = value.replace("&", "&amp;")
    value = value.replace("<", "&lt;")
    value = value.replace(">", "&gt;")
    value = value.replace('"', "&quot;")
    return value


def _svg_tag(tag, attrs, body=""):
    """Build an SVG tag string from *tag*, *attrs* dict, and optional *body*."""
    parts = ["<" + tag]
    for key in sorted(attrs):
        v = attrs[key]
        if v is None:
            continue
        parts.append(' {0}="{1}"'.format(key, _esc_xml(str(v))))
    if body:
        parts.append(">")
        parts.append(body)
        parts.append("</{0}>".format(tag))
    else:
        parts.append(" />")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Element rendering  (plan.md §4 element → attribute contract)
# ---------------------------------------------------------------------------

# Member IDs (verified, same values as plan.md §6 and catalog JSONs).
_MID_X = 1649127785
_MID_Y = 357335551
_MID_W = 2422045748
_MID_H = 2134141914
_MID_SHAPE = 564465120
_MID_CORNER_RADIUS = 1869484343
_MID_FILL = 2812299069
_MID_FRAME = 494569607
_MID_FONT_COLOR = 663104332
_MID_BORDER_WIDTH = 2678395525
_MID_TEXT = 390574330
_MID_X1 = 1357360684
_MID_Y1 = 444643082
_MID_X2 = 1837598620
_MID_Y2 = 669032122
_MID_FONT_NAME = 1603690730
_MID_FONT_SIZE = 4253639993


def _render_rect(x, y, w, h, element, rx=None):
    """Render a ``<rect>`` from a simple shape element."""
    fill = _resolve_color_value(_member_value(element, _MID_FILL))
    stroke = _resolve_color_value(_member_value(element, _MID_FRAME))
    _sw = _member_value(element, _MID_BORDER_WIDTH)
    sw = _sw if isinstance(_sw, str) else None

    attrs = {
        "x": str(x),
        "y": str(y),
        "width": str(w),
        "height": str(h),
    }
    if rx is not None:
        attrs["rx"] = str(rx)
    if fill:
        attrs["fill"] = fill
    if stroke:
        attrs["stroke"] = stroke
    if sw:
        try:
            sw_val = int(sw)
            if sw_val > 0:
                attrs["stroke-width"] = str(sw_val)
        except (ValueError, TypeError):
            pass
    return _svg_tag("rect", attrs)


def _render_circle(cx, cy, r, element):
    """Render a ``<circle>`` from a simple shape element (VISU_ST_CIRCLE)."""
    fill = _resolve_color_value(_member_value(element, _MID_FILL))
    stroke = _resolve_color_value(_member_value(element, _MID_FRAME))
    _sw = _member_value(element, _MID_BORDER_WIDTH)
    sw = _sw if isinstance(_sw, str) else None

    attrs = {"cx": str(cx), "cy": str(cy), "r": str(r)}
    if fill:
        attrs["fill"] = fill
    if stroke:
        attrs["stroke"] = stroke
    if sw:
        try:
            sw_val = int(sw)
            if sw_val > 0:
                attrs["stroke-width"] = str(sw_val)
        except (ValueError, TypeError):
            pass
    return _svg_tag("circle", attrs)


def _render_line(element):
    """Render a ``<line>`` from a VisuFbElemLine element."""
    _x1 = _member_value(element, _MID_X1)
    _y1 = _member_value(element, _MID_Y1)
    _x2 = _member_value(element, _MID_X2)
    _y2 = _member_value(element, _MID_Y2)

    stroke = _resolve_color_value(_member_value(element, _MID_FRAME))
    _sw = _member_value(element, _MID_BORDER_WIDTH)

    x1 = _x1 if isinstance(_x1, str) else None
    y1 = _y1 if isinstance(_y1, str) else None
    x2 = _x2 if isinstance(_x2, str) else None
    y2 = _y2 if isinstance(_y2, str) else None
    sw = _sw if isinstance(_sw, str) else None

    attrs = {}
    if x1 is not None:
        attrs["x1"] = x1
    if y1 is not None:
        attrs["y1"] = y1
    if x2 is not None:
        attrs["x2"] = x2
    if y2 is not None:
        attrs["y2"] = y2
    if stroke:
        attrs["stroke"] = stroke
    if sw:
        try:
            sw_val = int(sw)
            if sw_val > 0:
                attrs["stroke-width"] = str(sw_val)
        except (ValueError, TypeError):
            pass
    return _svg_tag("line", attrs)


def _render_label(element):
    """Render a ``<text>`` from a VisuFbLabel element."""
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)
    _text = _member_value(element, _MID_TEXT)

    fill = _resolve_color_value(_member_value(element, _MID_FONT_COLOR))
    _font_name = _member_value(element, _MID_FONT_NAME)
    _font_size = _member_value(element, _MID_FONT_SIZE)

    x = _x if isinstance(_x, str) else None
    y = _y if isinstance(_y, str) else None
    w = _w if isinstance(_w, str) else None
    h = _h if isinstance(_h, str) else None
    text = _text if isinstance(_text, str) else ""
    font_name = _font_name if isinstance(_font_name, str) else None
    font_size = _font_size if isinstance(_font_size, str) else None

    attrs = {}
    if x is not None:
        attrs["x"] = x
    if y is not None:
        attrs["y"] = y
    # Emit bounding-box as data attributes for layout awareness.
    if w is not None:
        attrs["data-width"] = w
    if h is not None:
        attrs["data-height"] = h
    if fill:
        attrs["fill"] = fill
    if font_name:
        attrs["font-family"] = font_name
    if font_size:
        try:
            attrs["font-size"] = str(int(font_size))
        except (ValueError, TypeError):
            attrs["font-size"] = font_size

    body = _esc_xml(text) if text else ""
    return _svg_tag("text", attrs, body)


def _render_textfield(element):
    """Render a ``<text data-cds-type="textfield">`` from a VisuFbElemTextfield."""
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)
    _text = _member_value(element, _MID_TEXT)
    _text_var = _member_value(element, 2477733581)

    fill = _resolve_color_value(_member_value(element, _MID_FONT_COLOR))
    _font_name = _member_value(element, _MID_FONT_NAME)
    _font_size = _member_value(element, _MID_FONT_SIZE)

    x = _x if isinstance(_x, str) else None
    y = _y if isinstance(_y, str) else None
    w = _w if isinstance(_w, str) else None
    h = _h if isinstance(_h, str) else None
    text = _text if isinstance(_text, str) else ""
    text_var = _text_var if isinstance(_text_var, str) else ""
    font_name = _font_name if isinstance(_font_name, str) else None
    font_size = _font_size if isinstance(_font_size, str) else None

    attrs = {"data-cds-type": "textfield"}
    if x is not None:
        attrs["x"] = x
    if y is not None:
        attrs["y"] = y
    if w is not None:
        attrs["data-width"] = w
    if h is not None:
        attrs["data-height"] = h
    if fill:
        attrs["fill"] = fill
    if font_name:
        attrs["font-family"] = font_name
    if font_size:
        try:
            attrs["font-size"] = str(int(font_size))
        except (ValueError, TypeError):
            attrs["font-size"] = font_size
    if text_var:
        attrs["data-text-var"] = text_var

    body = _esc_xml(text) if text else ""
    return _svg_tag("text", attrs, body)


def _render_button(element):
    """Render a button as ``<rect data-cds-type="button">``.

    Caption goes into ``data-text``. Colors are resolved from uint literals
    (set via themeable_colors) or struct + CanonicalName.
    """
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)
    _text = _member_value(element, _MID_TEXT)

    fill = _resolve_color_value(_member_value(element, _MID_FILL))
    stroke = _resolve_color_value(_member_value(element, _MID_FRAME))

    x = _x if isinstance(_x, str) else None
    y = _y if isinstance(_y, str) else None
    w = _w if isinstance(_w, str) else None
    h = _h if isinstance(_h, str) else None
    text = _text if isinstance(_text, str) else ""

    attrs = {"data-cds-type": "button"}
    if x is not None:
        attrs["x"] = x
    if y is not None:
        attrs["y"] = y
    if w is not None:
        attrs["width"] = w
    if h is not None:
        attrs["height"] = h
    if text:
        attrs["data-text"] = text
    if fill:
        attrs["fill"] = fill
    if stroke:
        attrs["stroke"] = stroke
    return _svg_tag("rect", attrs)


def _simple_to_svg(element):
    """Convert a ``VisuFbElemSimple`` element to SVG based on its shape."""
    _shape = _member_value(element, _MID_SHAPE)
    shape = _shape if isinstance(_shape, str) else "VISU_ST_RECTANGLE"

    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)

    x = int(_x) if isinstance(_x, str) else 0
    y = int(_y) if isinstance(_y, str) else 0
    w = int(_w) if isinstance(_w, str) else 0
    h = int(_h) if isinstance(_h, str) else 0

    if shape == "VISU_ST_RECTANGLE":
        return _render_rect(x, y, w, h, element)
    elif shape == "VISU_ST_ROUNDRECT":
        _rx = _member_value(element, _MID_CORNER_RADIUS)
        if isinstance(_rx, str):
            try:
                rx = int(_rx)
            except (ValueError, TypeError):
                rx = None
        else:
            rx = None
        return _render_rect(x, y, w, h, element, rx=rx)
    elif shape == "VISU_ST_CIRCLE":
        cx = x + w // 2
        cy = y + h // 2
        r = min(w, h) // 2
        return _render_circle(cx, cy, r, element)
    else:
        raise SvgExportError("Unsupported shape variant: '{0}'".format(shape))


def _element_to_svg(element):
    """Dispatch a CODESYS visual element to the appropriate SVG renderer."""
    type_name = _named_text(element, "VisualElementTypeName")
    if not type_name:
        raise SvgExportError("Element has no VisualElementTypeName")

    if type_name == "VisuFbElemSimple":
        return _simple_to_svg(element)
    elif type_name == "VisuFbElemLine":
        return _render_line(element)
    elif type_name == "VisuFbLabel":
        return _render_label(element)
    elif type_name == "VisuFbElemButton":
        return _render_button(element)
    elif type_name == "VisuFbElemTextfield":
        return _render_textfield(element)
    else:
        raise SvgExportError(
            "Unsupported element type: '{0}' "
            "(v1 vocabulary: VisuFbElemSimple, VisuFbElemLine, "
            "VisuFbLabel, VisuFbElemButton, VisuFbElemTextfield)".format(type_name)
        )


# ---------------------------------------------------------------------------
# Screen-level helpers
# ---------------------------------------------------------------------------


def _read_background(root):
    """Read the background colour from screen XML.

    Returns ``None`` if no custom background (BgColor=False),
    or a ``#rrggbb`` string if a custom colour is set.
    """
    bg_color_el = None
    use_color_el = None
    for el in root.iter():
        tag = _strip_ns(el.tag)
        if tag == "Single" and el.attrib.get("Name") == "BgColor":
            bg_color_el = el
        elif tag == "Single" and el.attrib.get("Name") == "BgUseColor":
            use_color_el = el
    if bg_color_el is not None and (bg_color_el.text or "").strip() == "True":
        if use_color_el is not None:
            raw = (use_color_el.text or "").strip()
            if raw:
                try:
                    val = int(raw)
                    unsigned = val & 0xFFFFFFFF
                    if (unsigned >> 24) == 0xFF:
                        rgb = unsigned & 0xFFFFFF
                    else:
                        rgb = unsigned
                    return "#{0:06x}".format(rgb)
                except ValueError:
                    pass
    return None


def _read_screen_size(root):
    size_x = size_y = None
    for el in root.iter():
        if _strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeX":
            size_x = int((el.text or "0").strip())
        elif _strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeY":
            size_y = int((el.text or "0").strip())
    if size_x is None or size_y is None:
        raise SvgExportError("Screen XML has no SizeX/SizeY in MetaObject")
    return size_x, size_y


def _load_default_theme():
    """Load the built-in dark theme colors for inline ``:root`` CSS vars."""
    theme_path = os.path.join(_THEME_DIR, "dark.json")
    try:
        with open(theme_path, "r") as f:
            data = json.load(f)
        themes_list = data.get("themes", [])
        if themes_list:
            return themes_list[0].get("style", {}).get("colors", {})
    except (IOError, ValueError, KeyError):
        pass
    return {}


def _format_theme_block(theme_colors):
    """Format a ``:root{ ... }`` CSS block with theme variable declarations."""
    if not theme_colors:
        return ""
    parts = [":root{"]
    for role in sorted(theme_colors):
        hex_val = theme_colors[role]
        # Dotted roles (e.g. ``text.muted``) become hyphenated CSS variables
        # (``--text-muted``).
        css_role = role.replace(".", "-")
        parts.append(" --{0}:{1};".format(css_role, hex_val))
    parts.append("}")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def screen_to_svg(xml_text, theme_colors=None):
    """Convert a CODESYS screen XML string to an SVG string.

    Parameters
    ----------
    xml_text : str
        The raw CODESYS ``.xml`` screen content.
    theme_colors : dict or None
        Optional mapping of role → ``#hex`` for inline ``:root`` CSS
        variables.  When ``None`` (the default) the built-in dark theme
        is loaded.

    Returns
    -------
    str
        The generated SVG document.

    Raises
    ------
    SvgExportError
        If the XML is malformed, a required member is missing, or an
        out-of-vocabulary element type is encountered.
    """
    if theme_colors is None:
        theme_colors = _load_default_theme()

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SvgExportError("Could not parse screen XML: {0}".format(exc))

    # Screen canvas size.
    size_x, size_y = _read_screen_size(root)

    # Background colour.
    bg_hex = _read_background(root)
    bg_style = (
        'style="background:{0}"'.format(bg_hex)
        if bg_hex
        else 'style="background:var(--surface)"'
    )
    velist = None
    for el in root.iter():
        if _strip_ns(el.tag) == "List" and el.attrib.get("Name") == "VisualElementList":
            velist = el
            break

    # Convert each element.
    elements_svg = []
    if velist is not None:
        for child in list(velist):
            if _strip_ns(child.tag) != "Single":
                continue
            try:
                svg = _element_to_svg(child)
                elements_svg.append(svg)
            except SvgExportError:
                raise
            except Exception as exc:
                tname = _named_text(child, "VisualElementTypeName") or "unknown"
                raise SvgExportError(
                    "Error converting element '{0}': {1}".format(tname, exc)
                )

    # Build the ``:root`` CSS block.
    theme_block = _format_theme_block(theme_colors)

    # Assemble the SVG document.
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        '     width="{0}" height="{1}"'.format(size_x, size_y),
        '     viewBox="0 0 {0} {1}"'.format(size_x, size_y),
        "     {0}>".format(bg_style),
    ]
    if theme_block:
        lines.append("  <defs><style>{0}</style></defs>".format(theme_block))
    for elem_svg in elements_svg:
        lines.append("  " + elem_svg)
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
