"""CTS0011 - local variables assigned but never read."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body
from cds_text_sync.analyze.st.decl import members_in_scope

_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z_]\w*)(?![A-Za-z0-9_])")
_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=")


def _member_offset(unit, member):
    line = member.get("line")
    if not line or not unit.declaration:
        return None
    lines = unit.declaration.split("\n")
    index = line - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return sum(len(lines[k]) + 1 for k in range(index)) + position


def _assigned_and_read(section):
    clean = section.text
    assigned = {match.group("name").lower() for match in _ASSIGNMENT.finditer(clean)}
    read = set()
    for match in _IDENTIFIER.finditer(clean):
        name = match.group("name").lower()
        before = clean[: match.start()].rstrip()
        after = clean[match.end() :].lstrip()
        if after.startswith(":="):
            continue
        # A qualified field is not a read of a local variable with the same name.
        if before.endswith((".", "^")):
            continue
        read.add(name)
    return assigned, read


def check(unit, ctx):
    """Report local variables that receive a value but are never read."""
    ctx.capability(Capability.DECLARATIONS)
    locals_ = members_in_scope(unit, ("VAR", "VAR_TEMP", "VAR_STAT"))
    if not locals_ or not unit.implementation:
        return

    assigned, read = _assigned_and_read(body(unit))
    for member in locals_:
        name = member["name"]
        lowered = name.lower()
        if lowered not in assigned or lowered in read:
            continue
        yield finding_in(
            message=f"local variable '{name}' is assigned but never read",
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0011",
    title="Assigned local not read",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Local variables that are assigned but never read.",
    topic="Dead code",
    check=check,
)
