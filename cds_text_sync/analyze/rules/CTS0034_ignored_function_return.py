"""CTS0034 - function return value is ignored."""

from __future__ import annotations

import re

from cds_text_sync.analyze.st import kinds as K
from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body

_CALL = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*\(.*\)\s*$", re.DOTALL)


def _function_names(ctx):
    names = set()
    for unit in ctx.units:
        if unit.kind != K.FUNCTION:
            continue
        qualified = unit.qualified_name.casefold()
        names.add(qualified)
        names.add(qualified.rsplit(".", 1)[-1])
    return names


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    functions = _function_names(ctx)
    if not functions or not unit.implementation:
        return

    section = body(unit)
    for offset, statement in section.statements():
        match = _CALL.fullmatch(statement)
        if match is None or match.group("name").casefold() not in functions:
            continue
        name = match.group("name")
        start = offset + statement.find(name)
        yield finding_in(
            message=(
                f"return value of function '{name}' is ignored; verify that "
                "the call is intentional"
            ),
            unit=unit,
            offset=start,
            end_offset=start + len(name),
            anchor=name,
            context=statement,
        )


RULE = RuleSpec(
    id="CTS0034",
    title="Ignored function return value",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Standalone calls to project functions whose return values are ignored.",
    topic="Correctness",
    check=check,
)
