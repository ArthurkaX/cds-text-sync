"""statements.py - Semicolon-terminated statement iteration (shared).

The text is already blanked (comments and string contents are spaces), so a
``;`` inside a string or comment never splits a statement. This is the same
logic the analyzer's ``Section.statements()`` used to inline; it lives here so
the analyzer and the FSM extractor share one definition.
"""

from __future__ import print_function

import re


def statements(text, base=0):
    """Yield ``(absolute_offset, statement)`` for semicolon-terminated
    statements in the blanked *text*, trailing ``;`` stripped and leading
    whitespace skipped. Offsets are local offsets into *text* plus *base*."""
    start = 0
    for match in re.finditer(r";", text):
        raw = text[start : match.end()]
        leading = len(raw) - len(raw.lstrip())
        statement = raw.strip()
        if statement:
            yield base + start + leading, statement[:-1]
        start = match.end()
