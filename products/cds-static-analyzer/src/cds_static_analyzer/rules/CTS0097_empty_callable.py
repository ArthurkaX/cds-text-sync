"""CTS0097 - a callable POU has no executable implementation."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_HEADER = re.compile(
    r"\b(?:PROGRAM|FUNCTION_BLOCK|FUNCTION|METHOD|ACTION|PROPERTY)\s+"
    r"(?P<name>[A-Za-z_]\w*)",
    re.IGNORECASE,
)


def _header_offset(unit):
    match = _HEADER.search(unit.declaration or "")
    if match is None:
        return None
    for span in unit.source_spans:
        if span.role == "declaration":
            return span.start_offset + match.start("name")
    return match.start("name")


def check(unit, ctx):
    if unit.kind not in K.CALLABLE or unit.implementation is None:
        return
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if re.sub(r"[;\s]", "", section.text):
        return

    offset = _header_offset(unit)
    yield finding_in(
        message=(
            f"{unit.kind.replace('_', ' ')} '{unit.qualified_name}' has an "
            "empty implementation"
        ),
        unit=unit,
        offset=offset,
        end_offset=offset + len(unit.qualified_name.rsplit(".", 1)[-1])
        if offset is not None
        else None,
        anchor=unit.qualified_name,
        context=unit.kind,
    )


RULE = RuleSpec(
    id="CTS0097",
    title="Empty callable implementation",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A callable POU contains no executable implementation.",
    topic="Dead code",
    check=check,
)
