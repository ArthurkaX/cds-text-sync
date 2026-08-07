"""CTS0098 - AND and OR mixed without explicit grouping."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_AND = re.compile(r"\bAND\b", re.IGNORECASE)
_OR = re.compile(r"\bOR\b", re.IGNORECASE)


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for _line_number, offset, line in section.lines():
        if "(" in line or ")" in line:
            continue
        and_match = _AND.search(line)
        or_match = _OR.search(line)
        if and_match is None or or_match is None:
            continue
        expression = line.strip().rstrip(";").strip()
        if not expression:
            continue
        start = offset + len(line) - len(line.lstrip())
        yield finding_in(
            message=(
                f"boolean expression '{expression}' mixes AND and OR without "
                "parentheses"
            ),
            unit=unit,
            offset=start,
            end_offset=start + len(expression),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0098",
    title="Mixed AND and OR without parentheses",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Mixed boolean operators should be explicitly grouped with parentheses.",
    topic="Correctness",
    check=check,
)
