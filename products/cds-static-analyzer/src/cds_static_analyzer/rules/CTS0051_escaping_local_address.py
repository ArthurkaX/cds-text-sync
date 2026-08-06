"""CTS0051 - address of a local value escapes its lifetime."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body


_ADR = re.compile(
    r"\bADR\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)", re.IGNORECASE
)
_TARGET = re.compile(
    r"(?P<target>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*:=\s*$",
    re.IGNORECASE,
)
_CALL = re.compile(
    r"\b[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?\s*\([^;]*$",
    re.IGNORECASE,
)
_RETURN = re.compile(r"\bRETURN\s*$", re.IGNORECASE)
_FUNCTION_NAME = re.compile(
    r"^\s*FUNCTION\s+(?P<name>[A-Za-z_]\w*)\b", re.IGNORECASE | re.MULTILINE
)
_LOCAL_KINDS = {
    "function",
    "method",
    "action",
    "property_get",
    "property_set",
}
_ESCAPING_SCOPES = {
    "VAR_GLOBAL",
    "VAR_EXTERNAL",
    "VAR_OUTPUT",
    "VAR_IN_OUT",
    "VAR_STAT",
}


def _block_qualifiers(unit):
    """Return declaration qualifiers keyed by member name.

    ``parse_var_blocks`` intentionally keeps the neutral scope name (for
    example ``VAR``) and does not retain RETAIN/PERSISTENT qualifiers. This
    small raw-text pass supplies just the information needed by this rule.
    """
    qualifiers = {}
    current = set()
    if not unit.declaration:
        return qualifiers
    for line_number, line in enumerate(unit.declaration.split("\n"), start=1):
        stripped = line.strip()
        if re.match(r"^END_VAR\b", stripped, re.IGNORECASE):
            current = set()
            continue
        opener = re.match(r"^VAR(?:_[A-Z]+)?(?:\s+([A-Z][A-Z_ ]*))?$", stripped, re.IGNORECASE)
        if opener:
            current = {
                word.upper()
                for word in (opener.group(1) or "").split()
            }
            continue
        for member in decl.all_members(unit):
            if member.get("line") == line_number:
                qualifiers[member.get("name", "").casefold()] = set(current)
    return qualifiers


def _members(unit):
    qualifier_map = _block_qualifiers(unit)
    return {
        member.get("name", "").casefold(): (
            (member.get("scope") or "").upper(),
            qualifier_map.get(member.get("name", "").casefold(), set()),
        )
        for member in decl.all_members(unit)
        if member.get("name")
    }


def _is_local(unit, member):
    scope = member[0]
    if scope == "VAR_TEMP":
        return True
    return scope == "VAR" and unit.kind in _LOCAL_KINDS


def _is_external_destination(target, members, function_name):
    normalized = re.sub(r"\s+", "", target).casefold()
    if "." in normalized or normalized == function_name.casefold():
        return True
    member = members.get(normalized)
    if member is None:
        return False
    scope, qualifiers = member
    return scope in _ESCAPING_SCOPES or bool(qualifiers & {"RETAIN", "PERSISTENT"})


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    members = _members(unit)
    local_names = {
        name
        for name, member in members.items()
        if _is_local(unit, member)
    }
    if not local_names:
        return
    function_match = _FUNCTION_NAME.search(unit.declaration or "")
    function_name = (
        function_match.group("name")
        if function_match
        else unit.qualified_name.rsplit(".", 1)[-1]
    )
    text = section.text

    for match in _ADR.finditer(text):
        local_name = match.group("name")
        if local_name.casefold() not in local_names:
            continue

        statement_start = text.rfind(";", 0, match.start()) + 1
        prefix = text[statement_start : match.start()]
        target = _TARGET.search(prefix)
        if target and _is_external_destination(target.group("target"), members, function_name):
            message = (
                f"address of local '{local_name}' escapes through "
                f"destination '{target.group('target').replace(' ', '')}'"
            )
        elif _CALL.search(prefix) or _RETURN.search(prefix):
            message = (
                f"address of local '{local_name}' is passed out of its "
                "lifetime through a call"
            )
        else:
            continue

        yield finding_in(
            message=message,
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=f"ADR({local_name})",
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0051",
    title="Escaping address of local value",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A local address may remain usable after its POU invocation ends.",
    topic="Correctness",
    check=check,
)
