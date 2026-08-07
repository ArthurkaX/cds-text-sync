"""CTS0070 - local symbols hide globals or FB members."""

from __future__ import annotations

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl, kinds as K
from cds_static_analyzer.st.body import declaration

_LOCAL_SCOPES = {"VAR", "VAR_TEMP", "VAR_STAT", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}


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


def _global_names(ctx):
    names = set()
    for candidate in ctx.units:
        if candidate.kind not in (K.GVL, K.GVL_PERSISTENT):
            continue
        names.update(member["name"].casefold() for member in decl.all_members(candidate))
    return names


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    global_names = _global_names(ctx)
    owner = ctx.snapshot.find_unit(unit.owner_id) if unit.owner_id else None
    owner_names = {
        member["name"].casefold() for member in decl.all_members(owner)
    } if owner is not None else set()
    seen = {}
    for member in decl.all_members(unit):
        name = member.get("name", "")
        if not name or member.get("scope", "").upper() not in _LOCAL_SCOPES:
            continue
        folded = name.casefold()
        hidden = "global variable" if folded in global_names else None
        if folded in owner_names:
            hidden = f"member of '{owner.qualified_name}'"
        if hidden:
            yield finding_in(
                message=f"local symbol '{name}' hides a {hidden}",
                unit=unit,
                offset=_member_offset(unit, member),
                anchor=name,
                context=f"{name} : {member.get('type', '')}",
            )
        if folded in seen:
            yield finding_in(
                message=f"local symbol '{name}' duplicates another declaration in this POU",
                unit=unit,
                offset=_member_offset(unit, member),
                anchor=name,
                context=f"{name} : {member.get('type', '')}",
            )
        seen[folded] = member


RULE = RuleSpec(
    id="CTS0070",
    title="Shadowed symbol",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="Local symbols must not hide global variables or owning FB members.",
    topic="Code quality",
    check=check,
)
