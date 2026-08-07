"""CTS0093 - REFERENCE use inside a declaration initializer."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.declarations import classify_type


_USE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*)?"
)
_DIRECT_BINDING = re.compile(
    r"^\s*(?P<left>[A-Za-z_]\w*)\s*:\s*REFERENCE\b"
    r".*?:=\s*(?P<right>[A-Za-z_]\w*)\s*$",
    re.IGNORECASE,
)


def _reference_names(unit, ctx):
    # The project-wide part is identical for every callable in this rule.
    # Computing it inside every unit check made large projects quadratic.
    key = "cts0093_project_reference_names"
    project_names = ctx._cache.get(key)
    if project_names is None:
        project_names = set()
        for candidate in ctx.units:
            if candidate.kind not in (K.GVL, K.GVL_PERSISTENT):
                continue
            for member in decl.all_members(candidate):
                if (
                    member.get("name")
                    and classify_type(member.get("type", "")).get("base", "").upper()
                    == "REFERENCE"
                ):
                    project_names.add(member["name"].casefold())
        ctx._cache[key] = project_names

    names = set(project_names)

    # A callable can declare a local REFERENCE as well.
    for member in decl.all_members(unit):
        if (
            member.get("name")
            and classify_type(member.get("type", "")).get("base", "").upper()
            == "REFERENCE"
        ):
            names.add(member["name"].casefold())
    return names


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = declaration(unit)
    if not section:
        return
    references = _reference_names(unit, ctx)
    if not references:
        return

    for match in _USE.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in references:
            continue
        statement_start = section.text.rfind(";", 0, match.start()) + 1
        statement_end = section.text.find(";", match.end())
        if statement_end < 0:
            statement_end = len(section.text)
        statement = section.text[statement_start:statement_end]
        assignment = statement.find(":=")
        if assignment < 0 or match.start() < statement_start + assignment + 2:
            continue
        # Binding a reference itself is intentional and does not read the
        # referenced object. A member/value access in the initializer is a
        # real use and remains reportable.
        if _DIRECT_BINDING.fullmatch(statement):
            continue
        yield finding_in(
            message=(
                f"reference '{name}' is used in a declaration initializer "
                "before its validity can be checked"
            ),
            unit=unit,
            offset=section.at(match.start("name")),
            end_offset=section.at(match.end()),
            anchor=match.group(0).strip(),
            context=statement.strip(),
        )


RULE = RuleSpec(
    id="CTS0093",
    title="Reference use in declaration initializer",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A REFERENCE is read before the POU body can validate it.",
    topic="Correctness",
    check=check,
)
