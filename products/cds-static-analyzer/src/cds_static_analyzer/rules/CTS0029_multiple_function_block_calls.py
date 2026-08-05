"""CTS0029 - one function-block instance is called more than once per path."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.blocks import Block, tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.decl import all_members


_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(")
_CALLABLE_KINDS = set(K.CALLABLE)


def _contains(node: Block, offset: int, end: int) -> bool:
    return node.start_offset <= offset < (node.end_offset or end)


def _branch_index(node: Block, offset: int):
    for index, (_label, start, end) in enumerate(node.branches):
        if start <= offset < end:
            return index
    return None


def _context(node: Block, offset: int, end: int):
    key = [(id(node), _branch_index(node, offset))]
    for child in node.children:
        if _contains(child, offset, end):
            return tuple(key) + _context(child, offset, end)
    return tuple(key)


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
    if unit.kind not in _CALLABLE_KINDS:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    fb_types = _function_block_types(ctx)
    if not fb_types:
        return
    instances = {
        member.get("name", "").casefold()
        for member in all_members(unit)
        if member.get("name")
        and (
            member.get("type", "").strip().casefold() in fb_types
            or member.get("type", "").strip().casefold().rsplit(".", 1)[-1]
            in fb_types
        )
    }
    if not instances:
        return

    root = tree(unit)
    end = section.at(len(section.text))
    calls = {}
    for match in _CALL.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in instances:
            continue
        absolute = section.at(match.start("name"))
        key = (name.casefold(), _context(root, absolute, end))
        calls.setdefault(key, []).append((name, match))

    for occurrences in calls.values():
        for name, match in occurrences[1:]:
            yield finding_in(
                message=(
                    f"function-block instance '{name}' is called more than once "
                    "in the same control-flow path"
                ),
                unit=unit,
                offset=section.at(match.start("name")),
                end_offset=section.at(match.end("name")),
                anchor=name,
                context=f"{name}(...)" ,
            )


RULE = RuleSpec(
    id="CTS0029",
    title="Multiple calls to one function-block instance",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A function-block instance is called more than once on one path.",
    topic="Correctness",
    check=check,
)
