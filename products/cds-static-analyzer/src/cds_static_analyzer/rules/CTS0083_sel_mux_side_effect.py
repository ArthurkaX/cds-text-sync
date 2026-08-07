"""CTS0083 - SEL/MUX arguments must not hide stateful side effects."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.decl import all_members


_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(", re.IGNORECASE)
_SELECTOR = re.compile(r"\b(?:SEL|MUX)\s*\(", re.IGNORECASE)
_PURE_CALLS = {
    "ABS", "CONCAT", "FIND", "LEFT", "LEN", "LIMIT", "MAX", "MID",
    "MIN", "REPLACE", "RIGHT", "SEL", "MUX", "SIZEOF", "TO_STRING",
}


def _function_block_types(ctx):
    names = set()
    for unit in ctx.units:
        if unit.kind != K.FUNCTION_BLOCK:
            continue
        qualified = unit.qualified_name.casefold()
        names.add(qualified)
        names.add(qualified.rsplit(".", 1)[-1])
    return names


def _instances(unit, ctx):
    block_types = _function_block_types(ctx)
    return {
        member.get("name", "").casefold()
        for member in all_members(unit)
        if member.get("name")
        and (
            member.get("type", "").strip().casefold() in block_types
            or member.get("type", "").strip().casefold().rsplit(".", 1)[-1]
            in block_types
        )
    }


def _matching_parenthesis(text, opening):
    depth = 0
    for offset in range(opening, len(text)):
        if text[offset] == "(":
            depth += 1
        elif text[offset] == ")":
            depth -= 1
            if depth == 0:
                return offset
    return None


def _split_arguments(text):
    arguments = []
    start = 0
    depth = 0
    for offset, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append(text[start:offset])
            start = offset + 1
    arguments.append(text[start:])
    return arguments


def _may_have_side_effect(call_name, instances):
    upper = call_name.upper()
    if call_name.casefold() in instances:
        return True
    if upper in _PURE_CALLS or upper.startswith("TO_") or "_TO_" in upper:
        return False
    return True


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    instances = _instances(unit, ctx)
    text = section.text
    for selector in _SELECTOR.finditer(text):
        closing = _matching_parenthesis(text, selector.end() - 1)
        if closing is None:
            continue
        arguments = _split_arguments(text[selector.end() : closing])
        if len(arguments) < 3:
            continue

        side_effects = []
        for argument in arguments[1:]:
            for call in _CALL.finditer(argument):
                name = call.group("name")
                if _may_have_side_effect(name, instances):
                    side_effects.append(name)
        if not side_effects:
            continue

        expression = text[selector.start() : closing + 1]
        absolute = section.at(selector.start())
        calls = ", ".join(dict.fromkeys(side_effects))
        yield finding_in(
            message=(
                f"SEL/MUX evaluates argument call(s) with possible side effects "
                f"before selecting a value: {calls}"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(closing + 1),
            anchor=selector.group(0).strip(),
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0083",
    title="SEL/MUX argument may have side effects",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A SEL or MUX argument contains a call that may execute even when its value is not selected.",
    topic="Correctness",
    check=check,
)
