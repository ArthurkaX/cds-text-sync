"""CTS0036 - duplicate condition in one IF/ELSIF chain."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_HEADER = re.compile(r"^(?:IF|ELSIF)\s+(?P<condition>.+?)(?:\s+THEN)?$", re.IGNORECASE)


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def check(unit, ctx):
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    for block in _walk(tree(unit)):
        if block.kind != "IF":
            continue
        seen = {}
        for label, absolute_start, _absolute_end in block.branches:
            match = _HEADER.match(label.strip())
            if not match:
                continue
            condition = match.group("condition").strip()
            key = re.sub(r"\s+", " ", condition).upper()
            if key in seen:
                start = section.at(absolute_start - section.base)
                # The branch start points at IF/ELSIF. Locate the condition
                # within that header so the diagnostic highlights useful text.
                local_header = absolute_start - section.base
                condition_start = section.text.find(condition, local_header)
                if condition_start < local_header:
                    condition_start = local_header
                start = section.at(condition_start)
                yield finding_in(
                    message="IF/ELSIF chain repeats a condition; this branch is unreachable",
                    unit=unit,
                    offset=start,
                    end_offset=start + len(condition),
                    anchor=condition,
                    context=label.strip(),
                )
            else:
                seen[key] = absolute_start


RULE = RuleSpec(
    id="CTS0036",
    title="Duplicate IF condition",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A condition is repeated in the same IF/ELSIF chain.",
    topic="Correctness",
    check=check,
)
