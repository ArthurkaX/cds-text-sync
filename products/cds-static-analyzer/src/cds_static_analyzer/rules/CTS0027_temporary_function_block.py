"""CTS0027 - local function-block instances lose state between calls."""

from __future__ import annotations

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.decl import members_in_scope


def _member_offset(unit, member):
    section = declaration(unit)
    if not section:
        return None
    lines = unit.declaration.split("\n")
    index = member.get("line", 0) - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return section.at(sum(len(lines[line]) + 1 for line in range(index)) + position)


def _function_block_names(ctx):
    names = set()
    for unit in ctx.units:
        if unit.kind != K.FUNCTION_BLOCK:
            continue
        qualified = unit.qualified_name.casefold()
        names.add(qualified)
        names.add(qualified.rsplit(".", 1)[-1])
    return names


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    if unit.kind not in (K.FUNCTION, K.METHOD):
        return
    block_names = _function_block_names(ctx)
    if not block_names:
        return

    scopes = ("VAR", "VAR_TEMP")
    for member in members_in_scope(unit, scopes):
        type_name = member.get("type", "").strip().casefold()
        if type_name not in block_names and type_name.rsplit(".", 1)[-1] not in block_names:
            continue
        yield finding_in(
            message=(
                f"local function-block instance '{member['name']}' is "
                "recreated on each call"
            ),
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=member["name"],
            context=f"{member['name']} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0027",
    title="Temporary function-block instance",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds=(K.FUNCTION, K.METHOD),
    summary="Local function-block instances are recreated on every call.",
    topic="Correctness",
    check=check,
)
