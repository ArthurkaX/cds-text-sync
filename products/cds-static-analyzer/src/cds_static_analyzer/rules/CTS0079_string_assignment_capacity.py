"""CTS0079 - a bounded STRING assignment can truncate the source value."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body


_STRING_TYPE = re.compile(r"^(?P<wide>W)?STRING\s*\(\s*(?P<size>\d+)\s*\)$", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"\b(?P<target>[A-Za-z_]\w*)\s*:=\s*(?P<source>[A-Za-z_]\w*)\b"
)


def _capacity(type_name):
    match = _STRING_TYPE.fullmatch((type_name or "").strip())
    return int(match.group("size")) if match else None


def _string_members(unit):
    result = {}
    for member in decl.all_members(unit):
        capacity = _capacity(member.get("type", ""))
        if capacity is not None:
            result[member.get("name", "").casefold()] = capacity
    return result


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    capacities = _string_members(unit)
    if not capacities:
        return
    for match in _ASSIGNMENT.finditer(section.text):
        target = match.group("target")
        source = match.group("source")
        target_capacity = capacities.get(target.casefold())
        source_capacity = capacities.get(source.casefold())
        if (
            target_capacity is None
            or source_capacity is None
            or source_capacity <= target_capacity
        ):
            continue
        expression = match.group(0)
        yield finding_in(
            message=(
                f"STRING({source_capacity}) value assigned to {target} STRING({target_capacity}) "
                "may be truncated"
            ),
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0079",
    title="String assignment may truncate the destination",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Assignments between explicitly bounded strings must preserve the destination capacity.",
    topic="Correctness",
    check=check,
)
