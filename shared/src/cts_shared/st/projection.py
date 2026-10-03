# -*- coding: utf-8 -*-
"""The projected ``.st`` text format: the markers and the split/join rules.

One CODESYS object projects to one ``.st`` file.  Two boundaries can appear in
that text:

* ``// --- implementation ---`` between a declaration and its body -- POUs,
  methods, properties with a single body;
* ``// === SECTION ===`` between the two text sections of an object that has no
  declaration, namely a property's GET/SET accessors.

The IDE bridge, the external engine, the folder reader and the static analyzer
all parse the same text, so the marker strings and the rules that match them
live here instead of being re-spelled in each of them.  That duplication is
where the accessor fixes in eb4908b and c3154fe had to be repeated.

Kept dependency-free (``re`` only) on purpose: IronPython 2.7 inside CODESYS
imports this module, so no f-strings, no type annotations and no Python-3-only
syntax.
"""

from __future__ import print_function

import re


IMPLEMENTATION_MARKER = "// --- implementation ---"

# CODESYS' own keyword for the same boundary, as it appears in the
# ``project-view/*.st`` files the IDE exports.
IMPLEMENTATION_KEYWORD = "IMPLEMENTATION"

SECTION_MARKER = "// === SECTION ==="
# What the projector writes around a section boundary; also what splits a
# projected value back into sections.
SECTION_SEPARATOR = "\n\n" + SECTION_MARKER + "\n\n"

ACTION_END_KEYWORD = "END_ACTION"
ACTION_HEADER_RE = re.compile(
    r"^\s*ACTION\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.IGNORECASE,
)

# What each POU kind ends with.  The CODESYS API re-adds the keyword itself, so
# the create path strips it from the implementation before handing the text
# over.
POU_END_KEYWORDS = {
    "PROGRAM": "END_PROGRAM",
    "FUNCTION_BLOCK": "END_FUNCTION_BLOCK",
    "FUNCTION": "END_FUNCTION",
    "METHOD": "END_METHOD",
    "PROPERTY": "END_PROPERTY",
}


def normalize_newlines(text):
    """Normalise CRLF and bare CR to LF."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def action_name(text):
    """Return the name from a leading ``ACTION <name>`` header, or None."""
    for line in normalize_newlines(text).split("\n"):
        if not line.strip():
            continue
        match = ACTION_HEADER_RE.match(line)
        return match.group(1) if match else None
    return None


def find_implementation_split(text, accept_keyword=False, bare_fallback=True):
    """Return ``(declaration, implementation)`` around the marker, or None.

    The marker is matched as a whole line (``"\\n" + marker + "\\n"``) so an
    occurrence in the middle of a line -- inside a comment or a string literal
    -- does not count.  A bare occurrence is accepted only when
    *bare_fallback* is set, for the marker at the very start or end of the
    text.  The halves are returned raw: callers decide whether to strip.

    ``accept_keyword`` also accepts CODESYS' ``IMPLEMENTATION`` keyword, seen
    in project-view exports.
    """
    normalized = normalize_newlines(text)
    if accept_keyword:
        keyword = "\n" + IMPLEMENTATION_KEYWORD + "\n"
        if keyword in normalized:
            return tuple(normalized.split(keyword, 1))
    marker = "\n" + IMPLEMENTATION_MARKER + "\n"
    if marker in normalized:
        return tuple(normalized.split(marker, 1))
    if bare_fallback and IMPLEMENTATION_MARKER in normalized:
        return tuple(normalized.split(IMPLEMENTATION_MARKER, 1))
    return None


def find_section_split(text):
    """Return ``(declaration, implementation)`` around the section marker.

    Returns None when the text carries a single section.  Unlike the
    implementation marker the section marker is matched as a bare substring:
    the whole line is the marker, and the projector's surrounding blank lines
    are not part of its identity.
    """
    normalized = normalize_newlines(text)
    if SECTION_MARKER not in normalized:
        return None
    return tuple(normalized.split(SECTION_MARKER, 1))


def strip_pou_end_keyword(implementation):
    """Drop a trailing ``END_FUNCTION_BLOCK``-style keyword, if present."""
    text = implementation or ""
    for keyword in POU_END_KEYWORDS.values():
        if text.rstrip().endswith(keyword):
            return text.rstrip()[: -len(keyword)].rstrip()
    return implementation


def split_action_body(text, trailing_newline=False):
    """Return the body of an ``ACTION``-headed projection, or None.

    Returns None when *text* does not start with an ``ACTION <name>`` header,
    so callers can fall through to their normal declaration/implementation
    handling.  The optional ``END_ACTION`` terminator is dropped: CODESYS
    stores the bare body and re-adds the keywords itself.
    """
    lines = normalize_newlines(text).split("\n")
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not ACTION_HEADER_RE.match(lines[index]):
        return None

    body = lines[index + 1 :]
    while body and not body[0].strip():
        body.pop(0)
    if body and body[0].strip() == IMPLEMENTATION_MARKER:
        body.pop(0)
        while body and not body[0].strip():
            body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if body and body[-1].strip().upper() == ACTION_END_KEYWORD:
        body.pop()
        while body and not body[-1].strip():
            body.pop()
    joined = "\n".join(body)
    if trailing_newline:
        return joined + ("\n" if joined else "")
    return joined


def join_sections(values):
    """Join projected text sections with the section separator."""
    values = list(values or [])
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return SECTION_SEPARATOR.join(values)


def split_sections(value, expected_count):
    """Split ``value`` into ``expected_count`` sections.

    Missing sections are padded with "", extra sections are merged into the
    last one so a section that itself contains the separator survives.
    """
    expected_count = int(expected_count or 0)
    if expected_count <= 0:
        return []
    parts = (value or "").split(SECTION_SEPARATOR)
    if len(parts) < expected_count:
        parts.extend([""] * (expected_count - len(parts)))
    if len(parts) > expected_count:
        parts = parts[: expected_count - 1] + [
            SECTION_SEPARATOR.join(parts[expected_count - 1 :])
        ]
    return parts
