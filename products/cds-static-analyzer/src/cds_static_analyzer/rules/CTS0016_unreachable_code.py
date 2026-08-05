"""CTS0016 - statements immediately following unconditional control flow."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_TERMINAL = re.compile(r"\b(?:RETURN|EXIT|CONTINUE)\b\s*;", re.IGNORECASE)
_BOUNDARY = {
    "ELSE",
    "ELSIF",
    "END_IF",
    "END_CASE",
    "END_FOR",
    "END_WHILE",
    "END_REPEAT",
}
_WORD = re.compile(r"\b[A-Za-z_]\w*\b")


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    for terminal in _TERMINAL.finditer(section.text):
        next_word = _WORD.search(section.text, terminal.end())
        if not next_word or next_word.group().upper() in _BOUNDARY:
            continue
        word = next_word.group()
        yield finding_in(
            message=f"statement after {terminal.group().strip()} is unreachable",
            unit=unit,
            offset=section.at(next_word.start()),
            end_offset=section.at(next_word.end()),
            anchor=word,
            context=word,
        )


RULE = RuleSpec(
    id="CTS0016",
    title="Unreachable code after control flow exit",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Statements immediately following an unconditional control-flow exit.",
    topic="Correctness",
    check=check,
)
