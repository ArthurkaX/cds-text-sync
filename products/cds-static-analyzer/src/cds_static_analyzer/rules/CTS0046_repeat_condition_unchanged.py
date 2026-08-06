"""CTS0046 - a REPEAT condition is not changed by its loop body."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_UNTIL = re.compile(r"\bUNTIL\b", re.IGNORECASE)
_END_REPEAT = re.compile(r"\bEND_REPEAT\b", re.IGNORECASE)
_IDENTIFIER = re.compile(r"(?<![\w.])(?P<name>[A-Za-z_]\w*)(?![\w.])")
_ASSIGNMENT = re.compile(
    r"(?<![\w.])(?P<name>[A-Za-z_]\w*)\s*:=", re.IGNORECASE
)
_TERMINAL = re.compile(r"\b(?:EXIT|RETURN)\b", re.IGNORECASE)
_KEYWORDS = {"AND", "OR", "XOR", "NOT", "MOD", "TRUE", "FALSE"}


def _walk(node):
    for child in node.children:
        yield child
        yield from _walk(child)


def _condition_names(text):
    return [
        match
        for match in _IDENTIFIER.finditer(text)
        if match.group("name").upper() not in _KEYWORDS
        and not text[match.end() :].lstrip().startswith("(")
    ]


def check(unit, ctx):
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    text = section.text

    for block in _walk(tree(unit)):
        if block.kind != "REPEAT" or block.end_offset is None:
            continue
        local_start = block.start_offset - section.base
        local_end = block.end_offset - section.base
        end_matches = list(_END_REPEAT.finditer(text, local_start, local_end))
        if not end_matches:
            continue
        end_start = end_matches[-1].start()
        until_matches = list(_UNTIL.finditer(text, local_start, end_start))
        if not until_matches:
            continue
        until = until_matches[-1]
        condition_start = until.end()
        condition = text[condition_start:end_start]
        names = _condition_names(condition)
        if not names:
            continue

        loop_body = text[local_start:until.start()]
        # A direct EXIT/RETURN is an alternate termination path. Determining
        # whether it is unconditional needs control-flow analysis, so leave
        # such loops for a future path-sensitive rule.
        if _TERMINAL.search(loop_body):
            continue
        assigned = {
            match.group("name").casefold()
            for match in _ASSIGNMENT.finditer(loop_body)
        }
        unchanged = [
            match for match in names if match.group("name").casefold() not in assigned
        ]
        if not unchanged:
            continue

        first = unchanged[0]
        variable_names = ", ".join(match.group("name") for match in unchanged)
        absolute = section.at(condition_start + first.start("name"))
        yield finding_in(
            message=(
                f"REPEAT UNTIL condition variable(s) {variable_names!r} are "
                "not assigned in the loop body; the loop may not terminate"
            ),
            unit=unit,
            offset=absolute,
            end_offset=absolute + len(first.group("name")),
            anchor=first.group("name"),
            context=condition.strip(),
        )


RULE = RuleSpec(
    id="CTS0046",
    title="REPEAT condition not changed",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A REPEAT loop condition is not changed by its body.",
    topic="Correctness",
    check=check,
)
