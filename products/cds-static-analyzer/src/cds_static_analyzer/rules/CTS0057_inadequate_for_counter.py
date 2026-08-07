"""CTS0057 - a FOR counter cannot represent its literal loop bounds."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_HEADER = re.compile(
    r"\bFOR\b(?P<header>.*?)(?P<do>\bDO\b)", re.IGNORECASE | re.DOTALL
)
_FORM = re.compile(
    r"^\s*(?P<counter>[A-Za-z_]\w*)\s*"
    r"(?:\:\s*(?P<inline_type>[A-Za-z_]\w*))?\s*:=\s*"
    r"(?P<start>[+-]?\d+)\s+TO\s+(?P<end>[+-]?\d+)"
    r"(?:\s+BY\s+(?P<step>[+-]?\d+))?\s*$",
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


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def _counter_types(unit):
    types = {}
    for member in decl.all_members(unit):
        info = classify_type(member.get("type", ""))
        if info.get("kind") == "scalar":
            types[member.get("name", "").casefold()] = str(
                info.get("base", "")
            ).upper()
    return types


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    text = section.text
    types = _counter_types(unit)

    for block in _walk(tree(unit)):
        if block.kind != "FOR":
            continue
        local_start = block.start_offset - section.base
        local_end = (
            block.end_offset - section.base
            if block.end_offset is not None
            else len(text)
        )
        header = _HEADER.search(text, local_start, local_end)
        if not header:
            continue
        parsed = _FORM.match(header.group("header"))
        if not parsed:
            continue

        counter = parsed.group("counter")
        counter_type = (
            parsed.group("inline_type") or types.get(counter.casefold(), "")
        ).upper()
        limits = _INTEGER_RANGES.get(counter_type)
        if limits is None:
            continue

        start = int(parsed.group("start"))
        end = int(parsed.group("end"))
        step = int(parsed.group("step") or "1")
        if step == 0 or (start < end and step < 0) or (start > end and step > 0):
            continue
        low, high = (start, end) if step > 0 else (end, start)
        minimum, maximum = limits
        if minimum <= low and high <= maximum:
            continue

        violations = []
        if low < minimum:
            violations.append(f"lower bound {low} < {minimum}")
        if high > maximum:
            violations.append(f"upper bound {high} > {maximum}")
        expression = header.group(0).strip()
        absolute = section.at(header.start())
        yield finding_in(
            message=(
                f"FOR counter '{counter}' has type {counter_type}, but its "
                f"literal range [{low}..{high}] exceeds the type range "
                f"[{minimum}..{maximum}] ({'; '.join(violations)})"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(header.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0057",
    title="Inadequate FOR counter type",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A FOR counter type cannot represent its literal loop bounds.",
    topic="Correctness",
    check=check,
)
