# -*- coding: utf-8 -*-
"""
ide_st_text.py -- Splitting of projected .st text into declaration and
implementation, shared by every daemon-side consumer.

This module is deliberately dependency-free -- stdlib plus the shared
``cts_shared.st.projection`` format module -- so it can be imported from
IronPython 2.7 inside CODESYS and from CPython in the unit tests. It is the
single place that decides what a given .st file means on the daemon side; the
sync handlers, the creation path and update_pou all route through it. Keeping
one implementation matters because the three used to disagree about marker-less
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

# Imported for its side effect: puts shared/src on sys.path so this module can be
# imported cold, without depending on some earlier bridge module having done it.
import ide_runtime_common  # noqa: F401

from cts_shared.st.projection import (
    IMPLEMENTATION_MARKER as ST_IMPLEMENTATION_MARKER,
    SECTION_MARKER as ST_SECTION_MARKER,
    action_name,
    find_implementation_split,
    find_section_split,
    normalize_newlines,
    split_action_body,
    strip_pou_end_keyword,
)


def split_st_text(content, strip_pou_end=False):
    """Split .st content into ``(declaration, implementation)``.

    An ACTION's synthesised header is dropped (see the module docstring), the
    implementation marker and the section separator are both understood, and a
    marker-less file stays a declaration.  ``strip_pou_end`` drops a trailing
    END_FUNCTION_BLOCK / END_FUNCTION / END_PROGRAM from the implementation;
    the CODESYS API re-adds those itself, so the creation path passes True.
    """
    normalized = normalize_newlines(content)

    if action_name(normalized):
        return "", split_action_body(normalized)

    parts = find_implementation_split(normalized)
    if parts is not None:
        declaration, implementation = parts[0].strip(), parts[1].strip()
        if strip_pou_end:
            implementation = strip_pou_end_keyword(implementation)
        return declaration, implementation

    section = find_section_split(normalized)
    if section is not None:
        return section[0].strip(), section[1].strip()

    return normalized.strip(), ""
