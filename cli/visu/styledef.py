# -*- coding: utf-8 -*-
"""
styledef.py - Read real CODESYS visualization style definitions.

CODESYS ships every visualization style as a machine-readable ``styledef.xml``
under ``C:\\ProgramData\\CODESYS\\Visualization Styles\\<Vendor>\\<Style>\\<version>``.
Each file carries an exact ``CanonicalName -> 0xAARRGGBB`` colour table (plus
fonts), and inherits the rest from a ``baseStyle`` chain (e.g.
``Flat style -> FlatCommon -> FlatImages``).

This module is the single authority for style palettes. ``load_theme`` in
``themes.py`` resolves a theme name to one of these styles, so the colours the
tool paints into custom primitives match exactly what CODESYS renders for the
native controls of the same project visual style.

The module is read-only with respect to the install. A committed
``styles_snapshot.json`` mirrors the resolved profiles so the tool still works
on machines (CI) where CODESYS is not installed.
"""

from __future__ import print_function

import json
import os
import re

import xml.etree.ElementTree as ET


class StyleDefError(Exception):
    pass


# ---------------------------------------------------------------------------
# Install discovery
# ---------------------------------------------------------------------------

_DEFAULT_STYLE_ROOTS = [
    r"C:\ProgramData\CODESYS\Visualization Styles",
]


def style_roots():
    """Return the list of directories to scan for installed styledefs.

    Overridable via the ``CDS_VISU_STYLE_ROOTS`` environment variable
    (os.pathsep-separated) for non-default CODESYS installations / testing.
    """
    env = os.environ.get("CDS_VISU_STYLE_ROOTS")
    if env:
        roots = [p for p in env.split(os.pathsep) if p.strip()]
    else:
        roots = list(_DEFAULT_STYLE_ROOTS)
    return [r for r in roots if os.path.isdir(r)]


# Friendly preset key -> the installed style identity (Name, Version, Company).
# Name/Version/Company match the ``<StyleInfo>`` of the real styledef and the
# ``"Name, Version (Company)"`` string stored in the project's Visualization
# Manager. This is the complete public style vocabulary the tool supports.
_3S = "3S-Smart Software Solutions GmbH"
PRESET_STYLES = {
    "flat-style": ("Flat style", "4.9.0.0", "CODESYS"),
    "basic-style": ("Basic style", "4.9.0.0", "CODESYS"),
    "default": ("Default", "4.9.0.0", "CODESYS"),
    "white-style": ("White style", "4.9.0.0", "CODESYS"),
    "example-for-a-style": ("Example", "4.9.0.0", "ExampleCompany"),
    "style-2": ("Style2", "3.5.12.0", _3S),
    "style-3-gradient-linear-1": ("Style3", "3.5.12.0", _3S),
    "style-4-gradient-linear-2": ("Style4", "3.5.12.0", _3S),
    "style-5-gradient-axial-1": ("Style5", "3.5.12.0", _3S),
    "style-6-gradient-axial-2": ("Style6", "3.5.12.0", _3S),
    "style-7-gradient-double-linear-1": ("Style7", "3.5.12.0", _3S),
    "style-8-gradient-double-linear-2": ("Style8", "3.5.12.0", _3S),
}


# ---------------------------------------------------------------------------
# styledef.xml parsing
# ---------------------------------------------------------------------------

_BASEREF_RE = re.compile(r"^(?P<name>.*?),\s*(?P<ver>[0-9][0-9.]*)\s*\((?P<co>.*)\)\s*$")


def parse_baseref(text):
    """Parse ``"FlatCommon, 4.9.0.0 (CODESYS)"`` -> (name, version, company).

    Also parses the Visualization Manager ``VisuStyle`` string, which has the
    same shape. Returns (name, None, None) when only a bare name is present.
    """
    if not text:
        return (None, None, None)
    s = str(text).strip()
    m = _BASEREF_RE.match(s)
    if m:
        return (m.group("name").strip(), m.group("ver").strip(), m.group("co").strip())
    return (s, None, None)


def format_styleref(name, version, company):
    """Inverse of :func:`parse_baseref`: build the canonical reference string."""
    if version and company:
        return "{0}, {1} ({2})".format(name, version, company)
    if version:
        return "{0}, {1}".format(name, version)
    return str(name)


def _normalize_argb(value):
    """Normalize a styledef colour value to ``0xAARRGGBB`` (upper hex)."""
    raw = str(value).strip()
    low = raw.lower()
    if low.startswith("0x"):
        low = low[2:]
    elif low.startswith("#"):
        low = low[1:]
    if not re.match(r"^[0-9a-f]{1,8}$", low):
        raise StyleDefError("Unparseable colour value: {0!r}".format(value))
    n = int(low, 16)
    if len(low) <= 6:
        n |= 0xFF000000  # opaque
    return "0x{0:08X}".format(n & 0xFFFFFFFF)


