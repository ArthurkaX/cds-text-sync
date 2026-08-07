"""
body.py - Implementation/declaration section access for the analyzer.

Text rules need one thing from a unit's body: its text with comments,
pragmas and string contents already blanked, plus the absolute offset of
every position in it. That offset used to be hand-computed per rule
(``source_spans`` + ``impl_start``), and forgetting the addition silently
misplaces every finding in any POU that has a declaration. This module is
the single place the conversion happens; ``Section.at`` is the one
conversion a rule performs.
"""

from __future__ import annotations

import re

from cds_static_analyzer.st.blanking import blank_noise, trim_strings


class Section:
    """One region of a unit (implementation or declaration), pre-blanked.

    ``.text`` is comment/string blanked; ``.raw`` is the untouched section
    text. Blanking only replaces characters, so a position in ``.text``
    indexes the same character in ``.raw`` and, after ``.at()``, in
    ``unit.text``.
    """

    def __init__(self, raw, base):
        self.raw = raw
        self.base = base
        self.text = trim_strings(blank_noise(raw))

    def __bool__(self):
        return bool(self.raw.strip())

    def at(self, local_offset):
        """Absolute offset in ``unit.text`` of *local_offset* in this section."""
        return self.base + local_offset

    def statements(self):
        """Yield ``(absolute_offset, statement)`` for semicolon-terminated
        statements in the blanked text, trailing ``;`` stripped and leading
        whitespace skipped. A ``;`` inside a string or comment is already
        blanked out, so it never splits a statement."""
        start = 0
        for match in re.finditer(r";", self.text):
            raw = self.text[start : match.end()]
            leading = len(raw) - len(raw.lstrip())
            statement = raw.strip()
            if statement:
                yield self.base + start + leading, statement[:-1]
            start = match.end()

    def lines(self):
        """Yield ``(lineno, absolute_offset, line_text)`` -- 1-based lineno,
        absolute offsets (identical in ``.raw`` and ``.text``, since blanking
        is 1:1), raw line text (line ending stripped)."""
        lineno = 0
        offset = 0
        for line in self.raw.splitlines(keepends=True):
            lineno += 1
            yield lineno, self.base + offset, line.rstrip("\r\n")
            offset += len(line)


def _section(unit, role, text):
    """Build a Section over *text*, anchored at the *role* span in unit.text."""
    base = next(
        (span.start_offset for span in unit.source_spans if span.role == role),
        0,
    )
    return Section(text or "", base)


def body(unit):
    """Implementation section of *unit*.

    A unit without an implementation marker is analysed as its whole text
    (the legacy ``unit.implementation or unit.text`` fallback the text rules
    used), with base 0 so offsets stay absolute. The section is falsy only
    when there is no text at all.
    """
    text = unit.implementation if unit.implementation is not None else unit.text
    cached = getattr(unit, "_cts_body_section_cache", None)
    if cached is not None and cached[0] is text:
        return cached[1]
    section = _section(unit, "implementation", text)
    unit._cts_body_section_cache = (text, section)
    return section


def declaration(unit):
    """Declaration section of *unit* (falsy when there is none)."""
    text = unit.declaration
    cached = getattr(unit, "_cts_declaration_section_cache", None)
    if cached is not None and cached[0] is text:
        return cached[1]
    section = _section(unit, "declaration", text)
    unit._cts_declaration_section_cache = (text, section)
    return section
