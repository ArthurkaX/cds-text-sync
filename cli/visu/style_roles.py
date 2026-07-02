# -*- coding: utf-8 -*-
"""
style_roles.py - The single curated mapping between authoring roles and the
real CODESYS style CanonicalNames.

SVG authors write semantic roles (``fill="var(--panel)"``) and never pick a hex
colour. This module is the *only* hand-maintained artefact that ties those roles
to CODESYS' ``CanonicalName`` style anchors, so:

* ``role_palette(profile)`` computes the concrete ``{role: "#hex"}`` palette a
  theme exposes, sampled from the real ``styledef.xml`` (via styledef.py), used
  for SVG preview and as the literal fallback for explicit hex.
* ``role_canonical(role)`` tells the builder which CanonicalName a role links
  to, so a custom primitive painted ``var(--panel)`` resolves through the same
  style anchor as the native control beside it -> the two never conflict.
* ``canonical_to_role(name)`` is the inverse used by svg_export, generated from
  the same table so the two directions cannot drift.

Roles with no CanonicalName equivalent (status/domain accents such as
``success``/``water``) are anchored to a real style colour when one exists and
otherwise fall back to a documented literal.
"""

from __future__ import print_function


# ---------------------------------------------------------------------------
# Role -> CanonicalName anchors
# ---------------------------------------------------------------------------
#
# Each role resolves to a colour by trying its candidate CanonicalNames in order
# against the active StyleProfile, then the literal fallback. The first
# candidate is also the *style-link* anchor returned by ``role_canonical`` (the
# CanonicalName written into the element XML for style-linked colours).
#
# (role, [canonical candidates...], literal_fallback)
_ROLE_DEFS = [
    # --- screen / surface ---------------------------------------------------
    ("surface", ["Element-Background-Color"], "#F5F5F5"),
    ("screen.background", ["Element-Background-Color"], "#F5F5F5"),
    ("screen.surface", ["BasicElement-Fill-Color"], "#FFFFFF"),

    # --- custom primitive fill (panels, grouping shapes) --------------------
    ("panel", ["BasicElement-Fill-Color"], "#FFFFFF"),
    ("fill", ["BasicElement-Fill-Color"], "#FFFFFF"),
    ("custom.fill", ["BasicElement-Fill-Color"], "#FFFFFF"),

    # --- custom primitive frame / borders / separators ----------------------
    ("frame", ["BasicElement-Frame-Color"], "#000000"),
    ("custom.frame", ["BasicElement-Frame-Color"], "#000000"),
    ("panel.frame", ["BasicElement-Frame-Color"], "#000000"),
    ("border", ["BasicElement-Frame-Color"], "#000000"),
    ("divider", ["BasicElement-Frame-Color"], "#000000"),

    # --- text ---------------------------------------------------------------
    ("text", ["Font-Default-Color"], "#1F1F1F"),
    ("on.surface", ["Font-Default-Color"], "#1F1F1F"),
    ("custom.text", ["Font-Default-Color"], "#1F1F1F"),
    ("panel.header.text", ["Font-Default-Color"], "#1F1F1F"),
    ("text.bright", ["Font-Default-BrightColor"], "#FFFFFF"),
    ("text.muted", ["Element-Control-Color", "Element-Meter-LabelFontColor"], "#666666"),

    # --- panel header -------------------------------------------------------
    ("panel.header", ["Element-Background-Color"], "#EAEAEA"),

    # --- native textfield / text editor -------------------------------------
    ("field.fill", ["Element-Fill-Color"], "#FFFFFF"),
    ("field.frame", ["Element-Frame-Color"], "#BEBEBE"),

    # --- native button caption ----------------------------------------------
    ("button.text", ["Element-Button-FontColor"], "#FFFFFF"),

    # --- accent / active ----------------------------------------------------
    ("accent", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("primary", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("element.active", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("focus", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("secondary", ["Element-Frame-Color"], "#6A6A6A"),

    # --- status / alarm -----------------------------------------------------
    ("success", ["Element-Control-Color_Green"], "#3A8A3A"),
    ("warning", ["Element-Control-Color_Yellow"], "#C47A00"),
    ("error", ["Element-Alarm-Frame-Color", "BasicElement-Alarm-Frame-Color"], "#C9302C"),
    ("alarm.fill", ["BasicElement-Alarm-Fill-Color"], "#FFCFCF"),
    ("alarm.frame", ["BasicElement-Alarm-Frame-Color"], "#FF0000"),

    # --- misc UI ------------------------------------------------------------
    ("muted", ["Element-Frame-Color"], "#7A7A7A"),
    ("hover", [], "#E9F3FF"),
    ("disabled", [], "#A6A6A6"),

    # --- P&ID domain accents (no style anchor; documented literals) ---------
    ("water", [], "#2D8CCB"),
    ("water.dim", [], "#1F6FA3"),
    ("metal", [], "#8C8C8C"),
]

# role -> (candidates, fallback)
_ROLE_TABLE = {role: (cands, fb) for role, cands, fb in _ROLE_DEFS}

# Preferred role each CanonicalName reverses to (svg_export). Order in
# ``_ROLE_DEFS`` defines preference: the first role that anchors a CanonicalName
# wins, so authoring roles (``frame``) beat aliases (``border``) and primary
# names match plan.md §2.5.
_CANONICAL_TO_ROLE = {}
for _role, _cands, _fb in _ROLE_DEFS:
    if _cands:
        _CANONICAL_TO_ROLE.setdefault(_cands[0], _role)


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _argb_to_hex(argb):
    """``0xAARRGGBB`` (str) -> ``#RRGGBB`` (drop opaque alpha) or ``#RRGGBBAA``."""
    raw = str(argb).strip()
    low = raw.lower()
    if low.startswith("0x"):
        low = low[2:]
    elif low.startswith("#"):
        low = low[1:]
    n = int(low, 16)
    a = (n >> 24) & 0xFF
    r = (n >> 16) & 0xFF
    g = (n >> 8) & 0xFF
    b = n & 0xFF
    if a == 0xFF:
        return "#{0:02X}{1:02X}{2:02X}".format(r, g, b)
    return "#{0:02X}{1:02X}{2:02X}{3:02X}".format(r, g, b, a)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def roles():
    """Return the full set of authoring role names."""
    return [role for role, _c, _f in _ROLE_DEFS]


def role_canonical(role):
    """Return the CanonicalName a role style-links to, or ``None``.

    Accepts dotted (``custom.fill``) or hyphenated (``custom-fill``) role names.
    """
    key = str(role or "").replace("-", ".")
    cands = _ROLE_TABLE.get(key, ([], None))[0]
    return cands[0] if cands else None


def canonical_to_role(canonical_name):
    """Inverse of :func:`role_canonical`: CanonicalName -> hyphenated role.

    Returns a hyphenated role token (e.g. ``alarm-frame``) suitable for emitting
    ``var(--alarm-frame)`` in SVG. Falls back to a heuristic for unknown names.
    """
    if canonical_name in _CANONICAL_TO_ROLE:
        return _CANONICAL_TO_ROLE[canonical_name].replace(".", "-")
    # Heuristic: strip known prefixes and the trailing ``-Color``.
    name = canonical_name or ""
    for prefix in ("BasicElement-", "Element-", "Font-", "Alarm-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.endswith("-Color"):
        name = name[: -len("-Color")]
    return "-".join(p.lower() for p in name.split("-") if p)


def role_palette(profile):
    """Compute ``{role: "#hex"}`` for a resolved StyleProfile.

    Each role samples its first available candidate CanonicalName from the real
    style, falling back to the documented literal. The returned hex matches what
    CODESYS renders for the same anchor, so SVG previews are faithful.
    """
    colors = (profile or {}).get("colors", {}) if isinstance(profile, dict) else {}
    palette = {}
    for role, cands, fallback in _ROLE_DEFS:
        value = None
        for cn in cands:
            argb = colors.get(cn)
            if argb:
                value = _argb_to_hex(argb)
                break
        palette[role] = value if value is not None else fallback
    return palette
