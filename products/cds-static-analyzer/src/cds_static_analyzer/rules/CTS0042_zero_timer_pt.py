"""CTS0042 - timer called with a zero preset time."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body


_CALL = re.compile(
    r"\b(?P<timer>[A-Za-z_]\w*)\s*\([^;]*?\bPT\s*:=\s*"
    r"(?P<pt>T#0(?:ms|s|m|h|d))\b[^;]*?\)",
    re.IGNORECASE | re.DOTALL,
)
_KNOWN_TYPES = re.compile(r"\b(?:TON|TOF|TP)\b", re.IGNORECASE)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    # Keep the rule local and conservative: require a timer type somewhere in
    # the unit declaration, then inspect calls carrying an explicit zero PT.
    if not _KNOWN_TYPES.search(unit.declaration or ""):
        return
    for match in _CALL.finditer(section.text):
        absolute = section.at(match.start("pt"))
        yield finding_in(
            message="timer preset time PT is zero",
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end("pt")),
            anchor=match.group("pt"),
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0042",
    title="Zero timer preset time",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="TON, TOF or TP is called with an explicit zero PT value.",
    topic="Correctness",
    check=check,
)
