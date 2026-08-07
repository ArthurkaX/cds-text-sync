"""CTS0086 - an interface is used before a visible initialization."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st import kinds as K


_ACCESS = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\.\s*(?P<member>[A-Za-z_]\w*)\b")
_ASSIGN = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*:=", re.IGNORECASE)


def _type_names(unit):
    qualified = unit.qualified_name.casefold()
    return {qualified, qualified.rsplit(".", 1)[-1]}


def _interface_types(ctx):
    names = {}
    ambiguous = set()
    for unit in ctx.units:
        if unit.kind != K.INTERFACE:
            continue
        for name in _type_names(unit):
            if name in names and names[name] != unit.qualified_name.casefold():
                ambiguous.add(name)
            else:
                names[name] = unit.qualified_name.casefold()
    return {name for name in names if name not in ambiguous}


def _is_interface(type_name, interface_types):
    text = (type_name or "").strip().casefold()
    return text in interface_types or text.rsplit(".", 1)[-1] in interface_types


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    interface_types = _interface_types(ctx)
    if not interface_types:
        return

    interfaces = {}
    for member in decl.all_members(unit):
        scope = (member.get("scope") or "").upper()
        # Inputs and in-outs are initialized by the caller's contract. The
        # rule is for local/stateful interface variables owned by this POU.
        if scope in {"VAR_INPUT", "VAR_IN_OUT"}:
            continue
        name = member.get("name", "")
        if name and _is_interface(member.get("type", ""), interface_types):
            interfaces[name.casefold()] = member
    if not interfaces:
        return

    assignments = {}
    for match in _ASSIGN.finditer(section.text):
        name = match.group("name").casefold()
        if name in interfaces:
            assignments.setdefault(name, section.at(match.start("name")))

    for match in _ACCESS.finditer(section.text):
        name = match.group("name").casefold()
        if name not in interfaces:
            continue
        first_use = section.at(match.start("name"))
        member = interfaces[name]
        initial = (member.get("initial") or "").strip()
        has_declaration_value = bool(initial) and initial not in {"0", "NULL"}
        first_assignment = assignments.get(name)
        if has_declaration_value or (
            first_assignment is not None and first_assignment < first_use
        ):
            continue
        display = member.get("name", match.group("name"))
        if first_assignment is None:
            message = (
                f"interface '{display}' is used before it is initialized; "
                "no assignment is visible in this POU"
            )
        else:
            message = (
                f"interface '{display}' is used before its first visible "
                "initialization"
            )
        yield finding_in(
            message=message,
            unit=unit,
            offset=first_use,
            end_offset=section.at(match.end()),
            anchor=match.group(0).strip(),
            context=match.group(0).strip(),
        )
        break


RULE = RuleSpec(
    id="CTS0086",
    title="Uninitialized interface use",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="An interface is accessed before a visible assignment or initialization.",
    topic="Correctness",
    check=check,
)
