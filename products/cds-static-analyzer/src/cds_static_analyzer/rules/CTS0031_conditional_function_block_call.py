"""CTS0031 - stateful function-block calls hidden behind conditions."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.blocks import Block, tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.decl import all_members


_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(")


def _contains(node: Block, offset: int, end: int) -> bool:
    return node.start_offset <= offset < (node.end_offset or end)


def _branch_index(node: Block, offset: int):
    for index, (_label, start, end) in enumerate(node.branches):
        if start <= offset < end:
            return index
    return None


def _conditional_context(node: Block, offset: int, end: int):
    for child in node.children:
        if not _contains(child, offset, end):
            continue
        if child.kind in ("IF", "CASE") and _branch_index(child, offset) is not None:
            return child.kind
        nested = _conditional_context(child, offset, end)
        if nested is not None:
            return nested
    return None


def _function_block_types(ctx):
    names = set()
    for unit in ctx.units:
        if unit.kind != K.FUNCTION_BLOCK:
            continue
        qualified = unit.qualified_name.casefold()
        names.add(qualified)
        names.add(qualified.rsplit(".", 1)[-1])
    return names


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    block_types = _function_block_types(ctx)
    instances = {
        member.get("name", "").casefold()
        for member in all_members(unit)
        if member.get("name")
        and (
            member.get("type", "").strip().casefold() in block_types
            or member.get("type", "").strip().casefold().rsplit(".", 1)[-1]
            in block_types
        )
    }
    if not instances:
        return

    root = tree(unit)
    end = section.at(len(section.text))
    for match in _CALL.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in instances:
            continue
        absolute = section.at(match.start("name"))
        conditional = _conditional_context(root, absolute, end)
        if conditional is None:
            continue
        yield finding_in(
            message=(
                f"stateful function-block instance '{name}' is called "
                f"conditionally inside {conditional}; its state may not "
                "be updated on every cycle"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end("name")),
            anchor=name,
            context=f"{name}(...) in {conditional}",
        )


RULE = RuleSpec(
    id="CTS0031",
    title="Conditional function-block call",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="Stateful function-block instances should be called every cycle.",
    topic="Correctness",
    check=check,
)