def load_styledef(path):
    """Parse one ``styledef.xml`` into a node dict (no inheritance resolved)."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise StyleDefError("Cannot parse {0}: {1}".format(path, exc))

    general = root.find("General")
    info = root.find(".//StyleInfo")
    name = info.findtext("Name") if info is not None else None
    company = info.findtext("Company") if info is not None else None
    version = info.findtext("Version") if info is not None else None
    base = general.get("baseStyle") if general is not None else None
    partial = (general.get("partialOnly") if general is not None else None) == "true"

    colors = {}
    for el in root.findall(".//Colors/Color"):
        cn = el.get("name")
        if cn and el.text and el.text.strip():
            colors[cn] = _normalize_argb(el.text)

    fonts = {}
    for el in root.findall(".//Fonts/Font"):
        fn = el.get("name")
        if not fn:
            continue
        size = el.findtext("FontSize")
        fonts[fn] = {
            "name": el.findtext("FontName"),
            "size": int(size) if size and size.strip().isdigit() else None,
        }

    return {
        "path": path,
        "name": (name or "").strip(),
        "version": (version or "").strip(),
        "company": (company or "").strip(),
        "base": base,
        "partial": partial,
        "colors": colors,
        "fonts": fonts,
    }


def build_index(roots=None):
    """Scan the install and index every styledef by (name, version, company)."""
    if roots is None:
        roots = style_roots()
    index = {}
    for root_dir in roots:
        for dirpath, _dirs, files in os.walk(root_dir):
            if "styledef.xml" not in files:
                continue
            try:
                node = load_styledef(os.path.join(dirpath, "styledef.xml"))
            except StyleDefError:
                continue
            index[(node["name"], node["version"], node["company"])] = node
    return index


def _lookup(index, name, version, company):
    """Find a node, tolerating an unspecified version/company in the key."""
    if (name, version, company) in index:
        return index[(name, version, company)]
    # Fall back to matching on name (+version) only.
    cands = [n for k, n in index.items() if k[0] == name
             and (not version or k[1] == version)
             and (not company or k[2] == company)]
    if cands:
        return cands[0]
    return None


def resolve_chain(name, version, company, index=None):
    """Resolve a style's full colour/font palette by walking ``baseStyle``.

    Leaf overrides win over bases. Returns a StyleProfile dict::

        {"name", "version", "company",
         "colors": {canonical: "0xAARRGGBB"},
         "fonts":  {name: {"name", "size"}},
         "base_chain": ["Leaf, ver (co)", "Base, ...", ...]}
    """
    if index is None:
        index = build_index()
    node = _lookup(index, name, version, company)
    if node is None:
        raise StyleDefError(
            "Installed style not found: {0}".format(format_styleref(name, version, company))
        )

    # Build the chain leaf -> base -> base...
    chain = []
    seen = set()
    cur = node
    while cur is not None:
        key = (cur["name"], cur["version"], cur["company"])
        if key in seen:  # cycle guard
            break
        seen.add(key)
        chain.append(cur)
        if not cur.get("base"):
            break
        bn, bv, bco = parse_baseref(cur["base"])
        cur = _lookup(index, bn, bv, bco)

    # Merge bases first, leaf last (leaf wins).
    colors = {}
    fonts = {}
    for n in reversed(chain):
        colors.update(n["colors"])
        fonts.update(n["fonts"])

    return {
        "name": node["name"],
        "version": node["version"],
        "company": node["company"],
        "colors": colors,
        "fonts": fonts,
        "base_chain": [format_styleref(n["name"], n["version"], n["company"]) for n in chain],
    }


# ---------------------------------------------------------------------------
# Snapshot fallback
# ---------------------------------------------------------------------------

_SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "styles_snapshot.json")
_SNAPSHOT_CACHE = None


def _snapshot_key(name, version, company):
    return "{0}|{1}|{2}".format(name, version, company)


def load_snapshot():
    """Load the committed offline snapshot of resolved style profiles."""
    global _SNAPSHOT_CACHE
    if _SNAPSHOT_CACHE is None:
        if os.path.isfile(_SNAPSHOT_PATH):
            with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as handle:
                _SNAPSHOT_CACHE = json.load(handle)
        else:
            _SNAPSHOT_CACHE = {}
    return _SNAPSHOT_CACHE


def resolve_profile(name, version, company):
    """Resolve a StyleProfile from the live install, else the committed snapshot.

    Raises StyleDefError if the style is available in neither source.
    """
    try:
        index = build_index()
        if _lookup(index, name, version, company) is not None:
            return resolve_chain(name, version, company, index=index)
    except StyleDefError:
        pass
    snap = load_snapshot()
    entry = snap.get(_snapshot_key(name, version, company))
    if entry is None:
        # Tolerate version/company drift in the snapshot too.
        for key, val in snap.items():
            kn = key.split("|")
            if kn and kn[0] == name:
                entry = val
                break
    if entry is None:
        raise StyleDefError(
            "Style unavailable (no install, not in snapshot): {0}".format(
                format_styleref(name, version, company)
            )
        )
    return entry
