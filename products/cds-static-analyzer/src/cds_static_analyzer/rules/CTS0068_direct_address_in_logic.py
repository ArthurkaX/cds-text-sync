"""CTS0068 - direct hardware addresses used in executable logic."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_DIRECT_ADDRESS = re.compile(
    r"(?<![A-Za-z0-9_])%(?:I|Q|M)(?:X|B|W|D|L)(?:\d+(?:\.\d+)?)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    for match in _DIRECT_ADDRESS.finditer(section.text):
        address = match.group(0)
        offset = section.at(match.start())
        yield finding_in(
            message=f"direct hardware address '{address}' is used in executable logic",
            unit=unit,
            offset=offset,
            end_offset=offset + len(address),
            anchor=address,
            context=address,
        )


RULE = RuleSpec(
    id="CTS0068",
    title="Direct hardware address in logic",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Use symbolic variables for hardware addresses instead of direct addresses in logic.",
    topic="Code quality",
    check=check,
)
