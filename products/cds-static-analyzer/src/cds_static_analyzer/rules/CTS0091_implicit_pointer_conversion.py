"""CTS0091 - incompatible pointer assignment without an explicit conversion."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.pointers import pointer_members


_ASSIGNMENT = re.compile(
    r"\b(?P<left>[A-Za-z_]\w*)\s*:=\s*(?P<right>[A-Za-z_]\w*)\b"
)


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    pointers = pointer_members(unit, ctx)

    for match in _ASSIGNMENT.finditer(section.text):
        left = pointers.get(match.group("left").casefold())
        right = pointers.get(match.group("right").casefold())
        if left is None or right is None or left[1] == right[1]:
            continue
        # A byte pointer is commonly used as an explicitly generic storage
        # view for buffers. Keep that escape hatch quiet; typed-to-typed
        # conversions remain actionable.
        if "byte" in {left[1], right[1]}:
            continue
        yield finding_in(
            message=(
                f"pointer '{right[0]}' to {right[1]} is assigned to pointer "
                f"'{left[0]}' to {left[1]} without an explicit conversion"
            ),
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=match.group(0),
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0091",
    title="Implicit pointer conversion",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Incompatible pointer bases are assigned without an explicit conversion.",
    topic="Correctness",
    check=check,
)
