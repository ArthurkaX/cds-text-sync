"""CTS0015 - duplicate CASE labels make a branch unreachable."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


def _labels(raw):
    return [part.strip().upper() for part in re.split(r"\s*,\s*", raw) if part.strip()]


def _cases(node):
    if node.kind == "CASE":
        yield node
    for child in node.children:
        yield from _cases(child)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    for case in _cases(tree(unit)):
        seen = set()
        for label, absolute_start, _ in case.branches:
            for value in _labels(label):
                if value == "ELSE":
                    continue
                if value in seen:
                    local_start = absolute_start - section.base
                    yield finding_in(
                        message=f"duplicate CASE label {value!r} makes a branch unreachable",
                        unit=unit,
                        offset=section.at(local_start),
                        end_offset=section.at(local_start + len(label)),
                        anchor=value,
                        context=value,
                    )
                seen.add(value)


RULE = RuleSpec(
    id="CTS0015",
    title="Duplicate CASE label",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="CASE labels must be unique within each CASE statement.",
    topic="Correctness",
    check=check,
)
