"""CTS0030 - a FOR loop counter is modified inside the loop."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import Block, tree
from cds_static_analyzer.st.body import body


_FOR_HEADER = re.compile(
    r"\bFOR\s+(?P<name>[A-Za-z_]\w*)\s*:=.*?\bDO\b",
    re.IGNORECASE | re.DOTALL,
)


def _inside_call(text, offset):
    """Return whether *offset* is inside a parenthesised call argument."""
    boundary = max(text.rfind(";", 0, offset), text.rfind("\n", 0, offset))
    fragment = text[boundary + 1 : offset]
    return fragment.count("(") > fragment.count(")")


def _for_counter(block: Block, section):
    start = block.start_offset - section.base
    end = block.end_offset - section.base if block.end_offset is not None else len(section.text)
    match = _FOR_HEADER.match(section.text, start, end)
    return match.group("name") if match else None


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    root = tree(unit)
    for block in _for_blocks(root):
        name = _for_counter(block, section)
        if not name:
            continue
        start = block.start_offset - section.base
        header = _FOR_HEADER.match(section.text, start)
        if not header:
            continue
        body_start = header.end()
        body_end = block.end_offset - section.base if block.end_offset is not None else len(section.text)
        assignment = re.compile(
            r"(?<![.\w])" + re.escape(name) + r"\s*:=", re.IGNORECASE
        )
        for match in assignment.finditer(section.text, body_start, body_end):
            if _inside_call(section.text, match.start()):
                continue
            yield finding_in(
                message=f"FOR loop control variable '{name}' is modified inside the loop",
                unit=unit,
                offset=section.at(match.start()),
                end_offset=section.at(match.end()),
                anchor=name,
                context=f"{name} :=",
            )


def _for_blocks(node):
    for child in node.children:
        if child.kind == "FOR":
            yield child
        yield from _for_blocks(child)


RULE = RuleSpec(
    id="CTS0030",
    title="Modifying a FOR loop control variable inside the loop",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A FOR loop control variable is assigned from inside the loop body.",
    topic="Correctness",
    check=check,
)
