"""CTS0096 - a FUNCTION writes project-global state."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.function_blocks import global_members


_WRITE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:\.\s*(?P<field>[A-Za-z_]\w*))?\s*:="
)


def check(unit, ctx):
    if unit.kind != K.FUNCTION:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    globals_by_name = global_members(ctx)
    if not globals_by_name:
        return
    local_names = {
        member.get("name", "").casefold()
        for member in decl.all_members(unit)
        if member.get("name")
    }
    reported = set()
    for match in _WRITE.finditer(section.text):
        name = match.group("name")
        key = name.casefold()
        if key in local_names or key not in globals_by_name or key in reported:
            continue
        reported.add(key)
        target = f"{name}.{match.group('field')}" if match.group("field") else name
        yield finding_in(
            message=(
                f"FUNCTION writes global '{target}'; the side effect is hidden "
                "from the function's call contract"
            ),
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=match.group(0).strip(),
            context=match.group(0).strip(),
        )


RULE = RuleSpec(
    id="CTS0096",
    title="Function writes global state",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds=(K.FUNCTION,),
    summary="A FUNCTION modifies project-global state instead of remaining side-effect free.",
    topic="Correctness",
    check=check,
)
