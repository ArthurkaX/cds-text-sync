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

import re
import xml.etree.ElementTree as ET
from collections import OrderedDict

from . import style_roles, themes
from .xml_ns import find_named, named_text, strip_ns


class SvgExportError(Exception):
    """Raised on unsupported element types or malformed data."""

    pass


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
    member_container = find_named(element, "Single", "VisualElemMemberList")
    mlist = (
        find_named(member_container, "List", "VisualElemMemberList")
        if member_container is not None
        else None
    )
    if mlist is None:
        return None
    for member in list(mlist):
        if strip_ns(member.tag) != "Single":
            continue
        idc = find_named(member, "Single", "Id")
        if idc is None or not idc.text:
            continue
        mid = int(idc.text.strip())
        if mid != member_id:
            continue

        # Scalar (short-form) value.
        scalar = find_named(member, "Single", "Value")
        if scalar is not None:
            return (scalar.text or "").strip()

        # Struct (color) value.
        listval = find_named(member, "List", "Value")
        if listval is not None:
            inner = list(listval)
            if inner and find_named(inner[0], "Single", "Color") is not None:
                color_el = find_named(inner[0], "Single", "Color")
                cn_el = find_named(inner[0], "Single", "CanonicalName")
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
_MID_H_ALIGN = 2340015797

# Same fallback the builder uses when a label carries no font_size.
_DEFAULT_FONT_SIZE = 12


def _text_geometry(element, y, h, font_size):
    """Invert the import's baseline -> box conversion for a label/textfield.

    A CODESYS text element is a box plus an alignment; an SVG ``<text>`` is a
    baseline plus an anchor, and ``_parse_text`` converts the one into the
    other. Reading the box back out without converting it loses both halves of
    that: every centred caption comes out flush left, and every baseline lands
    one font-size too high. Round-tripping a screen through ``to-svg`` and back
    then moves text the author never touched.

    Only h_align is read. The import derives v_align from it (VCENTER with
    HCENTER, TOP otherwise), so for a sketch-authored screen it carries nothing
    new -- and for a hand-authored LEFT/VCENTER text, deriving the baseline from
    v_align instead would put the glyphs right and move the *box* on recompile.
    Preserving the box is the stronger guarantee.

    Returns ``(text_anchor_or_None, svg_y_string)``.
    """
    _h_align = _member_value(element, _MID_H_ALIGN)
    h_align = _h_align if isinstance(_h_align, str) else ""

    try:
        y_val = float(y)
    except (TypeError, ValueError):
        return None, y

    if h_align == "HCENTER":
        # Import stored y as ``baseline - height/2``; add it back, rounding the
        # half-pixel an odd height leaves behind so the value survives a trip.
        try:
            return "middle", str(int(y_val + float(h) / 2 + 0.5))
        except (TypeError, ValueError):
            return "middle", str(int(y_val))

    try:
        fs = int(float(font_size))
    except (TypeError, ValueError):
        fs = _DEFAULT_FONT_SIZE
    anchor = "end" if h_align == "RIGHT" else None
    return anchor, str(int(y_val + fs))


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
        anchor, y = _text_geometry(element, y, h, font_size)
        attrs["y"] = y
        if anchor:
            attrs["text-anchor"] = anchor
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
        anchor, y = _text_geometry(element, y, h, font_size)
        attrs["y"] = y
        if anchor:
            attrs["text-anchor"] = anchor
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


# Reverse of _LAMP_COLOR_ROLES in svg_import: role suffix -> friendly colour.
_LAMP_ROLE_COLORS = {
    "Red": "red",
    "Green": "green",
    "Yellow": "yellow",
    "Blue": "blue",
    "Gray": "gray",
}


