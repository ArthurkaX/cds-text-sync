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


def _parse_text(elem, theme):
    """Parse a ``<text>`` -> label with caption text."""
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("data-width"), 200)
    h = _float(elem.get("data-height"), 20)
    text_content = (elem.text or "").strip()

    font_color = _resolve(elem.get("fill"), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text_content,
    }

    if font_color is not None:
        params["font_color"] = font_color

    fs = elem.get("font-size")
    if fs is not None:
        params["font_size"] = str(int(_float(fs, 12)))

    ff = elem.get("font-family")
    if ff is not None:
        params["font_name"] = ff

    return {"type": "label", "params": params}


def _parse_button(elem, theme):
    """Parse a ``<rect data-cds-type="button">`` -> button control.

    Per plan section 5, buttons keep their colours style-linked (the golden
    template is not overridden), so fill/frame are intentionally *not* emitted.
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("width"), 100)
    h = _float(elem.get("height"), 100)
    text = elem.get("data-text", "")
    text_id = elem.get("data-text-id", "")

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text,
    }

    if text_id:
        params["text_id"] = text_id

    return {"type": "button", "params": params}


def _parse_textfield(elem, theme):
    """Parse a ``<text data-cds-type="textfield">`` -> textfield control.

    Textfield is like Label but can show runtime variable values.
    ``fill`` controls the font colour (emitted as uint literal).
    """
    x = _float(elem.get("x"), 0)
    y = _float(elem.get("y"), 0)
    w = _float(elem.get("data-width"), 100)
    h = _float(elem.get("data-height"), 100)
    text = elem.text or ""
    text = text.strip() if text else ""
    text_var = elem.get("data-text-var", "")
    font_size = elem.get("font-size", "12")
    font_name = elem.get("font-family", "Arial")

    font_color = _resolve(elem.get("fill"), theme)

    params = {
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(w)),
        "height": str(int(h)),
        "text": text,
        "text_var": text_var,
        "font_size": font_size,
        "font_name": font_name,
    }

    if font_color is not None:
        params["font_color"] = font_color

    return {"type": "textfield", "params": params}


# ---------------------------------------------------------------------------
# Element dispatch table
# ---------------------------------------------------------------------------

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


def parse_svg(svg_text, theme=None):
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

    # Merge: caller-provided theme, then inline overrides on top.
    merged_theme = {}
    if theme is not None:
        merged_theme.update(theme)
    merged_theme.update(inline_theme)

    # -- SVG elements ------------------------------------------------------
    elements = []

    for child in root:
        tag = _strip_ns(child.tag)
        if tag == "defs":
            continue  # already handled by _parse_inline_theme

        # Promote <rect data-cds-type="button"> to button.
        if tag == "rect" and child.get("data-cds-type") == "button":
            elements.append(_parse_button(child, merged_theme))
            continue

        # Promote <text data-cds-type="textfield"> to textfield.
        if tag == "text" and child.get("data-cds-type") == "textfield":
            elements.append(_parse_textfield(child, merged_theme))
            continue

        parser = _ELEMENT_PARSERS.get(tag)
        if parser is None:
            raise ValueError(
                "Unsupported SVG element: <{0}>. Supported: {1}".format(
                    tag, ", ".join(sorted(_SUPPORTED))
                )
            )
        elements.append(parser(child, merged_theme))

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
