"""CTS0040 - shift amount outside the operand width."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.declarations import classify_type


_CALL = re.compile(
    r"\b(?:SHL|SHR|ROL|ROR)\s*\(\s*(?P<value>[A-Za-z_]\w*)\s*,\s*"
    r"(?P<amount>[+-]?\d+)\s*\)",
    re.IGNORECASE,
)
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
    types = {}
    for member in decl.all_members(unit):
        typ = classify_type(member.get("type", ""))
        base = str(typ.get("base", "")).upper()
        if base in _WIDTHS:
            types[member["name"].lower()] = _WIDTHS[base]

    for match in _CALL.finditer(section.text):
        width = types.get(match.group("value").lower())
        amount = int(match.group("amount"))
        if width is None or amount < width:
            continue
        absolute = section.at(match.start("amount"))
        yield finding_in(
            message=(
                f"shift amount {match.group('amount')} is outside the "
                f"{width}-bit width of '{match.group('value')}'"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end("amount")),
            anchor=match.group("amount"),
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0040",
    title="Shift amount outside operand width",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A literal shift amount is greater than or equal to the operand width.",
    topic="Correctness",
    check=check,
)