def _render_lamp(element):
    """Render a ``<rect data-cds-type="lamp">`` from a VisuFbElemLamp element."""
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)
    _role = _member_value(element, 4062784938)
    _var = _member_value(element, 743958181)

    attrs = {"data-cds-type": "lamp"}
    if isinstance(_x, str):
        attrs["x"] = _x
    if isinstance(_y, str):
        attrs["y"] = _y
    if isinstance(_w, str):
        attrs["width"] = _w
    if isinstance(_h, str):
        attrs["height"] = _h

    # Map the style role (e.g. 'Element-Lamp-Lamp1-Red') back to a colour.
    if isinstance(_role, str) and _role:
        suffix = _role.rsplit("-", 1)[-1]
        color = _LAMP_ROLE_COLORS.get(suffix)
        if color:
            attrs["data-color"] = color
    if isinstance(_var, str) and _var:
        attrs["data-var"] = _var

    return _svg_tag("rect", attrs)



def _render_image_switcher(element):
    """Render a <rect data-cds-type="image-switcher"> from a VisuFbImageSwitcher element."""
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)
    _image_on = _member_value(element, 427565733)
    _image_off = _member_value(element, 296037572)
    _var = _member_value(element, 743958181)

    attrs = {"data-cds-type": "image-switcher"}
    if isinstance(_x, str):
        attrs["x"] = _x
    if isinstance(_y, str):
        attrs["y"] = _y
    if isinstance(_w, str):
        attrs["width"] = _w
    if isinstance(_h, str):
        attrs["height"] = _h
    if isinstance(_image_on, str) and _image_on:
        attrs["data-image-on"] = _image_on
    if isinstance(_image_off, str) and _image_off:
        attrs["data-image-off"] = _image_off
    if isinstance(_var, str) and _var:
        attrs["data-var"] = _var

    return _svg_tag("rect", attrs)


def _render_combobox(element):
    """Render a <rect data-cds-type="combobox"> from a VisuFbComboBoxInteger element."""
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)
    _items = _member_value(element, 2114174855)
    _var = _member_value(element, 397264524)

    attrs = {"data-cds-type": "combobox"}
    if isinstance(_x, str):
        attrs["x"] = _x
    if isinstance(_y, str):
        attrs["y"] = _y
    if isinstance(_w, str):
        attrs["width"] = _w
    if isinstance(_h, str):
        attrs["height"] = _h
    if isinstance(_items, str) and _items:
        attrs["data-items"] = _items
    if isinstance(_var, str) and _var:
        attrs["data-var"] = _var

    return _svg_tag("rect", attrs)


def _render_frame(element):
    """Render a ``<rect data-cds-type="frame">`` from a VisuFbFrame element."""
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)

    attrs = {"data-cds-type": "frame"}

    # Build parent map for navigating descendants.
    parents = {c: p for p in element.iter() for c in p}

    # Find first non-null VisNodeRefs33.
    visu_name = None
    holder = None
    for child in element.iter():
        if strip_ns(child.tag) == "Single" and child.attrib.get("Name") == "VisNodeRefs33":
            text = (child.text or "").strip()
            if text:
                visu_name = text
                holder = parents.get(child)
                break

    if visu_name:
        attrs["data-visu"] = visu_name

    # Extract params from the holder's direct-child TypeNodeChildren.
    if holder is not None:
        for direct_child in list(holder):
            if strip_ns(direct_child.tag) == "List" and direct_child.attrib.get("Name") == "TypeNodeChildren":
                for param_node in list(direct_child):
                    if strip_ns(param_node.tag) != "Single":
                        continue
                    param_name_el = find_named(param_node, "Single", "TypeNodeName")
                    param_id_el = find_named(param_node, "Single", "TypeNodeIdLong")
                    if param_name_el is None or param_id_el is None:
                        continue
                    param_name = (param_name_el.text or "").strip()
                    if not param_name:
                        continue
                    try:
                        param_id = int(param_id_el.text.strip())
                    except (ValueError, TypeError):
                        continue
                    param_value = _member_value(element, param_id)
                    if param_value:
                        attrs["data-param-" + param_name] = param_value

    # Geometry attributes (mirror _render_combobox style).
    if isinstance(_x, str):
        attrs["x"] = _x
    if isinstance(_y, str):
        attrs["y"] = _y
    if isinstance(_w, str):
        attrs["width"] = _w
    if isinstance(_h, str):
        attrs["height"] = _h

    return _svg_tag("rect", attrs)


