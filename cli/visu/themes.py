# -*- coding: utf-8 -*-
"""
themes.py - Theme loading and color resolution for SVG->CODESYS conversion.

Theme files live in ``cli/visu/themes/<name>.json`` and follow the schema
defined in plan.md (section 0, D6). SVG references role colors via
``var(--role)`` (dotted roles use hyphens: ``var(--text-muted)``).
"""

from __future__ import print_function

import json
import os
import re

_THEME_DIR = os.path.join(os.path.dirname(__file__), "themes")


class ThemeError(Exception):
    pass


def list_themes():
    """Return sorted list of available theme names."""
    names = []
    if not os.path.isdir(_THEME_DIR):
        return names
    for name in os.listdir(_THEME_DIR):
        if name.endswith(".json"):
            names.append(name[: -len(".json")])
    return sorted(names)


def load_theme(name):
    """Load a theme JSON and return its first theme's color dict.

    Returns a dict mapping role->#hex, e.g. {"surface": "#161B22", ...}.
    Raises ThemeError if the theme is not found or malformed.
    """
    if not name:
        raise ThemeError("No theme name given")
    path = os.path.join(_THEME_DIR, "{0}.json".format(name))
    if not os.path.isfile(path):
        available = ", ".join(list_themes()) or "(none)"
        raise ThemeError("Unknown theme '{0}'. Available: {1}".format(name, available))
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    themes_list = data.get("themes", [])
    if not themes_list:
        raise ThemeError("Theme '{0}' has no theme entries".format(name))
    colors = themes_list[0].get("style", {}).get("colors", {})
    if not colors:
        raise ThemeError("Theme '{0}' has no style.colors".format(name))
    return colors


# ---------------------------------------------------------------------------
# Color resolution
# ---------------------------------------------------------------------------

_CSS_VAR_RE = re.compile(r"var\(--([^)]+)\)")


def resolve_color(color_expr, theme_colors):
    """Resolve a color expression to an ARGB unsigned 32-bit integer.

    Accepts:
      - ``var(--role)`` -> looked up in ``theme_colors`` dict.
      - ``#RRGGBB`` or ``#RRGGBBAA`` -> parsed directly.
      - A plain integer string (already encoded).

    Returns the unsigned 32-bit integer (0xAARRGGBB).
    """
    if color_expr is None:
        return None
    text = str(color_expr).strip()
    if not text:
        return None

    # var(--role) resolution.
    m = _CSS_VAR_RE.match(text)
    if m:
        role = m.group(1).replace("-", ".")  # var(--text-muted) -> text.muted
        hex_val = theme_colors.get(role)
        if hex_val is None:
            raise ThemeError(
                "Color role '--{0}' not found in theme (roles: {1})".format(
                    m.group(1), ", ".join(sorted(theme_colors))
                )
            )
        text = hex_val

    # Parse hex to unsigned 32-bit ARGB.
    raw = text
    if raw.startswith("#"):
        raw = raw[1:]
    elif raw.lower().startswith("0x"):
        raw = raw[2:]
    if re.match(r"^[0-9a-fA-F]{1,8}$", raw):
        argb = int(raw, 16)
        if len(raw) <= 6:
            argb |= 0xFF000000  # opaque
        return argb & 0xFFFFFFFF
    # Already numeric (e.g. from plan_1 testing).
    try:
        val = int(text)
        return val & 0xFFFFFFFF
    except ValueError:
        raise ThemeError("Cannot resolve color expression: '{0}'".format(color_expr))


def resolve_color_signed(color_expr, theme_colors):
    """Resolve color expression to a *signed* 32-bit int string.

    For use with the struct-based color emitter (_render_color_member).
    """
    unsigned = resolve_color(color_expr, theme_colors)
    if unsigned is None:
        return None
    if unsigned >= 0x80000000:
        signed = unsigned - 0x100000000
    else:
        signed = unsigned
    return str(signed)


def resolve_color_unsigned(color_expr, theme_colors):
    """Resolve color expression to an *unsigned* 32-bit int string.

    For use with the uint emitter (_render_color_uint).
    """
    unsigned = resolve_color(color_expr, theme_colors)
    if unsigned is None:
        return None
    return str(unsigned)
