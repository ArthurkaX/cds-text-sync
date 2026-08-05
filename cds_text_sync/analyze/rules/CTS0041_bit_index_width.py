"""CTS0041 - bit access outside the declared type width."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st import decl
from cds_text_sync.analyze.st.body import body
from cds_text_sync.engine.variable_map import classify_type


_ACCESS = re.compile(r"\b(?P<value>[A-Za-z_]\w*)\s*\.\s*(?P<bit>\d+)")
_WIDTHS = {
    "SINT": 8, "USINT": 8, "BYTE": 8,
    "INT": 16, "UINT": 16, "WORD": 16,
    "DINT": 32, "UDINT": 32, "DWORD": 32,
    "LINT": 64, "ULINT": 64, "LWORD": 64,
}


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    section = body(unit)
    if not section:
        return
    widths = {}
    for member in decl.all_members(unit):
        typ = classify_type(member.get("type", ""))
        base = str(typ.get("base", "")).upper()
        if base in _WIDTHS:
            widths[member["name"].lower()] = _WIDTHS[base]

    for match in _ACCESS.finditer(section.text):
        width = widths.get(match.group("value").lower())
        bit = int(match.group("bit"))
        if width is None or bit < width:
            continue
        absolute = section.at(match.start("bit"))
        yield finding_in(
            message=(
                f"bit index {match.group('bit')} is outside the "
                f"{width}-bit width of '{match.group('value')}'"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end("bit")),
            anchor=match.group(0),
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0041",
    title="Bit index outside type width",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A literal bit index must fit within the declared operand width.",
    topic="Correctness",
    check=check,
)