def _render_slider(element):
 """Render a <rect data-cds-type="slider"> from a VisuFbElemSlider element."""
 _x = _member_value(element, _MID_X)
 _y = _member_value(element, _MID_Y)
 _w = _member_value(element, _MID_W)
 _h = _member_value(element, _MID_H)
 _var = _member_value(element, 397264524)
 _orientation = _member_value(element, 2640826223)
 _min = _member_value(element, 1404881523)
 _max = _member_value(element, 3837067714)

 attrs = {"data-cds-type": "slider"}
 if isinstance(_x, str):
  attrs["x"] = _x
 if isinstance(_y, str):
  attrs["y"] = _y
 if isinstance(_w, str):
  attrs["width"] = _w
 if isinstance(_h, str):
  attrs["height"] = _h
 if isinstance(_var, str) and _var:
  attrs["data-var"] = _var
 if isinstance(_orientation, str) and _orientation:
  attrs["data-orientation"] = _orientation
 if isinstance(_min, str) and _min:
  attrs["data-min"] = _min
 if isinstance(_max, str) and _max:
  attrs["data-max"] = _max

 return _svg_tag("rect", attrs)


def _render_alarm_banner(element):
    """Render a ``<rect data-cds-type="alarm-banner">`` from a VisuFbElemAlarmBanner element.

    Geometry only -- no bound variable, no extra params.
    """
    _x = _member_value(element, _MID_X)
    _y = _member_value(element, _MID_Y)
    _w = _member_value(element, _MID_W)
    _h = _member_value(element, _MID_H)

    attrs = {"data-cds-type": "alarm-banner"}
    if isinstance(_x, str):
        attrs["x"] = _x
    if isinstance(_y, str):
        attrs["y"] = _y
    if isinstance(_w, str):
        attrs["width"] = _w
    if isinstance(_h, str):
        attrs["height"] = _h

    return _svg_tag("rect", attrs)


# ConfiguredComplexInputs / VisualElementInputActions, read back the way
# svg_import writes them (see catalog/input_actions.json).
_MID_INPUT_VARIABLE = 1186196937

# SignatureName -> the ``data-cds-action`` word _parse_complex_action expects.
_COMPLEX_INPUT_WORDS = {
    "Visu_TapInput": "TAP",
    "Visu_ToggleInput": "TOGGLE",
}

# Action type GUID prefix -> (field to read, body template) for
# _parse_event_action. Dialog actions are handled by _read_dialog_action.
_EVENT_ACTION_BODIES = {
    "{6302d3fe": ("STSnippet", "ST {0}"),
    "{9dcc475d": ("ToggleVariable", "toggle {0}"),
    "{b4c3a27b": ("Assign33", "screen {0}"),
}


def _read_input_actions(element, skip_events):
    """Recover an element's input wiring as ``data-cds-action`` clauses.

    ``from-svg`` splits a button's behaviour across two places: tap and toggle
    land in ConfiguredComplexInputs, and the per-event actions in
    VisualElementInputActions. Reading neither back gave a decompiled sketch
    buttons that look right and do nothing -- and recompiling that sketch
    stripped the wiring out of a screen that had it.

    *skip_events* suppresses the event actions when :func:`_read_dialog_action`
    has already claimed them, so a dialog button does not emit its ST snippet
    twice.

    Returns the list of clauses, in the order ``data-cds-action`` joins them.
    """
    clauses = []

    configured = find_named(element, "Array", "ConfiguredComplexInputs")
    for entry in list(configured) if configured is not None else []:
        if strip_ns(entry.tag) != "Single":
            continue
        word = _COMPLEX_INPUT_WORDS.get(named_text(entry, "SignatureName"))
        variable = _member_value(entry, _MID_INPUT_VARIABLE)
        if word and isinstance(variable, str) and variable:
            clauses.append("{0} {1}".format(word, variable))

    if skip_events:
        return clauses

    actions = find_named(element, "Dictionary", "VisualElementInputActions")
    for entry in list(actions) if actions is not None else []:
        if strip_ns(entry.tag) != "Entry":
            continue
        key_el = _find_child(entry, "Key")
        value_el = _find_child(entry, "Value")
        if key_el is None or value_el is None:
            continue
        event = _first_single_text(key_el)
        array = _find_child(value_el, "Array")
        if not event or array is None:
            continue
        for action in list(array):
            if strip_ns(action.tag) != "Single":
                continue
            for prefix, (field, template) in _EVENT_ACTION_BODIES.items():
                if not action.attrib.get("Type", "").startswith(prefix):
                    continue
                value = named_text(action, field)
                if value:
                    clauses.append(
                        "{0}: {1}".format(event, template.format(value))
                    )
                break

    return clauses


