"""CTS0017 - literal conditions used as temporary control-flow stubs."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body

_CONDITION = re.compile(
    r"\b(?P<keyword>IF|ELSIF|WHILE)\s+(?P<value>TRUE|FALSE)\s+"
    r"(?P<delimiter>THEN|DO)\b",
    re.IGNORECASE,
)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    for match in _CONDITION.finditer(section.text):
        value = match.group("value").upper()
        yield finding_in(
            message=f"constant condition {value} looks like a temporary stub",
            unit=unit,
            offset=section.at(match.start("value")),
            end_offset=section.at(match.end("value")),
            anchor=value,
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0017",
    title="Constant control-flow condition",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Literal TRUE/FALSE conditions that commonly mark temporary stubs.",
    topic="Code quality",
    check=check,
)
