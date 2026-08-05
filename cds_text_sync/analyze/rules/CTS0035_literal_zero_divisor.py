"""CTS0035 - division by a literal zero."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body


# Covers ordinary and typed ST numeric literals (for example ``0``, ``0.0``
# and ``DINT#0``).  The token boundary prevents matching the zero in ``10``.
_ZERO_DIVISOR = re.compile(
    r"/(?P<space>\s*)(?P<zero>"
    r"(?:(?:BOOL|BYTE|WORD|DWORD|LWORD|SINT|USINT|INT|UINT|DINT|UDINT|"
    r"LINT|ULINT|REAL|LREAL)#)?"
    r"0(?:\.0*)?(?:[eE][+-]?0+)?"
    r")\b",
    re.IGNORECASE,
)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for match in _ZERO_DIVISOR.finditer(section.text):
        start = section.at(match.start("zero"))
        end = section.at(match.end("zero"))
        literal = match.group("zero")
        yield finding_in(
            message="division by a literal zero",
            unit=unit,
            offset=start,
            end_offset=end,
            anchor=literal,
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0035",
    title="Division by literal zero",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Division expressions whose divisor is a literal zero.",
    topic="Correctness",
    check=check,
)