def _find_child(parent, tag_name):
    """First direct child of *parent* with *tag_name*, ignoring any Name."""
    for child in list(parent):
        if strip_ns(child.tag) == tag_name:
            return child
    return None


def _first_single_text(parent):
    """Text of the first ``<Single>`` directly under *parent*."""
    child = _find_child(parent, "Single")
    return (child.text or "").strip() if child is not None and child.text else ""


def _read_dialog_action(element):
    """Read dialog-open action info from an element's VisualElementInputActions.

    Returns a dict with keys ``dialog``, ``modal``, ``centered``, ``st``
    if a dialog-open action is found, or ``None`` otherwise.
    """
    # Find the VisualElementInputActions dictionary.
    actions_dict = None
    for child in element.iter():
        if strip_ns(child.tag) == "Dictionary" and child.attrib.get(
            "Name"
        ) == "VisualElementInputActions":
            actions_dict = child
            break
    if actions_dict is None:
        return None

    # Scan all Singles within the dictionary for the dialog-open action
    # (Type {c01cd804...}) and an optional ST-snippet action (Type {6302d3fe...}).
    dialog_action = None
    st_action = None
    for el in actions_dict.iter():
        if strip_ns(el.tag) != "Single":
            continue
        t = el.attrib.get("Type", "")
        if t.startswith("{c01cd804"):
            dialog_action = el
        elif t.startswith("{6302d3fe"):
            st_action = el

    if dialog_action is None:
        return None

    dialog_name = named_text(dialog_action, "Dialog33")
    if not dialog_name:
        return None

    open_modal = find_named(dialog_action, "Single", "OpenModal")
    modal = (
        (open_modal.text or "").strip().lower()
        if open_modal is not None
        else None
    )

    open_centered = find_named(dialog_action, "Single", "OpenCentered")
    centered = (
        (open_centered.text or "").strip().lower()
        if open_centered is not None
        else None
    )

    st = None
    if st_action is not None:
        st_snippet = find_named(st_action, "Single", "STSnippet")
        if st_snippet is not None and st_snippet.text:
            st = st_snippet.text.strip()

    # Read Parameters dict (only non-empty values, sparse).
    params = OrderedDict()
    params_dict = find_named(dialog_action, "Dictionary", "Parameters")
    if params_dict is not None:
        for entry in list(params_dict):
            if strip_ns(entry.tag) != "Entry":
                continue
            key_el = val_el = None
            for child in list(entry):
                if strip_ns(child.tag) == "Key":
                    key_el = child
                elif strip_ns(child.tag) == "Value":
                    val_el = child
            if key_el is None or val_el is None:
                continue
            # Extract text from the first <Single> inside Key/Value.
            key_text = ""
            val_text = ""
            for sub in list(key_el):
                if strip_ns(sub.tag) == "Single":
                    key_text = (sub.text or "").strip()
                    break
            for sub in list(val_el):
                if strip_ns(sub.tag) == "Single":
                    val_text = (sub.text or "").strip()
                    break
            if key_text and val_text:
                params[key_text] = val_text

    return {
        "dialog": dialog_name,
        "modal": modal,
        "centered": centered,
        "st": st,
        "params": params,
    }


