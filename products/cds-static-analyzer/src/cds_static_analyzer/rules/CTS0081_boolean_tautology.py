"""CTS0081 - tautological and contradictory boolean expressions."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body


_OPERAND = r"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?"
_SAME_NEGATED = re.compile(
    rf"(?P<left>{_OPERAND})\s+(?P<operator>AND|OR)\s+NOT\s+(?P<right>{_OPERAND})",
    re.IGNORECASE,
)
_CONSTANT = re.compile(
    rf"(?P<left>{_OPERAND}|TRUE|FALSE)\s+(?P<operator>AND|OR)\s+"
    rf"(?P<right>{_OPERAND}|TRUE|FALSE)",
    re.IGNORECASE,
)


def _normalise(value):
    return re.sub(r"\s+", "", value).casefold()


def _constant_result(left, operator, right):
    left_value = left.upper() if left.upper() in {"TRUE", "FALSE"} else None
    right_value = right.upper() if right.upper() in {"TRUE", "FALSE"} else None
    if left_value is None and right_value is None:
        return None
    if operator.upper() == "AND":
        if left_value == "FALSE" or right_value == "FALSE":
            return False
        if left_value == "TRUE" and right_value is not None:
            return right_value == "TRUE"
        if right_value == "TRUE" and left_value is not None:
            return left_value == "TRUE"
    if operator.upper() == "OR":
        if left_value == "TRUE" or right_value == "TRUE":
            return True
        if left_value == "FALSE" and right_value is not None:
            return right_value == "TRUE"
        if right_value == "FALSE" and left_value is not None:
            return left_value == "TRUE"
    return None


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    reported = set()
    for match in _SAME_NEGATED.finditer(section.text):
        if _normalise(match.group("left")) != _normalise(match.group("right")):
            continue
        operator = match.group("operator").upper()
        result = operator == "OR"
        expression = match.group(0)
        key = (match.start(), match.end())
        reported.add(key)
        yield finding_in(
            message=f"boolean expression '{expression}' is always {str(result).lower()}",
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )

    for match in _CONSTANT.finditer(section.text):
        if (match.start(), match.end()) in reported:
            continue
        result = _constant_result(
            match.group("left"), match.group("operator"), match.group("right")
        )
        if result is None:
            continue
        expression = match.group(0)
        yield finding_in(
            message=f"boolean expression '{expression}' is always {str(result).lower()}",
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0081",
    title="Tautological or contradictory boolean expression",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Boolean expressions that always evaluate to the same result should be simplified.",
    topic="Correctness",
    check=check,
)
