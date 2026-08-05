"""CTS0021 - assignments that copy a variable to itself."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_SELF_ASSIGNMENT = re.compile(
    r"(?is)^\s*(?P<target>[A-Za-z_]\w*)\s*:=\s*(?P<source>[A-Za-z_]\w*)\s*$"
)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for offset, statement in section.statements():
        match = _SELF_ASSIGNMENT.fullmatch(statement)
        if not match:
            continue
        target = match.group("target")
        source = match.group("source")
        if target.casefold() != source.casefold():
            continue
        target_offset = offset + match.start("target")
        yield finding_in(
            message=f"assignment to '{target}' has no effect",
            unit=unit,
            offset=target_offset,
            end_offset=target_offset + len(target),
            anchor=target,
            context=statement,
        )


RULE = RuleSpec(
    id="CTS0021",
    title="Self-assignment",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Simple assignments that write a variable back to itself.",
    topic="Dead code",
    check=check,
)
