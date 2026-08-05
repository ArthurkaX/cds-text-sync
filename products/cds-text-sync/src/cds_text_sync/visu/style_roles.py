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
    # ``screen`` is the field the generated visualisation is painted on. It is
    # deliberately NOT anchored to Element-Background-Color: several shipped
    # styles use a saturated tint there (flat-style: #FFFFE1) which reads as a
    # dated screen. ``cts visu from-svg --background style`` opts back in.
    ("screen", [], "#F4F5F7"),
    ("surface", ["Element-Background-Color"], "#F5F5F5"),
    ("screen.background", ["Element-Background-Color"], "#F5F5F5"),
    ("screen.surface", ["BasicElement-Fill-Color"], "#FFFFFF"),

    # --- custom primitive fill (panels, grouping shapes) --------------------
    ("panel", ["BasicElement-Fill-Color"], "#FFFFFF"),
    ("card", ["BasicElement-Fill-Color"], "#EDEFF2"),
    ("fill", ["BasicElement-Fill-Color"], "#FFFFFF"),
    ("custom.fill", ["BasicElement-Fill-Color"], "#FFFFFF"),

    # --- custom primitive frame / borders / separators ----------------------
    ("frame", ["BasicElement-Frame-Color"], "#000000"),
    ("custom.frame", ["BasicElement-Frame-Color"], "#D5D9DF"),
    ("panel.frame", ["BasicElement-Frame-Color"], "#D5D9DF"),
    ("border", ["BasicElement-Frame-Color"], "#000000"),
    ("divider", ["BasicElement-Frame-Color"], "#D5D9DF"),

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
    # The font a textfield draws its value in. Same anchor as ``text``, but a
    # role of its own: the field box and the text inside it have to be chosen
    # together, and naming the pair makes that a testable contract rather than
    # an implicit one (see svg_import's textfield font-colour default).
    ("field.text", ["Font-Default-Color"], "#1F1F1F"),

    # --- accent / active ----------------------------------------------------
    ("accent", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("primary", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("element.active", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("focus", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("secondary", ["Element-Frame-Color"], "#6A6A6A"),

    # --- native button ------------------------------------------------------
    # Listed *after* the accent block on purpose: ``button.fill`` shares
    # accent's anchors, and ``_CANONICAL_TO_ROLE`` keeps the first role that
    # claims a CanonicalName, so moving it earlier would make svg_export
    # decompile every highlight-coloured element as a button fill.
    ("button.fill", ["Element-Control-HighlightColor", "Dialog-HeaderColor"], "#007ACC"),
    ("button.text", ["Element-Button-FontColor"], "#FFFFFF"),

    # --- status / alarm -----------------------------------------------------
    # Status colours carry *meaning*, so they are curated rather than sampled.
    # The Element-Control-Color_* anchors are control accents, not semantics:
    # flat-style resolves _Green to #ADE204 (acid), which reads as decoration
    # rather than "healthy". Anchors are kept for style-linking; the literal is
    # what the palette actually serves.
    ("success", ["Element-Control-Color_Green"], "#3F9142"),
    ("warning", ["Element-Control-Color_Yellow"], "#C8860D"),
    ("error", ["Element-Alarm-Frame-Color", "BasicElement-Alarm-Frame-Color"], "#C0392B"),
    ("alarm.fill", ["BasicElement-Alarm-Fill-Color"], "#C0392B"),
    ("alarm.frame", ["BasicElement-Alarm-Frame-Color"], "#8E2B20"),

    # --- misc UI ------------------------------------------------------------
    ("muted", ["Element-Frame-Color"], "#7A7A7A"),
    ("hover", [], "#E9F3FF"),
    ("disabled", [], "#A6A6A6"),

    # --- P&ID domain accents (no style anchor; documented literals) ---------
    ("water", [], "#2E7FB8"),
    ("water.dim", [], "#1B5B87"),
    ("metal", [], "#9AA3AD"),
]

# Roles this module *curates*: they carry authoring semantics that no single
# CanonicalName expresses, so a style snapshot (cds_text_sync/visu/themes/*.json) must not
# redefine them -- see themes.strip_curated_roles(). Everything not listed here
# (text, frame, accent, hover, native control colours, ...) stays owned by the
# project's CODESYS visual style.
CURATED_ROLES = frozenset([
    "screen",
    "panel",
    "card",
    "divider",
    "panel.frame",
    # An unclassed <rect> lands on custom.fill/custom.frame. Those anchor to the
    # same BasicElement-* names as ``panel``/``divider``, so letting a style
    # snapshot own one pair while we curate the other guarantees two shapes with
    # identical intent are painted differently. Curate both, or neither.
    "custom.fill",
    "custom.frame",
    "success",
    "warning",
    "error",
    "alarm.fill",
    "alarm.frame",
    "water",
    "water.dim",
    "metal",
])

# ---------------------------------------------------------------------------
# The dark scheme
# ---------------------------------------------------------------------------
#
# A second opinion about what each role resolves to, kept as an overlay rather
# than a fourth element in the ``_ROLE_DEFS`` triples so that "which roles have
# a dark value" stays a single reviewable list.
#
# Every shipped CODESYS style is light, so in dark the palette is authoritative
# for each role it names -- sampling a light style for ``text`` while we paint
# the panel behind it dark is exactly how white-on-white happens. ``--scheme
# light`` (the default) still defers to the project style, and an inline
# ``<defs><style>:root{...}</style></defs>`` block still overrides everything.
#
# Surfaces rise screen -> panel -> card; status colours are lifted from their
# light values because a dark ground needs more luminance to read as the same
# signal. Lamps are NOT here: their colour comes from ``Element-Lamp-*``, and
# an indicator that changes meaning with the scheme would be a safety problem.
_DARK_LITERALS = {
    # surfaces
    "screen": "#10141A",
    "surface": "#171C24",
    "screen.background": "#10141A",
    "screen.surface": "#171C24",
    "panel": "#171C24",
    "card": "#1E242D",
    "fill": "#171C24",
    "custom.fill": "#171C24",
    # frames / separators
    "frame": "#2A3038",
    "custom.frame": "#2A3038",
    "panel.frame": "#2A3038",
    "border": "#2A3038",
    "divider": "#2A3038",
    # text
    "text": "#E6E9ED",
    "on.surface": "#E6E9ED",
    "custom.text": "#E6E9ED",
    "panel.header.text": "#E6E9ED",
    "text.bright": "#FFFFFF",
    "text.muted": "#9AA6B2",
    "panel.header": "#1E242D",
    # native controls
    "field.fill": "#0E1218",
    "field.frame": "#39424E",
    "field.text": "#E6E9ED",
    "button.fill": "#232A35",
    "button.text": "#E6E9ED",
    # accent
    "accent": "#4DA3FF",
    "primary": "#4DA3FF",
    "element.active": "#4DA3FF",
    "focus": "#4DA3FF",
    "secondary": "#6E7681",
    # status
    "success": "#4CAF50",
    "warning": "#E0A030",
    "error": "#E05A4A",
    "alarm.fill": "#B03A2E",
    "alarm.frame": "#E05A4A",
    # misc UI
    "muted": "#9AA6B2",
    "hover": "#24303D",
    "disabled": "#4A525C",
    # P&ID
    "water": "#3C93D4",
    "water.dim": "#1B5B87",
    "metal": "#6E7681",
}

SCHEMES = ("light", "dark")

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


def normalize_scheme(scheme):
    """Coerce a scheme name to ``"light"`` or ``"dark"``; unknown -> ``"light"``."""
    name = str(scheme or "light").strip().lower()
    return name if name in SCHEMES else "light"


def curated_roles(scheme="light"):
    """Roles this module owns outright in *scheme*.

    A curated role is forced to the palette value and a style snapshot must not
    redefine it (see ``themes.strip_curated_roles``).

    Light curates only the roles that carry authoring semantics no single
    CanonicalName expresses. Dark additionally curates every role it has a value
    for -- surfaces, the text that sits on them, and the native control colours
    -- because those have to be chosen as a set. Curating a dark panel while
    letting a light style keep ``text`` is precisely the white-on-white defect.
    """
    if normalize_scheme(scheme) == "dark":
        return frozenset(CURATED_ROLES | set(_DARK_LITERALS))
    return CURATED_ROLES


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


def role_palette(profile, scheme="light"):
    """Compute ``{role: "#hex"}`` for a resolved StyleProfile.

    In ``light`` each role samples its first available candidate CanonicalName
    from the real style, falling back to the documented literal, so the hex
    matches what CODESYS renders for the same anchor.

    In ``dark`` every role named by :data:`_DARK_LITERALS` returns that literal
    and *profile is not consulted for it*. Sampling a light style for half a
    dark palette is what produces unreadable pairings; the roles a scheme owns,
    it owns outright. Roles with no dark opinion still sample normally.
    """
    colors = (profile or {}).get("colors", {}) if isinstance(profile, dict) else {}
    overlay = _DARK_LITERALS if normalize_scheme(scheme) == "dark" else {}
    palette = {}
    for role, cands, fallback in _ROLE_DEFS:
        if role in overlay:
            palette[role] = overlay[role]
            continue
        value = None
        for cn in cands:
            argb = colors.get(cn)
            if argb:
                value = _argb_to_hex(argb)
                break
        palette[role] = value if value is not None else fallback
    return palette
