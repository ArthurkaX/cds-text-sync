"""CTS0062 - arithmetic must not mix TIME and numeric values implicitly."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_TIME_LITERAL = r"(?:T|TIME)#[+-]?(?:\d+(?:\.\d+)?(?:ms|us|ns|d|h|m|s))+"
_NUMBER_LITERAL = (
    r"(?:[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"(?:SINT|USINT|BYTE|INT|UINT|WORD|DINT|UDINT|DWORD|LINT|ULINT|LWORD|"
    r"REAL|LREAL)#[-+]?\d+(?:\.\d*)?)"
)
_IDENTIFIER = r"[A-Za-z_]\w*"
_OPERAND = rf"(?:{_TIME_LITERAL}|{_NUMBER_LITERAL}|{_IDENTIFIER})"
_MIXED_OPERATION = re.compile(
    rf"(?<![A-Za-z0-9_])(?P<left>{_OPERAND})\s*(?P<operator>[+*/-])\s*"
    rf"(?P<right>{_OPERAND})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_NUMERIC = frozenset(
    {
        "SINT", "USINT", "BYTE", "INT", "UINT", "WORD", "DINT", "UDINT",
        "DWORD", "LINT", "ULINT", "LWORD", "REAL", "LREAL",
    }
)


def _member_types(unit):
    result = {}
    for member in decl.all_members(unit):
        info = classify_type(member.get("type", ""))
        if info.get("kind") != "scalar":
            continue
        result[member.get("name", "").casefold()] = str(info.get("base", "")).upper()
    return result


def _operand_kind(operand, types):
    if re.fullmatch(_TIME_LITERAL, operand, re.IGNORECASE):
        return "time"
    if re.fullmatch(_NUMBER_LITERAL, operand, re.IGNORECASE):
        return "numeric"
    base = types.get(operand.casefold())
    if base == "TIME":
        return "time"
    if base in _NUMERIC:
        return "numeric"
    return None


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    types = _member_types(unit)
    if not types and not re.search(_TIME_LITERAL, section.text, re.IGNORECASE):
        return

    for match in _MIXED_OPERATION.finditer(section.text):
        left_kind = _operand_kind(match.group("left"), types)
        right_kind = _operand_kind(match.group("right"), types)
        if {left_kind, right_kind} != {"time", "numeric"}:
            continue
        expression = match.group(0)
        yield finding_in(
            message=(
                f"arithmetic mixes TIME and numeric value in '{expression}'; "
                "use an explicit TIME_TO_/TO_TIME conversion"
            ),
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0062",
    title="Implicit TIME and numeric arithmetic",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="TIME arithmetic with numeric values must use an explicit conversion.",
    topic="Correctness",
    check=check,
)
