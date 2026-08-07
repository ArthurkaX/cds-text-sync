"""CTS0076 - VAR_IN_OUT parameters that are never written."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body, declaration

_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<name>[A-Za-z_]\w*)"
    r"(?:\s*\.\s*[A-Za-z_]\w*|\s*\[[^\]]+\])*\s*:=",
    re.IGNORECASE,
)
_OUTPUT_ARGUMENT = re.compile(
    r"=>\s*(?P<name>[A-Za-z_]\w*)\b", re.IGNORECASE
)


def _member_offset(unit, member):
    section = declaration(unit)
    lines = (unit.declaration or "").split("\n")
    index = member.get("line", 0) - 1
    if not section or not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return section.at(sum(len(lines[i]) + 1 for i in range(index)) + position)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    inout = {
        member.get("name", "").casefold(): member
        for member in decl.all_members(unit)
        if (member.get("scope") or "").upper() == "VAR_IN_OUT"
        and member.get("name")
    }
    if not inout:
        return

    written = {
        match.group("name").casefold()
        for match in _ASSIGNMENT.finditer(section.text)
    }
    written.update(
        match.group("name").casefold()
        for match in _OUTPUT_ARGUMENT.finditer(section.text)
    )
    for folded, member in inout.items():
        if folded in written:
            continue
        name = member["name"]
        yield finding_in(
            message=(
                f"VAR_IN_OUT '{name}' is never written; declare it as "
                "VAR_INPUT if it is read-only"
            ),
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0076",
    title="VAR_IN_OUT never written",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="VAR_IN_OUT parameters that are only read should be VAR_INPUT.",
    topic="Interfaces",
    check=check,
)
