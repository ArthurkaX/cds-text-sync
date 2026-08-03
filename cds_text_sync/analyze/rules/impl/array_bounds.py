"""CTS0006: constant array indexes outside declared bounds."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise, trim_strings
from cds_text_sync.analyze.rules_api import finding_in
from cds_text_sync.analyze.st import decl
from cds_text_sync.engine.variable_map import classify_type

RULE_ID = "CTS0006"
SEVERITY = "danger"

_ACCESS_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*\[\s*([+-]?(?:\d+|(?:2|8|16)#[0-9A-Fa-f]+))\s*\]"
)


def _constant_int(value):
    """Parse the literal forms accepted by the first bounds check."""
    value = value.strip().upper()
    sign = -1 if value.startswith("-") else 1
    if value[:1] in {"+", "-"}:
        value = value[1:]
    if "#" in value:
        base, digits = value.split("#", 1)
        try:
            return sign * int(digits, int(base))
        except ValueError:
            return None
    try:
        return sign * int(value, 10)
    except ValueError:
        return None


def _array_bounds(unit):
    arrays = {}
    for member in decl.all_members(unit):
        typ = classify_type(member.get("type", ""))
        if typ.get("kind") != "array" or len(typ.get("dims", ())) != 1:
            continue
        lower = _constant_int(typ["dims"][0][0])
        upper = _constant_int(typ["dims"][0][1])
        if lower is not None and upper is not None:
            arrays.setdefault(member["name"].lower(), (member["name"], lower, upper))
    return arrays


def check(unit, ctx):
    """Flag literal indexes that are provably outside a local array range."""
    ctx.capability(Capability.DECLARATIONS)
    arrays = _array_bounds(unit)
    if not arrays:
        return
    body = unit.implementation if unit.implementation is not None else unit.text
    if not body:
        return
    clean = trim_strings(blank_noise(body))
    impl_start = next(
        (span.start_offset for span in unit.source_spans if span.role == "implementation"),
        0,
    )
    for match in _ACCESS_RE.finditer(clean):
        info = arrays.get(match.group(1).lower())
        if info is None:
            continue
        index = _constant_int(match.group(2))
        if index is None:
            continue
        name, lower, upper = info
        if lower <= index <= upper:
            continue
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message=(
                f"array '{name}' index {match.group(2)} is outside "
                f"declared bounds [{lower}..{upper}]"
            ),
            unit=unit,
            offset=impl_start + match.start(2),
            end_offset=impl_start + match.end(2),
            anchor=f"{name}[{match.group(2)}]",
            context=match.group(0),
            rule_title="Array index outside bounds",
        )
