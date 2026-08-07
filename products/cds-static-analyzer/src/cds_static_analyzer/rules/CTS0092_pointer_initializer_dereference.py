"""CTS0092 - pointer dereference in a declaration initializer."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.pointers import pointer_members


_DEREFERENCE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\^")


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = declaration(unit)
    if not section:
        return
    pointers = pointer_members(unit, ctx)
    if not pointers:
        return

    for match in _DEREFERENCE.finditer(section.text):
        pointer = pointers.get(match.group("name").casefold())
        if pointer is None:
            continue
        statement_start = section.text.rfind(";", 0, match.start()) + 1
        statement_end = section.text.find(";", match.end())
        if statement_end < 0:
            statement_end = len(section.text)
        statement = section.text[statement_start:statement_end]
        assignment = statement.find(":=")
        if assignment < 0 or match.start() < statement_start + assignment + 2:
            continue
        yield finding_in(
            message=(
                f"pointer '{pointer[0]}' is dereferenced in a declaration "
                "initializer before the POU body can validate it"
            ),
            unit=unit,
            offset=section.at(match.start("name")),
            end_offset=section.at(match.end()),
            anchor=match.group(0).strip(),
            context=statement.strip(),
        )


RULE = RuleSpec(
    id="CTS0092",
    title="Pointer dereference in declaration initializer",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A pointer is dereferenced before the POU body can establish a guard.",
    topic="Correctness",
    check=check,
)
