"""
visu_color.py - CTS0003: literal ExplicitColor beside a live NamedColor.

CODESYS visu XML writes a font/colour member twice: an ``ExplicitColor``
literal and a ``NamedColor`` link to the visual style. While the link is
present the literal is ignored (verified in the IDE; see
``visu/builder.py``), so a literal beside a live NamedColor is dead code that
misleads the next reader into thinking the screen really sets that colour.

A ``<Null Name="NamedColor" />`` breaks the link: then the ExplicitColor
literal is the actual colour and is not flagged.
"""

from __future__ import annotations

import re

from cds_text_sync.analyze.rules_api import finding_in
from cds_text_sync.analyze.st import kinds as K

RULE_ID = "CTS0003"
SEVERITY = "style"

# Same constants as visu/_builder_base.py.
_MEMBER_TYPE = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}"
_COLOR_TYPE = "{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}"

_MEMBER_OPEN_RE = re.compile(
    r'<Single Type="' + re.escape(_MEMBER_TYPE) + r'" Method="IArchivable">'
)
_EXPLICIT_RE = re.compile(r'<Single Name="ExplicitColor" Type="int">(-?\d+)</Single>')
_LIVE_NAMED_RE = re.compile(
    r'<Single Name="NamedColor" Type="'
    + re.escape(_COLOR_TYPE)
    + r'" Method="IArchivable">'
)

_OPEN_TAG = "<Single"
_CLOSE_TAG = "</Single>"


def member_blocks(text):
    """Yield (start, end) of every balanced member element in *text*."""
    pos = 0
    while True:
        m = _MEMBER_OPEN_RE.search(text, pos)
        if m is None:
            return
        start = m.start()
        depth = 1
        i = m.end()
        while i < len(text):
            next_open = text.find(_OPEN_TAG, i)
            next_close = text.find(_CLOSE_TAG, i)
            if next_close < 0:
                break
            if next_open >= 0 and next_open < next_close:
                depth += 1
                i = next_open + len(_OPEN_TAG)
            else:
                depth -= 1
                if depth == 0:
                    yield start, next_close + len(_CLOSE_TAG)
                    break
                i = next_close + len(_CLOSE_TAG)
        pos = start + 1


def check(unit, ctx):
    """Flag ExplicitColor literals inside members with a live NamedColor."""
    if unit.kind != K.VISUALIZATION:
        return
    text = unit.text or ""
    for start, end in member_blocks(text):
        inner = text[start:end]
        explicit = _EXPLICIT_RE.search(inner)
        if explicit is None:
            continue
        if _LIVE_NAMED_RE.search(inner) is None:
            continue
        value = explicit.group(1)
        value_start = start + explicit.start(1)
        value_end = start + explicit.end(1)
        canonical = _canonical_name(inner)
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message=(
                f"ExplicitColor {value} is ignored: a live NamedColor"
                + (f" ({canonical})" if canonical else "")
                + " takes precedence; the literal is dead code"
            ),
            unit=unit,
            offset=value_start,
            end_offset=value_end,
            anchor=f"{value}:{canonical or ''}",
            context=_explicit_line(inner),
            rule_title="Dead explicit color",
        )


def _canonical_name(inner):
    m = re.search(r'<Single Name="CanonicalName" Type="string">([^<]*)</Single>', inner)
    return m.group(1) if m else ""


def _explicit_line(inner):
    for raw in inner.split("\n"):
        if "ExplicitColor" in raw:
            return raw.strip()
    return ""
