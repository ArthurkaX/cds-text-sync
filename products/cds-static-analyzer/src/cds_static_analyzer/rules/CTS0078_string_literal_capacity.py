"""CTS0078 - string literal exceeds an explicitly declared STRING capacity."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blanking import blank_noise
from cds_static_analyzer.st.body import body, declaration


_STRING_TYPE = re.compile(r"^(?P<wide>W)?STRING\s*\(\s*(?P<size>\d+)\s*\)$", re.IGNORECASE)
_LITERAL = r"(?:W)?(?:'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")"
_ASSIGNMENT = re.compile(
    rf"\b(?P<target>[A-Za-z_]\w*)\s*:=\s*(?P<literal>{_LITERAL})"
)


def _capacity(type_name):
    match = _STRING_TYPE.fullmatch((type_name or "").strip())
    return int(match.group("size")) if match else None


def _literal_length(literal):
    quote_index = 1 if literal[:1].upper() == "W" else 0
    quote = literal[quote_index : quote_index + 1]
    value = literal[quote_index + 1 : -1]
    if quote:
        value = value.replace(quote + quote, quote)
    return len(value)


def _string_members(unit):
    return {
        member.get("name", "").casefold(): _capacity(member.get("type", ""))
        for member in decl.all_members(unit)
        if _capacity(member.get("type", "")) is not None
    }


def _check_declaration_initializers(unit, capacities):
    section = declaration(unit)
    if not section:
        return
    source = blank_noise(section.raw)
    for member in decl.all_members(unit):
        capacity = capacities.get(member.get("name", "").casefold())
        initial = member.get("initial", "").strip()
        if capacity is None or not re.fullmatch(_LITERAL, initial) or _literal_length(initial) <= capacity:
            continue
        match = re.search(
            rf"\b{re.escape(member['name'])}\b\s*:\s*[^;]*?:=\s*{re.escape(initial)}",
            source,
            re.IGNORECASE,
        )
        if not match:
            continue
        literal_start = match.end() - len(initial)
        yield finding_in(
            message=(
                f"string literal has {_literal_length(initial)} characters but "
                f"{member['name']} is limited to STRING({capacity})"
            ),
            unit=unit,
            offset=section.at(literal_start),
            end_offset=section.at(match.end()),
            anchor=initial,
            context=initial,
        )


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    capacities = _string_members(unit)
    if not capacities:
        return
    yield from _check_declaration_initializers(unit, capacities)
    section = body(unit)
    if not section:
        return
    source = blank_noise(section.raw)
    for match in _ASSIGNMENT.finditer(source):
        capacity = capacities.get(match.group("target").casefold())
        literal = match.group("literal")
        if capacity is None or _literal_length(literal) <= capacity:
            continue
        yield finding_in(
            message=(
                f"string literal has {_literal_length(literal)} characters but "
                f"{match.group('target')} is limited to STRING({capacity})"
            ),
            unit=unit,
            offset=section.at(match.start("literal")),
            end_offset=section.at(match.end("literal")),
            anchor=literal,
            context=literal,
        )


RULE = RuleSpec(
    id="CTS0078",
    title="String literal exceeds declared capacity",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="String literals must fit the explicit capacity of their STRING destination.",
    topic="Correctness",
    check=check,
)