def _inject_dialog_attrs(tag_str, info):
    """Inject dialog-related data attributes into an SVG tag string.

    Inserts ``data-open-dialog``, ``data-dialog-modal``,
    ``data-dialog-centered``, and ``data-dialog-st`` attributes just before
    the closing ``/>`` or ``>`` of the opening tag.  Works for both
    self-closing tags (``<rect .../>``) and bodied tags (``<text ...>body</text>``).
    """
    parts = []
    if info.get("dialog"):
        parts.append('data-open-dialog="{0}"'.format(_esc_xml(info["dialog"])))
    if info.get("modal") is not None:
        parts.append('data-dialog-modal="{0}"'.format(info["modal"]))
    if info.get("centered") is not None:
        parts.append('data-dialog-centered="{0}"'.format(info["centered"]))
    if info.get("st") is not None:
        parts.append('data-dialog-st="{0}"'.format(_esc_xml(info["st"])))
    if info.get("params"):
        for name, expr in info["params"].items():
            parts.append('data-dialog-param-{0}="{1}"'.format(
                _esc_xml(name), _esc_xml(expr)))
    return _inject_attrs(tag_str, parts)


def _inject_attrs(tag_str, parts):
    """Append rendered ``name="value"`` *parts* to an SVG tag's opening tag.

    Works for both self-closing tags (``<rect .../>``) and bodied ones
    (``<text ...>body</text>``).
    """
    if not parts:
        return tag_str

    attrs = " " + " ".join(parts)

    m = re.match(r"^(<\w+\b[^>]*?)(\s*/?>)(.*)$", tag_str, re.DOTALL)
    if m:
        return m.group(1) + attrs + m.group(2) + (m.group(3) or "")
    return tag_str


def _element_to_svg(element):
    """Dispatch a CODESYS visual element to the appropriate SVG renderer."""
    type_name = named_text(element, "VisualElementTypeName")
    if not type_name:
        raise SvgExportError("Element has no VisualElementTypeName")

    if type_name == "VisuFbElemSimple":
        svg = _simple_to_svg(element)
    elif type_name == "VisuFbElemLine":
        svg = _render_line(element)
    elif type_name == "VisuFbLabel":
        svg = _render_label(element)
    elif type_name == "VisuFbElemButton":
        svg = _render_button(element)
    elif type_name == "VisuFbElemTextfield":
        svg = _render_textfield(element)
    elif type_name == "VisuFbElemLamp":
        svg = _render_lamp(element)
    elif type_name == "VisuFbImageSwitcher":
        svg = _render_image_switcher(element)
    elif type_name == "VisuFbComboBoxInteger":
        svg = _render_combobox(element)
    elif type_name == "VisuFbElemAlarmBanner":
        svg = _render_alarm_banner(element)
    elif type_name == "VisuFbFrame":
        svg = _render_frame(element)
    elif type_name == "VisuFbElemSlider":
        svg = _render_slider(element)
    else:
        raise SvgExportError(
            "Unsupported element type: '{0}' "
            "(v1 vocabulary: VisuFbElemSimple, VisuFbElemLine, "
            "VisuFbLabel, VisuFbElemButton, VisuFbElemTextfield, "
            "VisuFbElemLamp, VisuFbImageSwitcher, "
            "VisuFbComboBoxInteger, "
            "VisuFbElemAlarmBanner, "
            "VisuFbElemSlider, "
            "VisuFbFrame)".format(type_name)
        )

    # Cross-cutting: inject dialog-open data attributes.
    info = _read_dialog_action(element)
    if info is not None:
        svg = _inject_dialog_attrs(svg, info)

    # Cross-cutting: recover tap / toggle / event wiring.
    clauses = _read_input_actions(element, skip_events=info is not None)
    if clauses:
        svg = _inject_attrs(
            svg, ['data-cds-action="{0}"'.format(_esc_xml(" || ".join(clauses)))]
        )
    return svg


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
        tag = strip_ns(el.tag)
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
        if strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeX":
            size_x = int((el.text or "0").strip())
        elif strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeY":
            size_y = int((el.text or "0").strip())
    if size_x is None or size_y is None:
        raise SvgExportError("Screen XML has no SizeX/SizeY in MetaObject")
    return size_x, size_y


