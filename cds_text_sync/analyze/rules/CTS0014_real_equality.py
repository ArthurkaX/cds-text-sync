"""CTS0014 - floating-point equality comparisons are unstable."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body
from cds_text_sync.analyze.st.decl import all_members


_EQUALITY = re.compile(r"(?<![<>=:])=(?!=)")
_IDENT = re.compile(r"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*")
_FLOAT_TYPES = {"REAL", "LREAL"}


def _real_names(unit):
    return {
        member["name"].upper()
        for member in all_members(unit)
        if member.get("type", "").strip().strip("'\"").rstrip(";").upper()
        in _FLOAT_TYPES
    }


def _operand(text, start, direction):
    """Return the nearest simple operand ending/starting at *start*."""
    if direction < 0:
        prefix = text[:start].rstrip()
        matches = list(_IDENT.finditer(prefix))
        match = matches[-1] if matches else None
        return match.group().replace(" ", "").upper() if match else None
    suffix = text[start:].lstrip()
    match = _IDENT.match(suffix)
    return match.group().replace(" ", "").upper() if match else None


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.DECLARATIONS)
    section = body(unit)
    if not section:
        return
    real_names = _real_names(unit)
    for match in _EQUALITY.finditer(section.text):
        left = _operand(section.text, match.start(), -1)
        right = _operand(section.text, match.end(), 1)
        if left not in real_names and right not in real_names:
            continue
        yield finding_in(
            message="floating-point equality should use a tolerance comparison",
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor="=",
            context=f"{left or '?'} = {right or '?'}",
        )


RULE = RuleSpec(
    id="CTS0014",
    title="Floating-point equality",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="REAL and LREAL values should not be compared for exact equality.",
    topic="Correctness",
    check=check,
)
