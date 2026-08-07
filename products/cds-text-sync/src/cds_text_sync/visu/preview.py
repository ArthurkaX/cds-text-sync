# -*- coding: utf-8 -*-
"""
preview.py - Render a parsed SVG sketch the way CODESYS will paint it.

The authored sketch is deliberately colourless: an author writes
``class="pipe-water"``, never a hex. That makes the source file portable across
visual styles, but it also means opening the sketch in any SVG viewer shows
black shapes on white -- nothing like the screen that lands in the IDE. So
neither a human reviewer nor an authoring model could see the result before
importing it.

This module closes that loop. It renders from the **parsed ElementSpec list**
(``svg_import.parse_svg``), not from the sketch source, and asks
``builder._resolve_golden_colors`` for the very colours the compiler will emit.
Preview and compile therefore cannot disagree about geometry, colour, or the
baseline-to-top-left conversion: there is one resolution path, used twice.

Rasterisation is delegated to a headless Chromium (Chrome or Edge) when one is
installed. Without a browser the resolved SVG is still written, and that alone
is viewable.
"""

from __future__ import print_function

import os
import subprocess
import sys

from . import builder as _builder
from . import catalog as _catalog

# Roles a native control borrows from the CODESYS visual style. The compiler
# leaves these colours unset (``None``) so the style owns them at runtime; the
# preview has to put *something* on screen, so it samples the same roles the
# style anchors would resolve to.
_NATIVE_ROLES = {
    "button": {"fill": "button.fill", "frame": "frame", "text": "button.text"},
    "textfield": {"fill": "field.fill", "frame": "field.frame", "text": "field.text"},
    "combobox": {"fill": "field.fill", "frame": "field.frame", "text": "field.text"},
    "alarm-banner": {"fill": "alarm.fill", "frame": "alarm.frame", "text": "text.bright"},
    "image-switcher": {"fill": "panel", "frame": "frame", "text": "text.muted"},
    "frame": {"fill": "panel", "frame": "frame", "text": "text.muted"},
}

_LAMP_HEX = {
    "Element-Lamp-Lamp1-Red": "#D64545",
    "Element-Lamp-Lamp1-Green": "#4CAF50",
    "Element-Lamp-Lamp1-Yellow": "#E0B020",
    "Element-Lamp-Lamp1-Blue": "#3F7FD6",
    "Element-Lamp-Lamp1-Gray": "#A8AEB6",
}

_DEFAULT_FONT = "Arial, Helvetica, sans-serif"


class PreviewError(Exception):
    pass


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def uint_to_rgba(value):
    """``"4278190080"`` -> ``("#RRGGBB", alpha_float)``; ``None`` -> ``(None, 0)``."""
    if value is None or value == "":
        return None, 0.0
    try:
        n = int(str(value).strip()) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None, 0.0
    a = (n >> 24) & 0xFF
    r = (n >> 16) & 0xFF
    g = (n >> 8) & 0xFF
    b = n & 0xFF
    return "#{0:02X}{1:02X}{2:02X}".format(r, g, b), a / 255.0


def _role_hex(theme_colors, role, fallback):
    """Look up a role in the palette, accepting dotted or hyphenated spelling."""
    for key in (role, role.replace(".", "-")):
        val = (theme_colors or {}).get(key)
        if val:
            return val
    return fallback


def _is_dark(scheme):
    """True when *scheme* names the dark palette."""
    from . import style_roles as _style_roles

    return _style_roles.normalize_scheme(scheme) == "dark"