def _load_default_theme(scheme="light"):
    """Load the default CODESYS style colors for inline ``:root`` CSS vars."""
    try:
        return themes.load_theme("flat-style", scheme)
    except themes.ThemeError:
        return {}


def _infer_scheme(bg_hex):
    """Guess the colour scheme of a compiled screen from its background.

    A compiled screen does not record which scheme produced it -- the two
    differ only in the colours they resolved to. The background is the one
    member that always carries the answer: the curated ``screen`` role is
    ``#F4F5F7`` in light and ``#10141A`` in dark, so its luminance separates
    them with room to spare.

    A screen with no custom background (``BgColor=False``) reads as ``light``,
    matching :func:`svg_import.read_scheme`'s own fallback for a sketch with no
    attribute. A hand-set dark background on an otherwise light screen will
    read as dark -- pass an explicit *scheme* to :func:`screen_to_svg` when the
    guess is wrong.
    """
    if not bg_hex:
        return "light"
    raw = bg_hex.lstrip("#")
    if len(raw) != 6:
        return "light"
    try:
        red, green, blue = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "light"
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "dark" if luminance < 128 else "light"


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


def screen_to_svg(xml_text, theme_colors=None, scheme=None):
    """Convert a CODESYS screen XML string to an SVG string.

    Parameters
    ----------
    xml_text : str
        The raw CODESYS ``.xml`` screen content.
    theme_colors : dict or None
        Optional mapping of role → ``#hex`` for inline ``:root`` CSS
        variables.  When ``None`` (the default) the built-in CODESYS
        ``flat-style`` preset
        is loaded.
    scheme : str or None
        ``light`` / ``dark``. ``None`` (the default) infers it from the
        screen's background -- see :func:`_infer_scheme`. A dark result is
        stamped on the root as ``data-cds-scheme``, so recompiling the
        decompiled sketch reproduces the screen it came from; light is left
        unstamped, matching what ``cts visu new`` writes.

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
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SvgExportError("Could not parse screen XML: {0}".format(exc))

    # Screen canvas size.
    size_x, size_y = _read_screen_size(root)

    # Background colour. Read before the theme is loaded: it is what tells the
    # two schemes apart, and the theme's curated roles depend on the answer.
    bg_hex = _read_background(root)
    resolved_scheme = (
        style_roles.normalize_scheme(scheme)
        if scheme is not None
        else _infer_scheme(bg_hex)
    )
    if theme_colors is None:
        theme_colors = _load_default_theme(resolved_scheme)

    bg_style = (
        'style="background:{0}"'.format(bg_hex)
        if bg_hex
        else 'style="background:var(--surface)"'
    )
    velist = None
    for el in root.iter():
        if strip_ns(el.tag) == "List" and el.attrib.get("Name") == "VisualElementList":
            velist = el
            break

    # Convert each element.
    elements_svg = []
    if velist is not None:
        for child in list(velist):
            if strip_ns(child.tag) != "Single":
                continue
            try:
                svg = _element_to_svg(child)
                elements_svg.append(svg)
            except SvgExportError:
                raise
            except Exception as exc:
                tname = named_text(child, "VisualElementTypeName") or "unknown"
                raise SvgExportError(
                    "Error converting element '{0}': {1}".format(tname, exc)
                )

    # Build the ``:root`` CSS block.
    theme_block = _format_theme_block(theme_colors)

    # Only a non-default scheme is stamped -- same rule as ``cts visu new``.
    scheme_attr = (
        ' data-cds-scheme="{0}"'.format(resolved_scheme)
        if resolved_scheme != "light"
        else ""
    )

    # Assemble the SVG document.
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        '     width="{0}" height="{1}"'.format(size_x, size_y),
        '     viewBox="0 0 {0} {1}"'.format(size_x, size_y),
        "     {0}{1}>".format(bg_style, scheme_attr),
    ]
    if theme_block:
        lines.append("  <defs><style>{0}</style></defs>".format(theme_block))
    for elem_svg in elements_svg:
        lines.append("  " + elem_svg)
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
