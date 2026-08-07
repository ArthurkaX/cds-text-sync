"""CTS0095 - hardware AT mapping on a local POU variable."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import declaration


_VAR_OPEN = re.compile(
    r"^\s*(?P<scope>VAR(?:_(?:INPUT|OUTPUT|IN_OUT|TEMP|STAT))?)\b",
    re.IGNORECASE,
)
_AT_DECL = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s+AT\s+"
    r"%(?:I|Q|M)(?:X|B|W|D|L)\d+(?:\.\d+)?\b",
    re.IGNORECASE,
)

_LOCAL_SCOPES = {"VAR", "VAR_TEMP", "VAR_STAT"}


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    section = declaration(unit)
    if not section:
        return

    scope = None
    for _line, offset, line in section.lines():
        stripped = line.strip()
        if re.match(r"^END_VAR\b", stripped, re.IGNORECASE):
            scope = None
            continue
        opener = _VAR_OPEN.match(line)
        if opener:
            scope = opener.group("scope").upper()
            continue
        if scope not in _LOCAL_SCOPES:
            continue
        for match in _AT_DECL.finditer(line):
            name = match.group("name")
            absolute = offset + match.start("name")
            yield finding_in(
                message=(
                    f"local variable '{name}' uses an AT hardware mapping; "
                    "keep hardware addresses in a global I/O map"
                ),
                unit=unit,
                offset=absolute,
                end_offset=absolute + len(name),
                anchor=name,
                context=match.group(0),
            )


RULE = RuleSpec(
    id="CTS0095",
    title="Local variable uses AT hardware mapping",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="Local POU variables should not own direct hardware mappings.",
    topic="Code quality",
    check=check,
)
