"""CTS0009: VAR_OUTPUT members that are never assigned."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise, trim_strings
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0009"
SEVERITY = "suspicious"

_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=")


def _assigned_names(snapshot, unit):
    bodies = []
    if unit.implementation:
        bodies.append(unit.implementation)
    for owned in snapshot.units_owned_by(unit.qualified_name):
        if owned.implementation:
            bodies.append(owned.implementation)

    assigned = set()
    for body in bodies:
        clean = trim_strings(blank_noise(body))
        assigned.update(match.group("name").lower() for match in _ASSIGNMENT.finditer(clean))
    return assigned


def _member_offset(unit, member):
    line = member.get("line")
    if not line:
        return None
    lines = (unit.declaration or "").split("\n")
    index = line - 1
    if not 0 <= index < len(lines):
        return None
    line_text = lines[index]
    position = line_text.find(member["name"])
    if position < 0:
        return None
    return sum(len(lines[k]) + 1 for k in range(index)) + position


def check(unit, ctx):
    """Report VAR_OUTPUT members with no direct assignment in visible code."""
    declarations = ctx.capability(Capability.DECLARATIONS)
    outputs = declarations.output_members(unit)
    if not outputs:
        return

    assigned = _assigned_names(ctx.snapshot, unit)
    for member in outputs:
        name = member["name"]
        if name.lower() in assigned:
            continue
        offset = _member_offset(unit, member)
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message=f"output '{name}' is never assigned by {unit.qualified_name}",
            unit=unit,
            offset=offset,
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
            rule_title="Output not assigned",
        )
