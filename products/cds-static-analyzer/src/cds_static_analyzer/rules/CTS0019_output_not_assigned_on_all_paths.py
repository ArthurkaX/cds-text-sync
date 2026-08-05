"""CTS0019 - outputs assigned only on some control-flow paths."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import Block, tree
from cds_static_analyzer.st.body import body

_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=", re.IGNORECASE)
_OUTPUT_ARGUMENT = re.compile(r"=>\s*(?P<name>[A-Za-z_]\w*)", re.IGNORECASE)
_CALLABLE_KINDS = {"function", "method", "action", "property_get", "property_set"}


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
    """Whether every path through *node* assigns *name*.

    This deliberately treats loops as non-guaranteeing: a loop body may run
    zero times. A CASE without ELSE is likewise not exhaustive.
    """
    end = node.end_offset
    if end is None:
        return False

    if node.kind == "IF":
        branches = node.branches
        return bool(branches) and len(branches) >= 2 and all(
            _guaranteed_range(node, assignments, name, branch_start, branch_end)
            for _label, branch_start, branch_end in branches
        )
    if node.kind == "CASE":
        branches = node.branches
        return bool(branches) and any(label == "ELSE" for label, _s, _e in branches) and all(
            _guaranteed_range(node, assignments, name, branch_start, branch_end)
            for _label, branch_start, branch_end in branches
        )
    return False


def _guaranteed_range(parent, assignments, name, start, end):
    children = _children_in(parent, start, end)
    events = []
    for candidate, offset in assignments:
        if (
            candidate.lower() == name.lower()
            and start <= offset < end
            and not any(_inside(child, offset) for child in children)
        ):
            events.append((offset, "assignment"))
    for child in children:
        events.append((child.start_offset, child))
    events.sort(key=lambda item: item[0])

    for offset, event in events:
        if event == "assignment":
            return True
        if _guaranteed(event, assignments, name):
            return True
    return False


def check(unit, ctx):
    if unit.kind not in _CALLABLE_KINDS:
        return
    declarations = ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    outputs = declarations.output_members(unit)
    if not outputs:
        return

    assignments = [
        (match.group("name"), section.at(match.start("name")))
        for match in _ASSIGNMENT.finditer(section.text)
    ]
    assignments.extend(
        (match.group("name"), section.at(match.start("name")))
        for match in _OUTPUT_ARGUMENT.finditer(section.text)
    )
    if not assignments:
        return  # CTS0009 owns the never-assigned case.

    root = tree(unit)
    for member in outputs:
        name = member["name"]
        matching = [
            (candidate, offset)
            for candidate, offset in assignments
            if candidate.lower() == name.lower()
        ]
        if not matching:
            continue

        root_end = section.at(len(section.text))
        if _guaranteed_range(root, matching, name, root.start_offset, root_end):
            continue

        yield finding_in(
            message=f"output '{name}' is not assigned on all control-flow paths",
            unit=unit,
            offset=matching[0][1],
            end_offset=matching[0][1] + len(matching[0][0]),
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0019",
    title="Output not assigned on all paths",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="Outputs assigned only on some conditional paths.",
    topic="Interfaces",
    check=check,
)
