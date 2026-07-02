"""Semantic class stylesheet for HMI SVG sketches.

A tiny CSS-like layer that maps authoring *classes* (``class="panel"``) to the
plain SVG presentation attributes the element parsers already understand
(``fill``, ``stroke``, ``font-size``). Colours are expressed as ``var(--role)``
and resolve through the active theme / CODESYS style, so authors never write a
literal colour -- they pick a class and the visual style decides the colour.

Two layers, merged in order (later wins):

1. the bundled ``stylesheet.css`` next to this module (the shared defaults);
2. an optional project-level ``visu.css`` (per-project overrides / additions).

This module is a thin loader over DATA. To add or change a class, edit the
``.css`` file -- do not hard-code mappings here.
"""

from __future__ import print_function

import os
import re

_BUNDLED_CSS = os.path.join(os.path.dirname(__file__), "stylesheet.css")

# One CSS rule: ``.name { decl; decl; }`` -- class name, then declaration body.
_RULE_RE = re.compile(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}")
# One declaration inside a rule body: ``prop: value``.
_DECL_RE = re.compile(r"([A-Za-z-]+)\s*:\s*([^;]+)")

# Properties a class is allowed to set. These map 1:1 onto SVG attributes the
# element parsers read; anything else in the CSS is ignored on purpose so a
# stray property can never inject an unsupported attribute into an element.
_ALLOWED_PROPS = ("fill", "stroke", "font-size")


class StylesheetError(Exception):
    """Raised on malformed stylesheet content."""

    pass


def parse_stylesheet(css_text):
    """Parse CSS text into ``{class_name: {prop: value}}``.

    Comments (``/* ... */``) are stripped first. Only properties in
    ``_ALLOWED_PROPS`` are kept; later declarations for the same property win.
    """
    rules = {}
    # Strip block comments so a ``{`` or ``:`` inside them can't confuse us.
    text = re.sub(r"/\*.*?\*/", "", css_text or "", flags=re.DOTALL)
    for rule in _RULE_RE.finditer(text):
        name = rule.group(1)
        decls = rules.setdefault(name, {})
        for decl in _DECL_RE.finditer(rule.group(2)):
            prop = decl.group(1).strip().lower()
            value = decl.group(2).strip()
            if prop in _ALLOWED_PROPS and value:
                decls[prop] = value
    return rules


def load_stylesheet(project_dir=None):
    """Return the merged class map: bundled defaults + optional project overrides.

    ``project_dir`` is searched for a ``visu.css`` file whose rules are merged
    on top of the bundled defaults (property-level merge, so a project rule can
    tweak one property of a class without redefining the whole rule).
    """
    merged = {}
    with open(_BUNDLED_CSS, "r", encoding="utf-8") as handle:
        _merge(merged, parse_stylesheet(handle.read()))

    if project_dir:
        override = os.path.join(project_dir, "visu.css")
        if os.path.isfile(override):
            with open(override, "r", encoding="utf-8") as handle:
                _merge(merged, parse_stylesheet(handle.read()))

    return merged


def class_attributes(class_value, stylesheet):
    """Expand a ``class`` attribute value into ``{svg_attr: value}`` defaults.

    Multiple space-separated classes are applied left-to-right (later wins).
    Unknown class names are ignored. The returned dict uses SVG attribute names
    (``fill``, ``stroke``, ``font-size``) so callers can inject them directly.
    """
    attrs = {}
    for name in (class_value or "").split():
        rule = stylesheet.get(name)
        if rule:
            attrs.update(rule)
    return attrs


def _merge(base, incoming):
    """Property-level merge of one class map into another (in place)."""
    for name, decls in incoming.items():
        base.setdefault(name, {}).update(decls)
