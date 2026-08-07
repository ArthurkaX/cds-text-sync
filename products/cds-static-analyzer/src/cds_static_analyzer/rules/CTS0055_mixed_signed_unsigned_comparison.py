"""CTS0055 - signed and unsigned operands are compared implicitly."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_COMPARISON = re.compile(
    r"\b(?P<left>[A-Za-z_]\w*)\s*(?P<op><>|<=|>=|=|<|>)\s*"
    r"(?P<right>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)

_SIGNED = frozenset({"SINT", "INT", "DINT", "LINT"})
_UNSIGNED = frozenset({"USINT", "BYTE", "UINT", "WORD", "UDINT", "DWORD", "ULINT", "LWORD"})


def _base_type(type_name):
    info = classify_type(type_name)
    if info.get("kind") != "scalar":
        return None
    return str(info.get("base", "")).upper()


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    section = body(unit)
    if not section:
        return

    types = {}
    for member in decl.all_members(unit):
        name = member.get("name", "")
        base = _base_type(member.get("type", ""))
        if name and base:
            types[name.casefold()] = base

    for match in _COMPARISON.finditer(section.text):
        left_name = match.group("left")
        right_name = match.group("right")
        left_type = types.get(left_name.casefold())
        right_type = types.get(right_name.casefold())
        if not left_type or not right_type:
            continue
        left_signed = left_type in _SIGNED
        right_signed = right_type in _SIGNED
        if left_signed == right_signed:
            continue

        expression = match.group(0)
        absolute = section.at(match.start())
        yield finding_in(
            message=(
                f"comparison mixes signed {left_type} and unsigned {right_type} "
                "values; make the conversion explicit"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0055",
    title="Mixed signed and unsigned comparison",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Comparisons must not mix signed and unsigned integer operands implicitly.",
    topic="Correctness",
    check=check,
)
