"""CTS0028 - operations that are fragile for single-byte STRING values."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body
from cds_text_sync.analyze.st.decl import all_members


_IDENT = r"[A-Za-z_]\w*"
_INDEX = re.compile(rf"\b(?P<name>{_IDENT})\s*\[")
_ADR = re.compile(rf"\bADR\s*\(\s*(?P<name>{_IDENT})\s*\)", re.IGNORECASE)
_NON_ASCII_ASSIGN = re.compile(
    rf"\b(?P<name>{_IDENT})\s*:=\s*'(?P<value>(?:''|[^'])*)'"
)


def _string_names(unit):
    names = set()
    for member in all_members(unit):
        type_name = member.get("type", "").strip().upper()
        if re.match(r"^STRING(?:\s*\(|$)", type_name):
            names.add(member.get("name", "").casefold())
    return names


def _emit(section, unit, match, message, context):
    name = match.group("name")
    yield finding_in(
        message=message,
        unit=unit,
        offset=section.at(match.start()),
        end_offset=section.at(match.end()),
        anchor=name,
        context=context,
    )


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.DECLARATIONS)
    names = _string_names(unit)
    section = body(unit)
    if not names or not section:
        return

    for match in _INDEX.finditer(section.text):
        if match.group("name").casefold() not in names:
            continue
        yield from _emit(
            section,
            unit,
            match,
            "indexed access to STRING may depend on single-byte encoding",
            f"{match.group('name')}[...]",
        )

    for match in _ADR.finditer(section.text):
        if match.group("name").casefold() not in names:
            continue
        yield from _emit(
            section,
            unit,
            match,
            "taking the address of STRING is encoding-sensitive",
            f"ADR({match.group('name')})",
        )

    raw_implementation = unit.implementation or ""
    for match in _NON_ASCII_ASSIGN.finditer(raw_implementation):
        if match.group("name").casefold() not in names:
            continue
        clean_assignment = re.match(
            rf"\b{re.escape(match.group('name'))}\s*:=",
            section.text[match.start() :],
            re.IGNORECASE,
        )
        if clean_assignment is None:
            continue
        value = match.group("value").replace("''", "'")
        if not any(ord(char) > 127 for char in value):
            continue
        yield finding_in(
            message="non-ASCII literal assigned to STRING may be misencoded",
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=match.group("name"),
            context=f"{match.group('name')} := '{value}'",
        )


RULE = RuleSpec(
    id="CTS0028",
    title="Suspicious STRING operation",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="STRING operations that can depend on the configured encoding.",
    topic="Correctness",
    check=check,
)
