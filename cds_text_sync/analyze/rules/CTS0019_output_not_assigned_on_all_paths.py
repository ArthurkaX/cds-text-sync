"""CTS0019 - outputs assigned only on some control-flow paths."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.blocks import tree
from cds_text_sync.analyze.st.body import body

_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=", re.IGNORECASE)


def _inside(node, offset):
    return node.start_offset <= offset < (node.end_offset or offset + 1)


def _has_assignment_in_range(assignments, start, end, name):
    return any(
        start <= offset < end and candidate.lower() == name.lower()
        for candidate, offset in assignments
    )


def _all_branches_assign(node, assignments, name):
    branches = node.branches
    return bool(branches) and len(branches) >= 2 and all(
        _has_assignment_in_range(assignments, start, end, name)
        for _label, start, end in branches
    )


def check(unit, ctx):
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
    if not assignments:
        return  # CTS0009 owns the never-assigned case.

    root = tree(unit)
    if_nodes = [node for node in root.children if node.kind == "IF"]
    for member in outputs:
        name = member["name"]
        matching = [
            (candidate, offset)
            for candidate, offset in assignments
            if candidate.lower() == name.lower()
        ]
        if not matching:
            continue

        if any(
            not any(_inside(node, offset) for node in if_nodes)
            for _candidate, offset in matching
        ):
            continue
        if any(_all_branches_assign(node, matching, name) for node in if_nodes):
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
