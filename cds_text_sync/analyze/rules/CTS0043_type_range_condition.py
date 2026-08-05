"""CTS0043 - comparison constant outside a variable's type range."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st import decl
from cds_text_sync.analyze.st.body import body
from cds_text_sync.engine.variable_map import classify_type


_COMPARE = re.compile(
    r"\b(?P<value>[A-Za-z_]\w*)\s*(?P<op><>|<=|>=|=|<|>)\s*"
    r"(?P<const>[+-]?\d+)\b"
)
_RANGES = {
    "SINT": (-128, 127), "USINT": (0, 255), "BYTE": (0, 255),
    "INT": (-32768, 32767), "UINT": (0, 65535), "WORD": (0, 65535),
    "DINT": (-2147483648, 2147483647), "UDINT": (0, 4294967295),
    "DWORD": (0, 4294967295),
    "LINT": (-9223372036854775808, 9223372036854775807),
    "ULINT": (0, 18446744073709551615), "LWORD": (0, 18446744073709551615),
}


def _truth(op, left, right):
    return {"=": left == right, "<>": left != right, "<": left < right,
            "<=": left <= right, ">": left > right, ">=": left >= right}[op]


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    section = body(unit)
    if not section:
        return
    ranges = {}
    for member in decl.all_members(unit):
        typ = classify_type(member.get("type", ""))
        base = str(typ.get("base", "")).upper()
        if base in _RANGES:
            ranges[member["name"].lower()] = _RANGES[base]

    for match in _COMPARE.finditer(section.text):
        limits = ranges.get(match.group("value").lower())
        if limits is None:
            continue
        constant = int(match.group("const"))
        low, high = limits
        at_low = _truth(match.group("op"), low, constant)
        at_high = _truth(match.group("op"), high, constant)
        if at_low != at_high:
            continue
        result = "always true" if at_low else "always false"
        absolute = section.at(match.start("value"))
        yield finding_in(
            message=(
                f"comparison is {result} for the full type range "
                f"[{low}..{high}]"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end()),
            anchor=match.group(0),
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0043",
    title="Comparison outside type range",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A comparison is always true or false across the variable's type range.",
    topic="Correctness",
    check=check,
)
