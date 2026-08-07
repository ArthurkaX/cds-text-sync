"""CTS0077 - integer division assigned to a floating-point result."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_ASSIGNMENT = re.compile(r"\b(?P<target>[A-Za-z_]\w*)\s*:=\s*(?P<expression>[^;]+)")
_DIVISION = re.compile(
    r"(?<![A-Za-z0-9_])(?P<left>[A-Za-z_]\w*|[+-]?\d+)\s*/\s*"
    r"(?P<right>[A-Za-z_]\w*|[+-]?\d+)(?![A-Za-z0-9_])",
)
_TYPED_INTEGER = re.compile(
    r"(?P<type>SINT|USINT|BYTE|INT|UINT|WORD|DINT|UDINT|DWORD|LINT|ULINT|LWORD)#",
    re.IGNORECASE,
)
_INTEGER_TYPES = frozenset(
    {"SINT", "USINT", "BYTE", "INT", "UINT", "WORD", "DINT", "UDINT", "DWORD", "LINT", "ULINT", "LWORD"}
)
_FLOAT_TYPES = frozenset({"REAL", "LREAL"})
_FUNCTION_HEADER = re.compile(
    r"^\s*FUNCTION\s+(?P<name>[A-Za-z_]\w*)\s*:\s*(?P<type>[A-Za-z_]\w*)",
    re.IGNORECASE,
)


def _base(type_name):
    info = classify_type(type_name or "")
    if info.get("kind") != "scalar":
        return None
    return str(info.get("base", "")).upper()


def _member_types(unit):
    result = {}
    for member in decl.all_members(unit):
        base = _base(member.get("type", ""))
        if base:
            result[member.get("name", "").casefold()] = base
    header = _FUNCTION_HEADER.match(unit.declaration or "")
    if header:
        result[header.group("name").casefold()] = _base(header.group("type"))
    return result


def _operand_type(operand, types):
    typed = _TYPED_INTEGER.fullmatch(operand.strip())
    if typed:
        return typed.group("type").upper()
    if re.fullmatch(r"[+-]?\d+", operand.strip()):
        return "INT"
    return types.get(operand.strip().casefold())


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    types = _member_types(unit)
    if not types:
        return

    for assignment in _ASSIGNMENT.finditer(section.text):
        target_type = types.get(assignment.group("target").casefold())
        if target_type not in _FLOAT_TYPES:
            continue
        for division in _DIVISION.finditer(assignment.group("expression")):
            left_type = _operand_type(division.group("left"), types)
            right_type = _operand_type(division.group("right"), types)
            if left_type not in _INTEGER_TYPES or right_type not in _INTEGER_TYPES:
                continue
            start = assignment.start("expression") + division.start()
            end = assignment.start("expression") + division.end()
            expression = section.text[start:end]
            yield finding_in(
                message=(
                    f"integer division '{expression}' loses its fractional part "
                    f"before assignment to {target_type}; convert an operand to REAL"
                ),
                unit=unit,
                offset=section.at(start),
                end_offset=section.at(end),
                anchor=expression,
                context=expression,
            )


RULE = RuleSpec(
    id="CTS0077",
    title="Integer division assigned to floating point",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Integer division must not silently discard the fractional part before a REAL assignment.",
    topic="Correctness",
    check=check,
)
