"""CTS0013 - declared variables with no explicit source reference."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body
from cds_text_sync.analyze.st.decl import all_members

_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z_]\w*)(?![A-Za-z0-9_])")
_PLACEHOLDER_PART = re.compile(
    r"(?i)^(?:spare|dummy|reserved|unused|padding|filler)$"
)


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


def _is_placeholder(name):
    """Return whether *name* is an intentional spare/dummy-style name."""
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    return any(_PLACEHOLDER_PART.fullmatch(part) for part in parts)


def _tokens(units):
    """Lowercased identifier set over the implementations of *units*."""
    tokens = set()
    for unit in units:
        if not unit.implementation:
            continue
        tokens.update(
            match.group("name").lower()
            for match in _IDENTIFIER.finditer(body(unit).text)
        )
    return tokens


def _owner_units(ctx, unit):
    """A POU plus the owned units (methods/actions) visible to this run."""
    visible_ids = {candidate.id for candidate in ctx.units}
    owned = [
        candidate
        for candidate in ctx.snapshot.units_owned_by(unit.qualified_name)
        if candidate.id in visible_ids
    ]
    return [unit] + owned


def _member_is_candidate(member):
    scope = (member.get("scope") or "").upper()
    # Interface members have dedicated, more precise rules and may be used by
    # callers outside the project-view sources.
    if scope in {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}:
        return False
    return scope in {"VAR", "VAR_TEMP", "VAR_STAT", "VAR_GLOBAL"}


def check(ctx):
    """Report declarations for which no explicit source reference is found."""
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)

    all_text_tokens = None
    for unit in ctx.units:
        for member in all_members(unit):
            name = member.get("name", "")
            if not name or not _member_is_candidate(member) or _is_placeholder(name):
                continue

            scope = (member.get("scope") or "").upper()
            if scope == "VAR_GLOBAL":
                if all_text_tokens is None:
                    all_text_tokens = _tokens(ctx.units)
                used = name.lower() in all_text_tokens
            else:
                used = name.lower() in _tokens(_owner_units(ctx, unit))

            if used:
                continue
            yield finding_in(
                message=(
                    f"declared symbol '{name}' has no explicit reference in "
                    "the analyzed Structured Text"
                ),
                unit=unit,
                offset=_member_offset(unit, member),
                anchor=name,
                context=f"{name} : {member.get('type', '')}",
            )


RULE = RuleSpec(
    id="CTS0013",
    title="Declared symbol not referenced",
    severity="suspicious",
    scope=Scope.PROJECT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="ANY",
    summary="Declared variables with no explicit reference in analyzed ST.",
    topic="Dead code",
    check=check,
)
