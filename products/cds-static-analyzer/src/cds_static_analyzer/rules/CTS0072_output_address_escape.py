"""CTS0072 - addresses of VAR_OUTPUT values are exposed through ADR()."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body

_ADR = re.compile(
    r"\bADR\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)", re.IGNORECASE
)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    output_names = {
        member.get("name", "").casefold()
        for member in decl.output_members(unit)
        if member.get("name")
    }
    section = body(unit)
    if not output_names or not section:
        return

    for match in _ADR.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in output_names:
            continue
        offset = section.at(match.start())
        yield finding_in(
            message=(
                f"address of VAR_OUTPUT '{name}' is exposed through ADR(); "
                "avoid aliases that can outlive this POU call"
            ),
            unit=unit,
            offset=offset,
            end_offset=section.at(match.end()),
            anchor=f"ADR({name})",
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0072",
    title="Escaping address of VAR_OUTPUT",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Addresses of VAR_OUTPUT values should not be exposed through ADR().",
    topic="Interfaces",
    check=check,
)
