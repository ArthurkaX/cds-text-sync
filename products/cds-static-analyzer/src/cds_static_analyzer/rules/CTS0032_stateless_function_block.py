"""CTS0032 - a function block that has the shape of a function."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.decl import var_blocks


_HEADER = re.compile(r"\bFUNCTION_BLOCK\s+(?P<name>[A-Za-z_]\w*)", re.IGNORECASE)
_STATE_SCOPES = {"VAR", "VAR_STAT", "VAR_TEMP"}


def _has_internal_state(unit):
    return any(block.get("scope") in _STATE_SCOPES for block in var_blocks(unit))


def _has_owned_members(unit, ctx):
    owner = unit.qualified_name.casefold()
    return any(
        other.owner_name
        and other.owner_name.casefold() == owner
        and other.kind in (K.METHOD, K.ACTION, K.PROPERTY_GET, K.PROPERTY_SET)
        for other in ctx.units
    )


def check(unit, ctx):
    if unit.kind != K.FUNCTION_BLOCK:
        return
    ctx.capability(Capability.DECLARATIONS)
    if _has_internal_state(unit) or _has_owned_members(unit, ctx):
        return

    section = declaration(unit)
    match = _HEADER.search(section.text if section else unit.text)
    if match is None:
        return
    offset = section.at(match.start("name")) if section else match.start("name")
    name = match.group("name")
    yield finding_in(
        message=(
            f"function block '{name}' has no internal state and may be better "
            "modelled as a FUNCTION"
        ),
        unit=unit,
        offset=offset,
        end_offset=offset + len(name),
        anchor=name,
        context="stateless FUNCTION_BLOCK",
    )


RULE = RuleSpec(
    id="CTS0032",
    title="Stateless function block",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds=K.FUNCTION_BLOCK,
    summary="A stateless function block may be clearer as a FUNCTION.",
    topic="Style",
    check=check,
)
