"""CTS0075 - FUNCTION result is not assigned on every control-flow path."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import Block, tree
from cds_static_analyzer.st.body import body, declaration

_HEADER = re.compile(
    r"^\s*FUNCTION\s+(?P<name>[A-Za-z_]\w*)\b", re.IGNORECASE | re.MULTILINE
)
_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=", re.IGNORECASE)


def _inside(node, offset):
    return node.start_offset <= offset < (node.end_offset or offset + 1)


def _children_in(node, start, end):
    return [
        child
        for child in node.children
        if start <= child.start_offset < end
        and (child.end_offset is None or child.end_offset <= end)
    ]


def _guaranteed(node: Block, assignments, name):
    """Return whether every path through *node* assigns *name*."""
    if node.end_offset is None:
        return False
    if node.kind == "IF":
        branches = node.branches
        return bool(branches) and len(branches) >= 2 and all(
            _guaranteed_range(node, assignments, name, start, end)
            for _label, start, end in branches
        )
    if node.kind == "CASE":
        branches = node.branches
        return bool(branches) and any(label == "ELSE" for label, _s, _e in branches) and all(
            _guaranteed_range(node, assignments, name, start, end)
            for _label, start, end in branches
        )
    return False


def _guaranteed_range(parent, assignments, name, start, end):
    children = _children_in(parent, start, end)
    events = []
    for candidate, offset in assignments:
        if (
            candidate.casefold() == name.casefold()
            and start <= offset < end
            and not any(_inside(child, offset) for child in children)
        ):
            events.append((offset, "assignment"))
    for child in children:
        events.append((child.start_offset, child))
    events.sort(key=lambda item: item[0])

    for _offset, event in events:
        if event == "assignment":
            return True
        if _guaranteed(event, assignments, name):
            return True
    return False


def _header_location(unit, name):
    section = declaration(unit)
    match = _HEADER.search(unit.declaration or "")
    if not section or not match:
        return None, None
    start = section.at(match.start("name"))
    return start, start + len(name)


def check(unit, ctx):
    if unit.kind != "function":
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    header = _HEADER.search(unit.declaration or "")
    section = body(unit)
    if not header or not section:
        return

    name = header.group("name")
    assignments = [
        (match.group("name"), section.at(match.start("name")))
        for match in _ASSIGNMENT.finditer(section.text)
        if match.group("name").casefold() == name.casefold()
    ]
    root = tree(unit)
    root_end = section.at(len(section.text))
    guaranteed = bool(assignments) and _guaranteed_range(
        root, assignments, name, root.start_offset, root_end
    )
    if guaranteed:
        return

    if assignments:
        offset = assignments[0][1]
        end_offset = offset + len(name)
    else:
        offset, end_offset = _header_location(unit, name)
    yield finding_in(
        message=f"FUNCTION result '{name}' is not assigned on all control-flow paths",
        unit=unit,
        offset=offset,
        end_offset=end_offset,
        anchor=name,
        context=f"FUNCTION {name}",
    )


RULE = RuleSpec(
    id="CTS0075",
    title="Function result not assigned on all paths",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT, Capability.BLOCK_STRUCTURE},
    kinds="function",
    summary="FUNCTION results must be assigned on every reachable return path.",
    topic="Correctness",
    check=check,
)
