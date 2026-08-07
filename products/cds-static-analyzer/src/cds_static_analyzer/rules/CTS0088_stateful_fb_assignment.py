"""CTS0088 - assignment copies the state of a function-block instance."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.function_blocks import (
    function_block_types,
    global_members,
    is_function_block_type,
)


_ASSIGNMENT = re.compile(
    r"\b(?P<left>[A-Za-z_]\w*)\s*:=\s*(?P<right>[A-Za-z_]\w*)\b"
)


def _instance_types(unit, ctx):
    names = function_block_types(ctx)
    members = {}
    for member in decl.all_members(unit):
        name = member.get("name", "")
        if name and is_function_block_type(member.get("type", ""), names):
            members[name.casefold()] = member.get("type", "").strip()
    for key, (_owner, member) in global_members(ctx).items():
        if is_function_block_type(member.get("type", ""), names):
            members.setdefault(key, member.get("type", "").strip())
    return members

def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    instances = _instance_types(unit, ctx)
    if not instances:
        return

    for match in _ASSIGNMENT.finditer(section.text):
        left = match.group("left")
        right = match.group("right")
        if left.casefold() == right.casefold():
            continue
        if left.casefold() not in instances or right.casefold() not in instances:
            continue
        yield finding_in(
            message=(
                f"assignment copies state from function-block instance '{right}' "
                f"to '{left}'"
            ),
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=f"{left} := {right}",
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0088",
    title="Stateful function-block assignment",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Assignment between FB instances can silently copy their internal state.",
    topic="Correctness",
    check=check,
)
