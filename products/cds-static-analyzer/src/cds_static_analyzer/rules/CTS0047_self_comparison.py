"""CTS0047 - comparing a simple expression with itself is redundant."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body


_COMPARISON = re.compile(
    r"(?P<left>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?)\s*"
    r"(?P<operator><>|<=|>=|=|<|>)\s*"
    r"(?P<right>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?)",
    re.IGNORECASE,
)
_ALWAYS_TRUE = {"=", "<=", ">="}


def _display(value):
    return re.sub(r"\s+", "", value)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for match in _COMPARISON.finditer(section.text):
        left = _display(match.group("left"))
        right = _display(match.group("right"))
        if left.casefold() != right.casefold():
            continue

        operator = match.group("operator")
        result = "always true" if operator in _ALWAYS_TRUE else "always false"
        absolute = section.at(match.start())
        expression = match.group(0)
        yield finding_in(
            message=(
                f"self-comparison '{expression}' is {result} and does not "
                "test two independent values"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0047",
    title="Self-comparison",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A value is compared with itself, making the result constant.",
    topic="Correctness",
    check=check,
)
