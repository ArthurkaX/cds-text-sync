"""CTS0094 - function-block outputs with no external project consumer."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_FIELD_ACCESS = re.compile(
    r"\b(?P<instance>[A-Za-z_]\w*)\s*\.\s*(?P<field>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)


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


def _type_names(unit):
    qualified = unit.qualified_name.casefold()
    return {qualified, qualified.rsplit(".", 1)[-1]}


def _matches_type(type_name, names):
    normalized = (type_name or "").strip().casefold()
    return normalized in names or normalized.rsplit(".", 1)[-1] in names


def _owner_units(ctx, owner):
    visible_ids = {unit.id for unit in ctx.units}
    return [
        unit
        for unit in ctx.snapshot.units_owned_by(owner.qualified_name)
        if unit.id in visible_ids
    ]


def _external_instances(ctx, owner):
    names = _type_names(owner)
    instances = {}
    owner_ids = {owner.id} | {unit.id for unit in _owner_units(ctx, owner)}
    for unit in ctx.units:
        if unit.id in owner_ids:
            continue
        for member in decl.all_members(unit):
            name = member.get("name", "")
            if name and _matches_type(member.get("type", ""), names):
                instances[name.casefold()] = name
    return instances


def _externally_read(ctx, owner, field, instances):
    field_key = field.casefold()
    if not instances:
        return False
    owner_ids = {owner.id} | {unit.id for unit in _owner_units(ctx, owner)}
    for unit in ctx.units:
        if unit.id in owner_ids or not unit.implementation:
            continue
        for match in _FIELD_ACCESS.finditer(body(unit).text):
            if (
                match.group("instance").casefold() in instances
                and match.group("field").casefold() == field_key
            ):
                return True
    return False


def check(ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    for owner in ctx.units:
        if owner.kind != K.FUNCTION_BLOCK:
            continue
        outputs = decl.output_members(owner)
        if not outputs:
            continue
        instances = _external_instances(ctx, owner)
        for member in outputs:
            name = member.get("name", "")
            if not name or _externally_read(ctx, owner, name, instances):
                continue
            yield finding_in(
                message=(
                    f"function-block output '{name}' has no external read "
                    "in the analyzed Structured Text"
                ),
                unit=owner,
                offset=_member_offset(owner, member),
                anchor=name,
                context=f"{name} : {member.get('type', '')}",
            )


RULE = RuleSpec(
    id="CTS0094",
    title="Unused function-block output",
    severity="suspicious",
    scope=Scope.PROJECT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="ANY",
    summary="A function-block output has no external consumer in the project view.",
    topic="Interfaces",
    check=check,
)
