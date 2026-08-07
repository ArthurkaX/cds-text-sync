"""CTS0058 - a 32-bit TIME literal is outside its representable range."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body, declaration


_TIME_LITERAL = re.compile(
    r"(?<![A-Za-z0-9_])(?P<literal>(?:TIME|T)#(?P<sign>[+-]?)"
    r"(?P<parts>(?:\d+(?:\.\d+)?(?:ms|us|ns|d|h|m|s))+))\b",
    re.IGNORECASE,
)
_UNIT_MILLISECONDS = {
    "d": Decimal("86400000"),
    "h": Decimal("3600000"),
    "m": Decimal("60000"),
    "s": Decimal("1000"),
    "ms": Decimal("1"),
    "us": Decimal("0.001"),
    "ns": Decimal("0.000001"),
}
_PART = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|us|ns|d|h|m|s)", re.IGNORECASE)
_MAX_TIME_MILLISECONDS = Decimal(2**32 - 1)


def _milliseconds(sign, parts):
    total = Decimal(0)
    position = 0
    for match in _PART.finditer(parts):
        if match.start() != position:
            return None
        try:
            value = Decimal(match.group("value"))
        except InvalidOperation:
            return None
        total += value * _UNIT_MILLISECONDS[match.group("unit").lower()]
        position = match.end()
    if position != len(parts):
        return None
    return -total if sign == "-" else total


def _scan_section(unit, section):
    if not section:
        return
    for match in _TIME_LITERAL.finditer(section.text):
        value = _milliseconds(match.group("sign"), match.group("parts"))
        if value is None or 0 <= value <= _MAX_TIME_MILLISECONDS:
            continue
        literal = match.group("literal")
        yield finding_in(
            message=(
                f"TIME literal {literal} evaluates to {value} ms outside "
                f"the 32-bit TIME range [0..{_MAX_TIME_MILLISECONDS} ms]"
            ),
            unit=unit,
            offset=section.at(match.start("literal")),
            end_offset=section.at(match.end("literal")),
            anchor=literal,
            context=literal,
        )


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    yield from _scan_section(unit, declaration(unit))
    yield from _scan_section(unit, body(unit))


RULE = RuleSpec(
    id="CTS0058",
    title="TIME literal outside range",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A 32-bit TIME literal is outside its representable range.",
    topic="Correctness",
    check=check,
)
