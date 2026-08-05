"""CTS0038 - FOR loop with an invalid literal step."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_HEADER = re.compile(
    r"\bFOR\b(?P<header>.*?)(?P<do>\bDO\b)", re.IGNORECASE | re.DOTALL
)
_FORM = re.compile(
    r"^\s*(?P<counter>[^:=]+?)\s*:=\s*"
    r"(?P<start>[+-]?\d+)\s+TO\s+(?P<end>[+-]?\d+)"
    r"(?:\s+BY\s+(?P<step>[+-]?\d+))?\s*$",
    re.IGNORECASE,
)


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def check(unit, ctx):
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    text = section.text

    for block in _walk(tree(unit)):
        if block.kind != "FOR":
            continue
        local_start = block.start_offset - section.base
        local_end = block.end_offset - section.base if block.end_offset is not None else len(text)
        header = _HEADER.search(text, local_start, local_end)
        if not header:
            continue
        parsed = _FORM.match(header.group("header"))
        if not parsed or parsed.group("step") is None:
            continue
        start = int(parsed.group("start"))
        end = int(parsed.group("end"))
        step = int(parsed.group("step"))
        step_start = header.start("header") + parsed.start("step")
        absolute = section.at(step_start)
        if step == 0:
            yield finding_in(
                message="FOR loop has a zero step and cannot make progress",
                unit=unit,
                offset=absolute,
                end_offset=absolute + len(parsed.group("step")),
                anchor=parsed.group("step"),
                context=header.group(0).strip(),
            )
        elif (start < end and step < 0) or (start > end and step > 0):
            yield finding_in(
                message="FOR loop step moves away from its literal boundary",
                unit=unit,
                offset=absolute,
                end_offset=absolute + len(parsed.group("step")),
                anchor=parsed.group("step"),
                context=header.group(0).strip(),
            )


RULE = RuleSpec(
    id="CTS0038",
    title="Invalid FOR loop step",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A FOR loop has a zero or directionally invalid literal step.",
    topic="Correctness",
    check=check,
)
