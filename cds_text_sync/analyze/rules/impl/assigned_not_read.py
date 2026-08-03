"""CTS0011: local variables assigned but never read."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise, trim_strings
from cds_text_sync.analyze.rules_api import finding_in
from cds_text_sync.analyze.st.decl import members_in_scope

RULE_ID = "CTS0011"
SEVERITY = "suspicious"

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


def _assigned_and_read(body):
    clean = trim_strings(blank_noise(body))
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
    body = unit.implementation
    if not locals_ or not body:
        return

    assigned, read = _assigned_and_read(body)
    for member in locals_:
        name = member["name"]
        lowered = name.lower()
        if lowered not in assigned or lowered in read:
            continue
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message=f"local variable '{name}' is assigned but never read",
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
            rule_title="Assigned local not read",
        )
