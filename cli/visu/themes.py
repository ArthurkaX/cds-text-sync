# -*- coding: utf-8 -*-
"""
themes.py - CODESYS visual style presets and color resolution for SVG import.

The SVG bridge still resolves ``var(--role)`` values to concrete CODESYS color
integers, because imported primitive colors must be literal values to survive a
round-trip reliably.  The preset names, however, are modeled after CODESYS
visualization styles rather than editor themes.  JSON files in
``cli/visu/themes/<name>.json`` are kept as a compatibility extension point.
"""

from __future__ import print_function

import json
import os
import re

_THEME_DIR = os.path.join(os.path.dirname(__file__), "themes")


_STYLE_ROLES = {
    "background": "#F5F5F5",
    "surface": "#FFFFFF",
    "screen.background": "#F5F5F5",
    "screen.surface": "#FFFFFF",
    "panel": "#FFFFFF",
    "panel.frame": "#B8B8B8",
    "panel.header": "#EAEAEA",
    "panel.header.text": "#1F1F1F",
    "border": "#B8B8B8",
    "divider": "#B8B8B8",
    "frame": "#808080",
    "text": "#1F1F1F",
    "text.muted": "#666666",
    "on-surface": "#1F1F1F",
    "custom.fill": "#FFFFFF",
    "custom.frame": "#808080",
    "custom.text": "#1F1F1F",
    "custom.accent.fill": "#007ACC",
    "custom.accent.text": "#FFFFFF",
    "element.active": "#007ACC",
    "focus": "#007ACC",
    "primary": "#007ACC",
    "secondary": "#6A6A6A",
    "accent": "#007ACC",
    "success": "#3A8A3A",
    "warning": "#C47A00",
    "error": "#C9302C",
    "muted": "#7A7A7A",
    "hover": "#E9F3FF",
    "disabled": "#A6A6A6",
    "water": "#2D8CCB",
    "water-dim": "#1F6FA3",
    "metal": "#8C8C8C",
}


def _style_roles(**overrides):
    colors = dict(_STYLE_ROLES)
    colors.update(overrides)
    return _complete_roles(colors)


_DERIVED_ROLES = {
    "screen.background": ("background", "surface"),
    "screen.surface": ("surface", "background"),
    "surface": ("screen.surface", "background"),
    "background": ("screen.background", "surface"),
    "panel": ("panel.header", "surface", "background"),
    "panel.frame": ("border", "frame"),
    "panel.header": ("panel", "surface"),
    "panel.header.text": ("text", "on-surface"),
    "divider": ("border", "frame"),
    "on-surface": ("text",),
    "text.muted": ("muted", "text"),
    "custom.fill": ("panel", "surface"),
    "custom.frame": ("frame", "border"),
    "custom.text": ("text", "on-surface"),
    "custom.accent.fill": ("accent", "primary", "element.active"),
    "custom.accent.text": ("on-surface", "text"),
    "focus": ("element.active", "accent", "primary"),
    "primary": ("accent", "element.active"),
    "accent": ("primary", "element.active"),
}


def _complete_roles(colors):
    """Return colors with semantic layout/custom roles filled in.

    CODESYS owns native controls through visual styles.  These roles are for the
    SVG bridge: screen background, grouping panels, separators, custom shapes,
    and status/attention accents around native controls.
    """
    result = dict(colors or {})
    changed = True
    while changed:
        changed = False
        for role, fallbacks in _DERIVED_ROLES.items():
            if role in result:
                continue
            for fallback in fallbacks:
                if fallback in result:
                    result[role] = result[fallback]
                    changed = True
                    break
    return result


# These presets intentionally use CODESYS visualization style names and
# versions.  The color roles are a compact SVG-preview/import fallback; the
# actual CODESYS project visual style still owns native styled elements.
_CODESYS_STYLES = {
    "flat-style": {
        "display_name": "Flat style",
        "version": "4.9.0.0",
        "vendor": "CODESYS",
        "colors": _style_roles(
            background="#F2F2F2",
            surface="#FFFFFF",
            border="#C7C7C7",
            frame="#7F7F7F",
            primary="#007ACC",
            accent="#007ACC",
            **{"element.active": "#007ACC"}
        ),
    },
    "basic-style": {
        "display_name": "Basic style",
        "version": "4.9.0.0",
        "vendor": "CODESYS",
        "colors": _style_roles(
            background="#DCDCDC",
            surface="#ECECEC",
            border="#8A8A8A",
            frame="#606060",
            primary="#005A9E",
            accent="#005A9E",
            hover="#D6E8F7",
            **{"element.active": "#005A9E"}
        ),
    },
    "default": {
        "display_name": "Default",
        "version": "4.9.0.0",
        "vendor": "CODESYS",
        "colors": _style_roles(),
    },
    "example-for-a-style": {
        "display_name": "Example for a style",
        "version": "4.9.0.0",
        "vendor": "ExampleCompany",
        "colors": _style_roles(
            primary="#2E75B6",
            accent="#70AD47",
            secondary="#5B9BD5",
            **{"element.active": "#70AD47"}
        ),
    },
    "white-style": {
        "display_name": "White style",
        "version": "4.9.0.0",
        "vendor": "CODESYS",
        "colors": _style_roles(
            background="#FFFFFF",
            surface="#FFFFFF",
            panel="#FFFFFF",
            border="#D9D9D9",
            frame="#A6A6A6",
            hover="#F5F5F5",
        ),
    },
    "style-2": {
        "display_name": "Style 2",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#E7E7E7",
            surface="#F2F2F2",
            primary="#336699",
            accent="#336699",
            **{"element.active": "#336699"}
        ),
    },
    "style-3-gradient-linear-1": {
        "display_name": "Style 3, Gradient linear 1",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#E8EEF5",
            surface="#F7FAFD",
            primary="#2F75B5",
            accent="#5B9BD5",
            **{"element.active": "#5B9BD5"}
        ),
    },
    "style-4-gradient-linear-2": {
        "display_name": "Style 4, Gradient linear 2",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#ECECEC",
            surface="#FAFAFA",
            primary="#767171",
            accent="#A5A5A5",
            **{"element.active": "#767171"}
        ),
    },
    "style-5-gradient-axial-1": {
        "display_name": "Style 5, Gradient axial 1",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#E9F0E5",
            surface="#F8FBF6",
            primary="#548235",
            accent="#70AD47",
            **{"element.active": "#70AD47"}
        ),
    },
    "style-6-gradient-axial-2": {
        "display_name": "Style 6, Gradient axial 2",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#F5EDE7",
            surface="#FFF8F3",
            primary="#A65E2E",
            accent="#C55A11",
            **{"element.active": "#C55A11"}
        ),
    },
    "style-7-gradient-double-linear-1": {
        "display_name": "Style 7, Gradient double linear 1",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#EAEAF3",
            surface="#F7F7FC",
            primary="#5F5FA8",
            accent="#7F7FC5",
            **{"element.active": "#7F7FC5"}
        ),
    },
    "style-8-gradient-double-linear-2": {
        "display_name": "Style 8, Gradient double linear 2",
        "version": "3.5.12.0",
        "vendor": "3S-Smart Software Solutions GmbH",
        "colors": _style_roles(
            background="#E8F2F2",
            surface="#F6FCFC",
            primary="#2F7F7F",
            accent="#4BA3A3",
            **{"element.active": "#4BA3A3"}
        ),
    },
}