def _esc(text):
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _num(params, key, default=0):
    try:
        return int(float(params.get(key, default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Element rendering
# ---------------------------------------------------------------------------


def _resolved_colors(spec, theme_colors, scheme="light"):
    """Ask the compiler for this element's (fill, frame, font) colours.

    ``fill``/``frame`` come back ``None`` for native controls, which is the
    compiler saying "the CODESYS visual style owns this". The preview
    substitutes the role that style anchor points at.

    *scheme* is handed straight to the compiler so the preview asks the same
    question the compile step will: in ``dark`` the native controls resolve to a
    literal here too, instead of the preview arriving at the same colour by a
    different route and only appearing to agree.
    """
    type_name = spec.get("type")
    params = spec.get("params", {})
    try:
        cat = _catalog.load_catalog(type_name)
    except Exception:
        cat = {"type": type_name, "themeable_colors": {}}
    fill_uint, frame_uint, font_uint = _builder._resolve_golden_colors(
        cat, params, theme_colors, scheme
    )
    fill, fill_a = uint_to_rgba(fill_uint)
    frame, frame_a = uint_to_rgba(frame_uint)
    font, _font_a = uint_to_rgba(font_uint)

    native = _NATIVE_ROLES.get(type_name)
    if native:
        # Fallbacks come from the palette first: a hard-coded light grey here is
        # what turns one missing role into a light patch on a dark screen.
        if fill is None:
            fill = _role_hex(
                theme_colors, native["fill"], _role_hex(theme_colors, "panel", "#DDDDDD")
            )
            fill_a = 1.0
        if frame is None:
            frame = _role_hex(
                theme_colors, native["frame"], _role_hex(theme_colors, "frame", "#808080")
            )
            frame_a = 1.0
        if type_name in ("button", "alarm-banner"):
            font = _role_hex(
                theme_colors,
                native["text"],
                _role_hex(theme_colors, "text.bright", "#FFFFFF"),
            )
    return fill, fill_a, frame, frame_a, font


def _paint(fill, fill_a, frame, frame_a, stroke_width=1):
    """Build the fill/stroke attribute string shared by every shape."""
    out = []
    if fill and fill_a > 0:
        out.append('fill="{0}"'.format(fill))
        if fill_a < 1.0:
            out.append('fill-opacity="{0:.3f}"'.format(fill_a))
    else:
        out.append('fill="none"')
    if frame and frame_a > 0:
        out.append('stroke="{0}" stroke-width="{1}"'.format(frame, stroke_width))
        if frame_a < 1.0:
            out.append('stroke-opacity="{0:.3f}"'.format(frame_a))
    return " ".join(out)


def _text_node(params, x, y, w, h, color, size, content, weight=None, inset=0):
    """Place text inside a box using the CODESYS h_align / v_align semantics.

    *inset* is the gap a native control keeps between its frame and its value --
    real for a textfield, and 0 for a plain label, which CODESYS draws flush.
    Charging every label 2px made the preview disagree with the sketch about the
    one thing an author reads a preview for: a label written ``x="48"`` came
    back drawn at 50, so lining it up with a card edge always looked 2px wrong.
    """
    h_align = (params.get("h_align") or "LEFT").upper()
    v_align = (params.get("v_align") or "TOP").upper()

    if h_align == "HCENTER":
        tx, anchor = x + w / 2.0, "middle"
    elif h_align == "RIGHT":
        tx, anchor = x + w - inset, "end"
    else:
        tx, anchor = x + inset, "start"

    if v_align == "VCENTER":
        ty = y + h / 2.0 + size * 0.36
    elif v_align == "BOTTOM":
        ty = y + h - 2
    else:
        ty = y + size

    font = params.get("font_name") or _DEFAULT_FONT
    if font and "," not in font:
        font = "{0}, {1}".format(font, _DEFAULT_FONT)
    extra = ' font-weight="{0}"'.format(weight) if weight else ""
    return (
        '<text x="{0:.1f}" y="{1:.1f}" font-family="{2}" font-size="{3}" '
        'fill="{4}" text-anchor="{5}"{6}>{7}</text>'.format(
            tx, ty, _esc(font), size, color or "#000000", anchor, extra, _esc(content)
        )
    )


def _render_rectangle(params, context):
    x, y, w, h, paint = context[:5]
    shape = (params.get("shape") or "rectangle").lower()
    if shape == "ellipse":
        return ['<ellipse cx="{0:.1f}" cy="{1:.1f}" rx="{2:.1f}" ry="{3:.1f}" {4}/>'.format(
            x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0, paint)]
    radius = _num(params, "corner_radius") if shape == "rounded" else 0
    return ['<rect x="{0}" y="{1}" width="{2}" height="{3}" rx="{4}" {5}/>'.format(
        x, y, w, h, radius, paint)]


def _render_line(params, context):
    x, y, w, h, _paint_value = context[:5]
    fill, _fill_a, frame = context[5], context[6], context[7]
    colour = frame or fill or "#000000"
    return ['<line x1="{0}" y1="{1}" x2="{2}" y2="{3}" stroke="{4}" stroke-width="1"/>'.format(
        _num(params, "x1", x), _num(params, "y1", y),
        _num(params, "x2", x + w), _num(params, "y2", y + h), colour)]


def _render_label(params, context):
    x, y, w, h, paint, fill, fill_a, frame, frame_a, font, theme_colors = context
    out = []
    if (fill and fill_a > 0) or (frame and frame_a > 0):
        out.append('<rect x="{0}" y="{1}" width="{2}" height="{3}" {4}/>'.format(x, y, w, h, paint))
    out.append(_text_node(params, x, y, w, h, font, _num(params, "font_size", 12), params.get("text", "")))
    return out


def _render_button(params, context):
    x, y, w, h, paint, _fill, _fill_a, _frame, _frame_a, font, _theme = context
    caption = dict(params, h_align="HCENTER", v_align="VCENTER")
    return [
        '<rect x="{0}" y="{1}" width="{2}" height="{3}" rx="2" {4}/>'.format(x, y, w, h, paint),
        _text_node(caption, x, y, w, h, font, _num(params, "font_size", 12), params.get("text", "")),
    ]


def _render_textfield(params, context):
    x, y, w, h, paint, _fill, _fill_a, _frame, _frame_a, font, _theme = context
    shown = params.get("text") or ("%s" if params.get("text_var") else "")
    return [
        '<rect x="{0}" y="{1}" width="{2}" height="{3}" {4}/>'.format(x, y, w, h, paint),
        _text_node(params, x, y, w, h, font, _num(params, "font_size", 12), shown, inset=2),
    ]


def _render_lamp(params, context):
    x, y, w, h, _paint, _fill, _fill_a, _frame, _frame_a, _font, theme_colors = context
    colour = _LAMP_HEX.get(params.get("style_role"), "#A8AEB6")
    return ['<circle cx="{0:.1f}" cy="{1:.1f}" r="{2:.1f}" fill="{3}" stroke="{4}" stroke-width="1"/>'.format(
        x + w / 2.0, y + h / 2.0, min(w, h) / 2.0,
        colour, _role_hex(theme_colors, "frame", "#808080"))]


def _render_placeholder(params, context):
    x, y, w, h, paint, _fill, _fill_a, _frame, _frame_a, _font, theme_colors = context
    type_name = params.get("type", "control")
    centred = dict(params, h_align="HCENTER", v_align="VCENTER")
    return [
        '<rect x="{0}" y="{1}" width="{2}" height="{3}" {4}/>'.format(x, y, w, h, paint),
        _text_node(centred, x, y, w, h, _role_hex(theme_colors, "text.muted", "#666666"), 11, type_name),
    ]


_ELEMENT_RENDERERS = {
    "rectangle": _render_rectangle,
    "line": _render_line,
    "label": _render_label,
    "button": _render_button,
    "textfield": _render_textfield,
    "lamp": _render_lamp,
}


def _render_element(spec, theme_colors, scheme="light"):
    """Return the SVG markup for one parsed element (may be several nodes)."""
    type_name = spec.get("type")
    params = dict(spec.get("params", {}))
    params["type"] = type_name
    x, y = _num(params, "x"), _num(params, "y")
    w, h = _num(params, "width"), _num(params, "height")
    fill, fill_a, frame, frame_a, font = _resolved_colors(spec, theme_colors, scheme)
    context = (x, y, w, h, _paint(fill, fill_a, frame, frame_a), fill, fill_a, frame, frame_a, font, theme_colors)
    return _ELEMENT_RENDERERS.get(type_name, _render_placeholder)(params, context)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render(parsed, theme_colors=None, grid=0, scheme=None):
    """Render a ``svg_import.parse_svg`` result to a self-contained SVG string.

    ``grid`` > 0 overlays that spacing as hairlines -- useful when checking a
    layout against the 8px grid, off by default so the preview matches the
    screen.

    ``scheme`` defaults to whatever ``parse_svg`` resolved, so the preview and
    the compiled screen cannot disagree about it.
    """
    canvas = parsed.get("canvas", {})
    width = int(canvas.get("width", 800))
    height = int(canvas.get("height", 480))
    theme_colors = theme_colors or parsed.get("theme") or {}
    if scheme is None:
        scheme = parsed.get("scheme", "light")
    background = parsed.get("bg_color") or _role_hex(theme_colors, "screen", "#F4F5F7")

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}" '
        'viewBox="0 0 {0} {1}">'.format(width, height),
        '<rect x="0" y="0" width="{0}" height="{1}" fill="{2}"/>'.format(
            width, height, background
        ),
    ]

    if grid > 0:
        lines = []
        for gx in range(0, width, grid):
            lines.append('<line x1="{0}" y1="0" x2="{0}" y2="{1}"/>'.format(gx, height))
        for gy in range(0, height, grid):
            lines.append('<line x1="0" y1="{0}" x2="{1}" y2="{0}"/>'.format(gy, width))
        # A black hairline is invisible on a dark screen, which reads as "--grid
        # is broken" rather than "the grid is there". Draw it in whatever the
        # scheme uses for bright text; the 0.06 opacity keeps it a hint either way.
        grid_stroke = "#FFFFFF" if _is_dark(scheme) else "#000000"
        parts.append(
            '<g stroke="{1}" stroke-opacity="0.06" stroke-width="1">{0}</g>'.format(
                "".join(lines), grid_stroke
            )
        )

    for spec in parsed.get("elements", []):
        parts.extend(_render_element(spec, theme_colors, scheme))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Rasterisation
# ---------------------------------------------------------------------------

_BROWSER_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def find_browser():
    """Return a headless-capable Chromium executable path, or ``None``."""
    env = os.environ.get("CHROME_PATH")
    if env and os.path.isfile(env):
        return env
    for path in _BROWSER_CANDIDATES:
        if os.path.isfile(path):
            return path
    try:
        from shutil import which
    except ImportError:
        return None
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = which(name)
        if found:
            return found
    return None


def rasterize(svg_path, png_path, width, height, timeout=60):
    """Screenshot *svg_path* to *png_path*. Returns the PNG path, or ``None``.

    ``None`` means no headless browser was found -- not a failure worth
    stopping a compile over, since the SVG itself is already written.
    """
    browser = find_browser()
    if not browser:
        return None
    out_dir = os.path.dirname(os.path.abspath(png_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    url = "file:///" + os.path.abspath(svg_path).replace("\\", "/")
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--default-background-color=00000000",
        "--window-size={0},{1}".format(int(width), int(height)),
        "--screenshot={0}".format(os.path.abspath(png_path)),
        url,
    ]
    try:
        subprocess.run(
            cmd, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as exc:  # browser present but unusable
        print("[WARN] preview rasterisation failed: {0}".format(exc), file=sys.stderr)
        return None
    return png_path if os.path.isfile(png_path) else None
