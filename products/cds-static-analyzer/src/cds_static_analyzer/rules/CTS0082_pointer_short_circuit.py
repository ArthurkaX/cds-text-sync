"""CTS0082 - pointer safety must not rely on AND evaluation order."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_GUARD = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*<>\s*0\s+AND\b(?P<tail>[^;\n]*)",
    re.IGNORECASE,
)
_DEREFERENCE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\^")


def _pointer_names(unit):
    return {
        member["name"].casefold()
        for member in decl.all_members(unit)
        if classify_type(member.get("type", "")).get("base", "").upper()
        == "POINTER"
    }


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    pointers = _pointer_names(unit)
    if not pointers:
        return

    for match in _GUARD.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in pointers:
            continue
        dereference = next(
            (
                item
                for item in _DEREFERENCE.finditer(match.group("tail"))
                if item.group("name").casefold() == name.casefold()
            ),
            None,
        )
        if dereference is None:
            continue

        end = match.start("tail") + dereference.end()
        expression = section.text[match.start() : end].strip()
        absolute = section.at(match.start())
        yield finding_in(
            message=(
                f"pointer '{name}' is dereferenced in an AND condition; "
                "do not rely on short-circuit evaluation for the null check"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(end),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0082",
    title="Pointer guard relies on short-circuit evaluation",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A pointer dereference is guarded only by the left operand of AND.",
    topic="Correctness",
    check=check,
)