_STYLE_ALIASES = {
    "flat": "flat-style",
    "flat-style-4.9.0.0": "flat-style",
    "basic": "basic-style",
    "basic-style-4.9.0.0": "basic-style",
    "default-4.9.0.0": "default",
    "example": "example-for-a-style",
    "example-style": "example-for-a-style",
    "white": "white-style",
    "white-style-4.9.0.0": "white-style",
    "style-3": "style-3-gradient-linear-1",
    "gradient-linear-1": "style-3-gradient-linear-1",
    "style-4": "style-4-gradient-linear-2",
    "gradient-linear-2": "style-4-gradient-linear-2",
    "style-5": "style-5-gradient-axial-1",
    "gradient-axial-1": "style-5-gradient-axial-1",
    "style-6": "style-6-gradient-axial-2",
    "gradient-axial-2": "style-6-gradient-axial-2",
    "style-7": "style-7-gradient-double-linear-1",
    "gradient-double-linear-1": "style-7-gradient-double-linear-1",
    "style-8": "style-8-gradient-double-linear-2",
    "gradient-double-linear-2": "style-8-gradient-double-linear-2",
    # Backward-compatible editor-theme names.  They now map to nearby CODESYS
    # styles instead of being the recommended public vocabulary.
    "light": "white-style",
    "dark": "flat-style",
    "hi-contrast": "style-2",
}


class ThemeError(Exception):
    pass


def list_themes():
    """Return sorted list of available CODESYS style preset names."""
    names = set(_CODESYS_STYLES)
    if not os.path.isdir(_THEME_DIR):
        return sorted(names)
    for name in os.listdir(_THEME_DIR):
        if name.endswith(".json"):
            theme_name = name[: -len(".json")]
            if theme_name not in _STYLE_ALIASES:
                names.add(theme_name)
    return sorted(names)


def _normalize_name(name):
    text = str(name or "").strip().lower()
    text = text.replace("<", "").replace(">", "")
    text = re.sub(r"[^0-9a-z]+", "-", text).strip("-")
    for key, style in _CODESYS_STYLES.items():
        display = re.sub(
            r"[^0-9a-z]+", "-", style["display_name"].lower()
        ).strip("-")
        if text == display or text.startswith(display + "-"):
            return key
        if text == key or text.startswith(key + "-"):
            return key
    return _STYLE_ALIASES.get(text, text)


def load_theme(name):
    """Load a CODESYS style preset or JSON theme and return its color roles.

    Returns a dict mapping role->#hex, e.g. {"surface": "#161B22", ...}.
    Raises ThemeError if the theme is not found or malformed.
    """
    if not name:
        raise ThemeError("No theme name given")
    normalized = _normalize_name(name)

    path = os.path.join(_THEME_DIR, "{0}.json".format(normalized))
    if os.path.isfile(path):
        return _load_theme_json(path, name)

    if normalized in _CODESYS_STYLES:
        return _complete_roles(_CODESYS_STYLES[normalized]["colors"])

    legacy_path = os.path.join(_THEME_DIR, "{0}.json".format(str(name).strip()))
    if os.path.isfile(legacy_path):
        return _load_theme_json(legacy_path, name)

    available = ", ".join(list_themes()) or "(none)"
    raise ThemeError("Unknown theme '{0}'. Available: {1}".format(name, available))


def _load_theme_json(path, name):
    """Load a JSON theme file and return its first theme color dictionary."""
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
    return _complete_roles(colors)


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


def resolve_color_unsigned(color_expr, theme_colors):
    """Resolve color expression to an *unsigned* 32-bit int string.

    For use with the short-form uint color emitter.
    """
    unsigned = resolve_color(color_expr, theme_colors)
    if unsigned is None:
        return None
    return str(unsigned)
