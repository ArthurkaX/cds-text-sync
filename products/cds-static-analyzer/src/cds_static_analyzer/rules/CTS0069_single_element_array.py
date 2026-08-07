"""CTS0069 - arrays that contain only one element."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import declaration

_ONE_DIMENSION = re.compile(
    r"(?is)^ARRAY\s*\[\s*(?P<low>[^.]+?)\s*\.\.\s*(?P<high>[^]]+?)\s*\]\s+OF\s+"
)


def _member_offset(unit, member):
    section = declaration(unit)
    if not section or not unit.declaration:
        return None
    lines = unit.declaration.split("\n")
    index = member.get("line", 0) - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return section.at(sum(len(lines[i]) + 1 for i in range(index)) + position)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    for member in decl.all_members(unit):
        match = _ONE_DIMENSION.match(member.get("type", "").strip())
        if not match or match.group("low").strip() != match.group("high").strip():
            continue
        name = member.get("name", "")
        yield finding_in(
            message=f"array '{name}' has only one element; use a scalar variable",
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0069",
    title="Single-element array",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="Arrays with one element should be represented by a scalar variable.",
    topic="Style",
    check=check,
)
