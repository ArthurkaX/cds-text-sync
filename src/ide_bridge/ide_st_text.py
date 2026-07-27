# -*- coding: utf-8 -*-
"""
ide_st_text.py -- Splitting of projected .st text into declaration and
implementation, shared by every daemon-side consumer.

This module is deliberately dependency-free (stdlib ``re`` only) so it can be
imported from IronPython 2.7 inside CODESYS and from CPython in the unit tests.
It is the single place that decides what a given .st file means; the sync
handlers, the creation path and update_pou all route through it. Keeping one
implementation matters because the three used to disagree about marker-less
files, which is exactly how an edit could be reported as applied without ever
reaching the IDE.

Rules, in order:

1. ``ACTION <name>`` header  -> ("", body). ACTIONs have no declaration; the
   header is synthesised on export by ``xml_helpers.st_projection_content``
   purely so the file is self-describing, and is stripped again here.
2. ``// --- implementation ---`` marker -> (before, after).
3. Neither -> (content, ""). A marker-less file is a *declaration*: that is what
   GVLs, DUTs and POUs with an empty body project to. Do not "improve" this into
   an implementation — those kinds have no textual_implementation, so the write
   silently lands nowhere.
"""

from __future__ import print_function

import re


ST_IMPLEMENTATION_MARKER = "// --- implementation ---"

_ACTION_HEADER_RE = re.compile(
    r"^\s*ACTION\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.IGNORECASE,
)

_POU_END_KEYWORDS = ("END_FUNCTION_BLOCK", "END_FUNCTION", "END_PROGRAM")


def _normalize_newlines(content):
    return (content or "").replace("\r\n", "\n").replace("\r", "\n")


def action_name(content):
    """Return the name from a leading ``ACTION <name>`` header, or None."""
    for line in _normalize_newlines(content).split("\n"):
        if not line.strip():
            continue
        match = _ACTION_HEADER_RE.match(line)
        return match.group(1) if match else None
    return None


def _split_action_text(content):
    """Return the implementation body of an ACTION-headed .st file."""
    lines = _normalize_newlines(content).split("\n")
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1

    body = lines[index + 1 :]
    while body and not body[0].strip():
        body.pop(0)
    if body and body[0].strip() == ST_IMPLEMENTATION_MARKER:
        body.pop(0)
        while body and not body[0].strip():
            body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if body and body[-1].strip().upper() == "END_ACTION":
        body.pop()
        while body and not body[-1].strip():
            body.pop()
    return "\n".join(body)


def split_st_text(content, strip_pou_end=False):
    """Split .st content into ``(declaration, implementation)``.

    ``strip_pou_end`` drops a trailing END_FUNCTION_BLOCK / END_FUNCTION /
    END_PROGRAM from the implementation; the CODESYS API re-adds those itself,
    so the creation path passes True.
    """
    normalized = _normalize_newlines(content)

    if action_name(normalized):
        return "", _split_action_text(normalized)

    if ST_IMPLEMENTATION_MARKER in normalized:
        parts = normalized.split(ST_IMPLEMENTATION_MARKER, 1)
        declaration = parts[0].strip()
        implementation = parts[1].strip()
        if strip_pou_end:
            for end_keyword in _POU_END_KEYWORDS:
                if implementation.rstrip().endswith(end_keyword):
                    implementation = implementation.rstrip()[
                        : -len(end_keyword)
                    ].rstrip()
                    break
        return declaration, implementation

    return normalized.strip(), ""
