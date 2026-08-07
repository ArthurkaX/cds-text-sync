"""CTS0094 - function-block outputs with no external project consumer."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_DOTTED_ACCESS = re.compile(
    r"\b(?P<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)+)\b",
    re.IGNORECASE,
)
_CALL = re.compile(
    r"\b(?P<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*\(",
    re.IGNORECASE,
)
_OUTPUT_MAPPING = re.compile(
    r"\b(?P<output>[A-Za-z_]\w*)\s*=>\s*(?P<target>[^,;)\r\n]*)",
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
                if unit.kind in (K.GVL, K.GVL_PERSISTENT):
                    path = f"{unit.qualified_name}.{name}"
                else:
                    path = name
                instances[path.casefold()] = path

                # Non-qualified GVL access is legal when the GVL is not
                # marked ``qualified_only``.  Add it only when no two GVLs
                # expose the same FB instance name; otherwise guessing would
                # create a false consumer.
                if unit.kind in (K.GVL, K.GVL_PERSISTENT):
                    simple = name.casefold()
                    previous = instances.get(simple)
                    if previous is None:
                        instances[simple] = path
                    elif previous != path:
                        instances.pop(simple, None)
    return instances


def _externally_read(ctx, owner, field, instances):
    field_key = field.casefold()
    if not instances:
        return False
    owner_ids = {owner.id} | {unit.id for unit in _owner_units(ctx, owner)}
    for unit in ctx.units:
        section = body(unit)
        if unit.id in owner_ids or not section:
            continue
        text = section.text
        for match in _DOTTED_ACCESS.finditer(text):
            parts = [part.strip().casefold() for part in match.group("path").split(".")]
            path = ".".join(parts[:-1])
            if path in instances and parts[-1] == field_key:
                return True

        # CODESYS also exposes an FB output through named output mapping:
        # ``instance(Output => destination)``.  A non-empty destination is
        # an external consumer even when no ``instance.Output`` expression
        # appears in the caller.
        for call in _CALL.finditer(text):
            path = ".".join(part.strip().casefold() for part in call.group("path").split("."))
            if path not in instances:
                continue
            end = text.find(";", call.start())
            if end < 0:
                end = len(text)
            for mapping in _OUTPUT_MAPPING.finditer(text, call.end(), end):
                if (
                    mapping.group("output").casefold() == field_key
                    and mapping.group("target").strip()
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
