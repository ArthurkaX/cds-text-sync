"""CTS0054 - an assignment narrows a known scalar type implicitly."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_ASSIGNMENT = re.compile(
    r"\b(?P<target>[A-Za-z_]\w*)\s*:=\s*(?P<source>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)

_INTEGER_RANGES = {
    "SINT": (-128, 127),
    "USINT": (0, 255),
    "BYTE": (0, 255),
    "INT": (-32768, 32767),
    "UINT": (0, 65535),
    "WORD": (0, 65535),
    "DINT": (-2147483648, 2147483647),
    "UDINT": (0, 4294967295),
    "DWORD": (0, 4294967295),
    "LINT": (-9223372036854775808, 9223372036854775807),
    "ULINT": (0, 18446744073709551615),
    "LWORD": (0, 18446744073709551615),
}

_REAL_ORDER = {"REAL": 1, "LREAL": 2}


def _base_type(type_name):
    info = classify_type(type_name)
    if info.get("kind") != "scalar":
        return None
    return str(info.get("base", "")).upper()


def _narrowing_reason(source, target):
    if source in _INTEGER_RANGES and target in _INTEGER_RANGES:
        source_low, source_high = _INTEGER_RANGES[source]
        target_low, target_high = _INTEGER_RANGES[target]
        if target_low <= source_low and target_high >= source_high:
            return None
        return "value range"

    if source in _REAL_ORDER and target in _REAL_ORDER:
        if _REAL_ORDER[source] > _REAL_ORDER[target]:
            return "precision"
        return None

    # A real-to-integer assignment loses both fractional information and, in
    # general, part of the source range. Integer-to-real is intentionally not
    # reported here; it has a different precision profile and deserves its
    # own rule when the analyzer can prove a problematic value.
    if source in _REAL_ORDER and target in _INTEGER_RANGES:
        return "range and fractional precision"
    return None


def _inside_call_argument(text, start):
    """Return whether an assignment-like token is a named call argument."""
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
            return bool(re.search(r"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?\s*$", prefix))
    return False


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    section = body(unit)
    if not section:
        return

    types = {}
    for member in decl.all_members(unit):
        name = member.get("name", "")
        base = _base_type(member.get("type", ""))
        if name and base:
            types[name.casefold()] = base

    for match in _ASSIGNMENT.finditer(section.text):
        if _inside_call_argument(section.text, match.start()):
            continue
        target_name = match.group("target")
        source_name = match.group("source")
        target = types.get(target_name.casefold())
        source = types.get(source_name.casefold())
        if not target or not source:
            continue
        reason = _narrowing_reason(source, target)
        if reason is None:
            continue
        absolute = section.at(match.start())
        expression = match.group(0)
        yield finding_in(
            message=(
                f"implicit narrowing conversion from {source} to {target} "
                f"may lose {reason}; use an explicit TO_ conversion"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0054",
    title="Implicit narrowing conversion",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Assignments must not silently narrow a known scalar type.",
    topic="Correctness",
    check=check,
)
