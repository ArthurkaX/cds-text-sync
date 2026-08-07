"""CTS0080 - a provably oversized CONCAT result."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blanking import blank_noise
from cds_static_analyzer.st.body import body


_STRING_TYPE = re.compile(r"^(?P<wide>W)?STRING\s*\(\s*(?P<size>\d+)\s*\)$", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"\b(?P<target>[A-Za-z_]\w*)\s*:=\s*(?P<expression>[^;]+)"
)
_CONCAT = re.compile(r"\bCONCAT\s*\(", re.IGNORECASE)
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_LITERAL = re.compile(r"(?:W)?(?:'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")")


def _capacity(type_name):
    match = _STRING_TYPE.fullmatch((type_name or "").strip())
    return int(match.group("size")) if match else None


def _members(unit):
    return {
        member.get("name", "").casefold(): _capacity(member.get("type", ""))
        for member in decl.all_members(unit)
        if _capacity(member.get("type", "")) is not None
    }


def _literal_length(literal):
    quote_index = 1 if literal[:1].upper() == "W" else 0
    quote = literal[quote_index : quote_index + 1]
    value = literal[quote_index + 1 : -1]
    return len(value.replace(quote + quote, quote)) if quote else None


def _split_args(text):
    args = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
    args.append(text[start:].strip())
    return args


def _matching_close(text, opening):
    depth = 1
    quote = None
    index = opening + 1
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _value_length(expression, capacities):
    literal = _LITERAL.fullmatch(expression)
    if literal:
        return _literal_length(expression)
    identifier = _IDENTIFIER.fullmatch(expression)
    if identifier:
        return capacities.get(identifier.group(0).casefold())
    call = _CONCAT.fullmatch(expression[: expression.find("(") + 1]) if "(" in expression else None
    if call:
        opening = expression.find("(")
        closing = _matching_close(expression, opening)
        if closing != len(expression) - 1:
            return None
        args = _split_args(expression[opening + 1 : closing])
        if len(args) != 2:
            return None
        lengths = [_value_length(arg, capacities) for arg in args]
        if any(length is None for length in lengths):
            return None
        return sum(lengths)
    return None


def _concat_call(expression, capacities):
    match = _CONCAT.match(expression.strip())
    if not match:
        return None
    opening = match.end() - 1
    closing = _matching_close(expression, opening)
    if closing is None or expression[closing + 1 :].strip():
        return None
    length = _value_length(expression.strip(), capacities)
    return length, opening, closing


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    capacities = _members(unit)
    if not capacities:
        return
    source = blank_noise(section.raw)
    for assignment in _ASSIGNMENT.finditer(source):
        capacity = capacities.get(assignment.group("target").casefold())
        if capacity is None:
            continue
        expression = assignment.group("expression").strip()
        result = _concat_call(expression, capacities)
        if result is None:
            continue
        length, _opening, closing = result
        if length is None or length <= capacity:
            continue
        expression_start = assignment.start("expression") + (
            len(assignment.group("expression")) - len(assignment.group("expression").lstrip())
        )
        expression_end = assignment.end("expression") - (
            len(assignment.group("expression")) - len(assignment.group("expression").rstrip())
        )
        call = source[expression_start:expression_end]
        yield finding_in(
            message=(
                f"CONCAT result can contain {length} characters but "
                f"{assignment.group('target')} is limited to STRING({capacity})"
            ),
            unit=unit,
            offset=section.at(expression_start),
            end_offset=section.at(expression_end),
            anchor=call,
            context=call,
        )


RULE = RuleSpec(
    id="CTS0080",
    title="CONCAT result exceeds string capacity",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Provably oversized CONCAT results must not be assigned to a smaller STRING.",
    topic="Correctness",
    check=check,
)
