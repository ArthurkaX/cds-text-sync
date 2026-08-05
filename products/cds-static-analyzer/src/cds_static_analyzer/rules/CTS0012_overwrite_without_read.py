"""CTS0012 - sequential assignments that overwrite an unread value."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_SIMPLE_ASSIGNMENT = re.compile(
    r"(?s)^\s*(?P<name>[A-Za-z_]\w*)\s*:=\s*(?P<expression>.+?)\s*$"
)
_SELF_UPDATE = re.compile(
    r"(?is)^\s*(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:\+|-|\*|/|MOD|AND|OR|XOR)\s*.+$"
)
_CONCAT_UPDATE = re.compile(
    r"(?is)^\s*CONCAT\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*,"
)


def _is_self_update(name, expression):
    """Return whether an expression intentionally derives its value from itself."""
    self_update = _SELF_UPDATE.fullmatch(expression)
    if self_update and self_update.group("name").lower() == name.lower():
        return True

    concat_update = _CONCAT_UPDATE.match(expression)
    return bool(concat_update and concat_update.group("name").lower() == name.lower())


def check(unit, ctx):
    """Report a simple assignment immediately overwritten by another one."""
    ctx.capability(Capability.ST_TEXT)
    if not unit.implementation:
        return

    previous = None
    for offset, statement in body(unit).statements():
        match = _SIMPLE_ASSIGNMENT.fullmatch(statement)
        if not match:
            previous = None
            continue
        name = match.group("name")
        expression = match.group("expression")
        if (
            previous is not None
            and previous["name"].lower() == name.lower()
            and not _is_self_update(name, expression)
        ):
            old = previous
            yield finding_in(
                message=(
                    f"assignment to '{old['name']}' is overwritten before the value is read"
                ),
                unit=unit,
                offset=old["offset"],
                end_offset=old["offset"] + len(old["name"]),
                anchor=old["name"],
                context=old["statement"],
            )
        previous = {"name": name, "offset": offset, "statement": statement}


RULE = RuleSpec(
    id="CTS0012",
    title="Overwrite without read",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Assignments that are immediately overwritten before being read.",
    topic="Dead code",
    check=check,
)
