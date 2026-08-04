"""CTS0024 - multiple writes to one output in the same control-flow path."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.blocks import Block, tree
from cds_text_sync.analyze.st.body import body

_ASSIGNMENT = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=" )
_OUTPUT_ARGUMENT = re.compile(r"=>\s*(?P<name>[A-Za-z_]\w*)", re.IGNORECASE)
_CALLABLE_KINDS = {"function", "method", "action", "property_get", "property_set"}


def _contains(node: Block, offset: int, end: int) -> bool:
    return node.start_offset <= offset < (node.end_offset or end)


def _branch_index(node: Block, offset: int) -> int | None:
    for index, (_label, start, end) in enumerate(node.branches):
        if start <= offset < end:
            return index
    return None


def _context(node: Block, offset: int, end: int):
    """Return a path-sensitive key for the block containing *offset*.

    IF/ELSIF/ELSE and CASE arms are separate contexts. This keeps intentional
    mutually-exclusive output assignments from looking like sequential writes.
    """
    key = [(id(node), _branch_index(node, offset))]
    for child in node.children:
        if _contains(child, offset, end):
            return tuple(key) + _context(child, offset, end)
    return tuple(key)


def _reads_output(text: str, match, name: str) -> bool:
    """Whether the assignment uses the same output while building its value."""
    statement_end = text.find(";", match.end())
    if statement_end < 0:
        statement_end = len(text)
    rhs = text[match.end() : statement_end]
    return re.search(rf"\b{re.escape(name)}\b", rhs, re.IGNORECASE) is not None


def check(unit, ctx):
    if unit.kind not in _CALLABLE_KINDS:
        return
    declarations = ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    outputs = {
        member.get("name", "").casefold(): member
        for member in declarations.output_members(unit)
        if member.get("name")
    }
    if not outputs:
        return

    writes = []
    for match in _ASSIGNMENT.finditer(section.text):
        name = match.group("name")
        if name.casefold() in outputs:
            writes.append(
                (name, section.at(match.start("name")), _reads_output(section.text, match, name))
            )
    for match in _OUTPUT_ARGUMENT.finditer(section.text):
        name = match.group("name")
        if name.casefold() in outputs:
            writes.append((name, section.at(match.start("name")), False))
    if not writes:
        return

    root = tree(unit)
    end = section.at(len(section.text))
    grouped = {}
    for name, offset, reads_output in writes:
        if reads_output:
            continue
        key = (name.casefold(), _context(root, offset, end))
        grouped.setdefault(key, []).append((name, offset))

    for (folded, _context_key), occurrences in grouped.items():
        if len(occurrences) < 2:
            continue
        name = occurrences[1][0]
        for _previous, offset in occurrences[1:]:
            yield finding_in(
                message=f"output '{name}' is written more than once in the same control-flow block",
                unit=unit,
                offset=offset,
                end_offset=offset + len(name),
                anchor=name,
                context=f"{name} : {outputs[folded].get('type', '')}",
            )


RULE = RuleSpec(
    id="CTS0024",
    title="Multiple output writes",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="Outputs written more than once along the same control-flow path.",
    topic="Interfaces",
    check=check,
)
