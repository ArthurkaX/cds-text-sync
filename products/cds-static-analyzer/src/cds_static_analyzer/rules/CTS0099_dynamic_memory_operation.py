"""CTS0099 - dynamic allocation or release in Structured Text implementation code."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_DYNAMIC_MEMORY = re.compile(r"\b(?P<operation>__NEW|__DELETE)\b", re.IGNORECASE)


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    # A declaration-only source has no execution context.  Do not fall back
    # to the whole unit here: a type or variable name may contain the token.
    if unit.implementation is None:
        return
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for match in _DYNAMIC_MEMORY.finditer(section.text):
        operation = match.group("operation")
        absolute = section.at(match.start("operation"))
        yield finding_in(
            message=(
                f"dynamic memory operation '{operation}' in implementation code; "
                "heap allocation and release can make cycle time and memory "
                "availability unpredictable"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end("operation")),
            anchor=operation,
            context=f"{operation} in POU implementation",
        )


RULE = RuleSpec(
    id="CTS0099",
    title="Dynamic memory operation",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Dynamic memory operations can make cyclic execution unpredictable.",
    topic="Correctness",
    check=check,
)
