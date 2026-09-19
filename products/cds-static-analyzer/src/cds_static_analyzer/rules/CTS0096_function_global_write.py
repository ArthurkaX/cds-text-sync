"""CTS0096 - a FUNCTION writes project-global state."""

from __future__ import annotations

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.global_access import global_access_index
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K


def check(unit, ctx):
    if unit.kind != K.FUNCTION:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    reported = set()
    for access in global_access_index(ctx).accesses_for(unit):
        if not access.write:
            continue
        target = access.target
        key = target.casefold()
        if key in reported:
            continue
        reported.add(key)
        yield finding_in(
            message=(
                f"FUNCTION writes global '{target}'; the side effect is hidden "
                "from the function's call contract"
            ),
            unit=unit,
            offset=access.offset,
            end_offset=access.end_offset + 2,
            anchor=f"{target} :=",
            context=f"{target} :=",
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
