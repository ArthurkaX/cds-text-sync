"""CTS0020 - writes to VAR_INPUT parameters."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body

_ASSIGNMENT = re.compile(
    r"(?is)^\s*(?P<lhs>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*|\s*\[[^\]]+\])*)\s*:="
)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    declarations = ctx.capability(Capability.DECLARATIONS)
    section = body(unit)
    if not section:
        return

    inputs = {
        member["name"].upper()
        for member in declarations.input_members(unit)
    }
    if not inputs:
        return

    for offset, statement in section.statements():
        match = _ASSIGNMENT.match(statement)
        if not match:
            continue
        lhs = match.group("lhs")
        root = re.match(r"[A-Za-z_]\w*", lhs).group()
        if root.upper() not in inputs:
            continue
        # Section.statements() already returns an absolute unit offset.
        lhs_offset = offset + match.start("lhs")
        yield finding_in(
            message=f"input '{root}' is written inside the POU",
            unit=unit,
            offset=lhs_offset,
            end_offset=lhs_offset + len(lhs),
            anchor=root,
            context=statement,
        )


RULE = RuleSpec(
    id="CTS0020",
    title="Write to input variable",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="VAR_INPUT parameters must not be modified by their owner POU.",
    topic="Interfaces",
    check=check,
)
