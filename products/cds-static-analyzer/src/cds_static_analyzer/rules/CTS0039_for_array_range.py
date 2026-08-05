"""CTS0039 - FOR counter can address an array outside its bounds."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_HEADER = re.compile(r"\bFOR\b(?P<header>.*?)(?P<do>\bDO\b)", re.IGNORECASE | re.DOTALL)
_FORM = re.compile(
    r"^\s*(?P<counter>[A-Za-z_]\w*)\s*:=\s*(?P<start>[+-]?\d+)\s+TO\s+"
    r"(?P<end>[+-]?\d+)(?:\s+BY\s+(?P<step>[+-]?\d+))?\s*$",
    re.IGNORECASE,
)
_ACCESS = re.compile(r"\b(?P<array>[A-Za-z_]\w*)\s*\[\s*(?P<index>[A-Za-z_]\w*)\s*\]")


def _constant_int(value):
    try:
        return int(value, 10)
    except (TypeError, ValueError):
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
            arrays[member["name"].lower()] = (member["name"], lower, upper)
    return arrays


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    arrays = _array_bounds(unit)
    section = body(unit)
    if not arrays or not section:
        return
    text = section.text

    for block in _walk(tree(unit)):
        if block.kind != "FOR" or block.end_offset is None:
            continue
        loop_start = block.start_offset - section.base
        loop_end = block.end_offset - section.base
        header = _HEADER.search(text, loop_start, loop_end)
        if not header:
            continue
        parsed = _FORM.match(header.group("header"))
        if not parsed:
            continue
        counter = parsed.group("counter").lower()
        start = int(parsed.group("start"))
        end = int(parsed.group("end"))
        step = int(parsed.group("step") or "1")
        if step == 0 or (start < end and step < 0) or (start > end and step > 0):
            continue
        low, high = (start, end) if step > 0 else (end, start)
        body_start = header.end("do")
        for access in _ACCESS.finditer(text, body_start, loop_end):
            info = arrays.get(access.group("array").lower())
            if info is None or access.group("index").lower() != counter:
                continue
            name, array_low, array_high = info
            if low >= array_low and high <= array_high:
                continue
            absolute = section.at(access.start("index"))
            yield finding_in(
                message=(
                    f"FOR counter range [{low}..{high}] can access array "
                    f"'{name}' outside declared bounds [{array_low}..{array_high}]"
                ),
                unit=unit,
                offset=absolute,
                end_offset=section.at(access.end("index")),
                anchor=f"{name}[{access.group('index')}]",
                context=access.group(0),
            )


RULE = RuleSpec(
    id="CTS0039",
    title="FOR range exceeds array bounds",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A literal FOR counter range can index an array outside its bounds.",
    topic="Correctness",
    check=check,
)
