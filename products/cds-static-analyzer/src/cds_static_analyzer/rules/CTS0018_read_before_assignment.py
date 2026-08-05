"""CTS0018 - local variables read before their first assignment."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.decl import all_members

_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z_]\w*)(?![A-Za-z0-9_])")
_WRITE_AFTER = re.compile(
    r"\s*(?:(?:\.(?:[A-Za-z_]\w*|%[A-Za-z]\w*|\d+))|(?:\[[^\]]*\]))*\s*:=",
    re.IGNORECASE,
)
_LOCAL_SCOPES = {"VAR", "VAR_TEMP"}
_LOCAL_KINDS = {"function", "method", "action", "property_get", "property_set"}


def _member_offset(unit, member):
    line = member.get("line")
    if not line or not unit.declaration:
        return None
    lines = unit.declaration.split("\n")
    index = line - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return sum(len(lines[k]) + 1 for k in range(index)) + position


def _has_initial_value(member):
    initial = member.get("initial")
    return initial is not None and str(initial).strip() != ""


def _path_after(match, text):
    """Return a normalized selector path following an identifier."""
    tail = text[match.end() :]
    selectors = []
    position = 0
    while True:
        selector = re.match(
            r"\s*(?:\.\s*(?P<field>(?:[A-Za-z_]\w*|%[A-Za-z]\w*|\d+))|\[(?P<index>[^\]]*)\])",
            tail[position:],
            re.IGNORECASE,
        )
        if not selector:
            break
        if selector.group("field") is not None:
            selectors.append("." + selector.group("field").lower())
        else:
            selectors.append("[" + re.sub(r"\s+", "", selector.group("index")) + "]")
        position += selector.end()
    return "".join(selectors)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for member in all_members(unit):
        name = member.get("name", "")
        scope = (member.get("scope") or "").upper()
        if not name or _has_initial_value(member):
            continue
        if scope == "VAR_TEMP":
            pass
        elif scope == "VAR" and unit.kind in _LOCAL_KINDS:
            pass
        else:
            continue

        assigned = set()
        aggregate_assigned = False
        for match in _IDENTIFIER.finditer(section.text):
            if match.group("name").lower() != name.lower():
                continue

            path = _path_after(match, section.text)
            after = section.text[match.end() :]
            before = section.text[: match.start()]
            # In ``arg => local`` the left identifier is an argument label,
            # not a read of a local with the same name.
            if re.match(r"\s*=>", after):
                continue
            is_write = bool(_WRITE_AFTER.match(section.text, match.end()))
            is_output_argument = bool(
                re.search(r"=>\s*$", before)
            )
            is_address_output = bool(re.search(r"\bADR\s*\(\s*$", before, re.IGNORECASE))
            if is_write or is_output_argument or is_address_output:
                assigned.add(path.lower())
                # A field or indexed write initializes the aggregate for this
                # lexical rule. This covers ST unions and buffer-building
                # loops, whose exact storage relation is not in the parser.
                if path.startswith((".", "[")):
                    aggregate_assigned = True
                continue

            if path.lower() in assigned or aggregate_assigned:
                continue
            yield finding_in(
                message=f"local '{name}' is read before its first assignment",
                unit=unit,
                offset=section.at(match.start()),
                end_offset=section.at(match.end()),
                anchor=name,
                context=name,
            )
            break


RULE = RuleSpec(
    id="CTS0018",
    title="Read before assignment",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Local variables read before their first assignment.",
    topic="Correctness",
    check=check,
)
