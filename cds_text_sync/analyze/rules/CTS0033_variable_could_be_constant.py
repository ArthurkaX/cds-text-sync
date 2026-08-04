"""CTS0033 - local variables that could be declared CONSTANT."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.blanking import blank_noise, trim_strings
from cds_text_sync.analyze.st.body import body
from cds_text_sync.analyze.st.decl import all_members

_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
_TYPED_LITERAL = re.compile(
    r"\b[A-Za-z_]\w*\s*#\s*[A-Za-z0-9_.:-]+", re.IGNORECASE
)
_VAR_HEADER = re.compile(
    r"^\s*(VAR(?:_[A-Z]+)?)(?:\s+(?P<qualifiers>.*))?$", re.IGNORECASE
)
_UNSAFE_TYPE = re.compile(
    r"\b(?:ARRAY|POINTER|REFERENCE|INTERFACE|VARIANT)\b", re.IGNORECASE
)
_CONSTANT_WORDS = {"TRUE", "FALSE", "NULL", "AND", "OR", "XOR", "NOT", "MOD"}


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


def _declaration_line(unit, member):
    lines = (unit.declaration or "").split("\n")
    index = member.get("line", 0) - 1
    return lines[index] if 0 <= index < len(lines) else ""


def _block_qualifiers(unit, member):
    """Return qualifiers of the VAR block containing a member."""
    lines = (unit.declaration or "").split("\n")
    index = member.get("line", 0) - 1
    for current in range(index, -1, -1):
        line = lines[current].strip()
        if line.upper().startswith("END_VAR"):
            return set()
        match = _VAR_HEADER.match(line)
        if match:
            return set((match.group("qualifiers") or "").upper().split())
    return set()


def _is_local_candidate(unit, member):
    scope = (member.get("scope") or "").upper()
    if scope not in {"VAR", "VAR_TEMP", "VAR_STAT"}:
        return False
    qualifiers = _block_qualifiers(unit, member)
    if qualifiers & {"CONSTANT", "RETAIN", "PERSISTENT"}:
        return False
    if re.search(r"\bAT\b", _declaration_line(unit, member), re.IGNORECASE):
        return False
    return not _UNSAFE_TYPE.search(member.get("type", ""))


def _looks_like_constant(expression):
    """Accept literal arithmetic while conservatively rejecting identifiers."""
    if not expression or not expression.strip():
        return False
    clean = trim_strings(blank_noise(expression))
    clean = _TYPED_LITERAL.sub(" ", clean)
    return all(token.upper() in _CONSTANT_WORDS for token in _IDENTIFIER.findall(clean))


def _in_call_argument(text, start):
    """Return whether an identifier occurrence is an argument to a call."""
    depth = 0
    for index in range(start - 1, -1, -1):
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth:
                depth -= 1
                continue
            prefix = text[:index].rstrip()
            return bool(re.search(r"[A-Za-z_]\w*\s*$", prefix))
    return False


def _has_possible_write_or_alias(text, name):
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    for match in pattern.finditer(text):
        next_text = text[match.end():].lstrip()
        if next_text.startswith(":=") or next_text.startswith("[") or next_text.startswith("."):
            return True
        if _in_call_argument(text, match.start()):
            return True
    return False


def _visible_units(ctx, unit):
    visible_ids = {candidate.id for candidate in ctx.units}
    return [unit] + [
        other
        for other in ctx.snapshot.units_owned_by(unit.qualified_name)
        if other.id in visible_ids
    ]


def _shadowed_in(child, name):
    return any(
        member.get("name", "").casefold() == name.casefold()
        for member in all_members(child)
    )


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    if not unit.declaration:
        return

    for member in all_members(unit):
        name = member.get("name", "")
        if (
            not name
            or not _is_local_candidate(unit, member)
            or not _looks_like_constant(member.get("initial", ""))
        ):
            continue

        if any(
            _has_possible_write_or_alias(body(candidate).text, name)
            for candidate in _visible_units(ctx, unit)
            if candidate is unit or not _shadowed_in(candidate, name)
        ):
            continue

        yield finding_in(
            message=(
                f"variable '{name}' is initialized with a constant and is never "
                "modified; consider declaring it CONSTANT"
            ),
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=name,
            context=f"{name} : {member.get('type', '')} := {member.get('initial', '')}",
        )


RULE = RuleSpec(
    id="CTS0033",
    title="Variable could be declared CONSTANT",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="Local variables with constant initialization and no possible mutation.",
    topic="Style",
    check=check,
)
