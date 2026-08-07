"""CTS0064 - pointers must not be retained across a restart."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.declarations import classify_type


_VAR_OPEN = re.compile(r"^VAR(?:_[A-Z]+)?(?:\s+(?P<qualifiers>[A-Z][A-Z_ ]*))?$", re.IGNORECASE)


def _qualifiers(unit):
    result = {}
    current = set()
    for line_number, line in enumerate((unit.declaration or "").split("\n"), start=1):
        stripped = line.strip()
        if re.match(r"^END_VAR\b", stripped, re.IGNORECASE):
            current = set()
            continue
        opener = _VAR_OPEN.fullmatch(stripped)
        if opener:
            current = {word.upper() for word in (opener.group("qualifiers") or "").split()}
            continue
        for member in decl.all_members(unit):
            if member.get("line") == line_number:
                result[member.get("name", "").casefold()] = set(current)
    return result


def _member_offset(section, member):
    lines = (section.raw or "").splitlines(keepends=True)
    line_number = member.get("line", 0)
    if not 1 <= line_number <= len(lines):
        return None
    line_start = sum(len(line) for line in lines[: line_number - 1])
    match = re.search(
        rf"\b{re.escape(member.get('name', ''))}\b",
        lines[line_number - 1],
        re.IGNORECASE,
    )
    if not match:
        return None
    return section.at(line_start + match.start())


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    section = declaration(unit)
    if not section:
        return
    qualifiers = _qualifiers(unit)
    for member in decl.all_members(unit):
        info = classify_type(member.get("type", ""))
        if info.get("kind") != "scalar" or str(info.get("base", "")).upper() != "POINTER":
            continue
        name = member.get("name", "")
        member_qualifiers = qualifiers.get(name.casefold(), set())
        persistent_gvl = unit.kind == "gvl_persistent"
        if not persistent_gvl and not member_qualifiers & {"RETAIN", "PERSISTENT"}:
            continue
        offset = _member_offset(section, member)
        if offset is None:
            continue
        qualifier_text = "PERSISTENT" if "PERSISTENT" in member_qualifiers or persistent_gvl else "RETAIN"
        yield finding_in(
            message=(
                f"pointer '{name}' is declared in {qualifier_text} storage; "
                "its address may be invalid after a restart"
            ),
            unit=unit,
            offset=offset,
            end_offset=offset + len(name),
            anchor=name,
            context=member.get("type", ""),
        )


RULE = RuleSpec(
    id="CTS0064",
    title="Retained pointer",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="ANY",
    summary="A RETAIN/PERSISTENT pointer may contain an invalid address after restart.",
    topic="Correctness",
    check=check,
)
