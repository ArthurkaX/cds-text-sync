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
_ACCESS = re.compile(
    r"\b(?P<array>[A-Za-z_]\w*)\s*\[\s*(?P<indices>[^\]\n]+?)\s*\]"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")


def _constant_int(value):
    try:
        return int(value, 10)
    except (TypeError, ValueError):
        return None


def _array_bounds(unit):
    arrays = {}
    for member in decl.all_members(unit):
        typ = classify_type(member.get("type", ""))
        if typ.get("kind") != "array":
            continue
        dimensions = []
        for lower_text, upper_text in typ.get("dims", ()):
            lower = _constant_int(lower_text)
            upper = _constant_int(upper_text)
            if lower is None or upper is None:
                break
            dimensions.append((lower, upper))
        if len(dimensions) == len(typ.get("dims", ())):
            arrays[member["name"].lower()] = (member["name"], dimensions)
    return arrays


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def _split_indices(text):
    return [part.strip() for part in text.split(",")]


def _for_range(block, text, section):
    if block.kind != "FOR" or block.end_offset is None:
        return None
    loop_start = block.start_offset - section.base
    loop_end = block.end_offset - section.base
    header = _HEADER.search(text, loop_start, loop_end)
    if not header:
        return None
    parsed = _FORM.match(header.group("header"))
    if not parsed:
        return None
    start = int(parsed.group("start"))
    end = int(parsed.group("end"))
    step = int(parsed.group("step") or "1")
    if step == 0 or (start < end and step < 0) or (start > end and step > 0):
        return None
    low, high = (start, end) if step > 0 else (end, start)
    return {
        "start": loop_start,
        "end": loop_end,
        "body_start": header.end("do"),
        "counter": parsed.group("counter").lower(),
        "low": low,
        "high": high,
    }


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    arrays = _array_bounds(unit)
    section = body(unit)
    if not arrays or not section:
        return
    text = section.text

    loops = []
    for block in _walk(tree(unit)):
        loop = _for_range(block, text, section)
        if loop is not None:
            loops.append(loop)

    for access in _ACCESS.finditer(text):
        info = arrays.get(access.group("array").lower())
        if info is None:
            continue
        indices = _split_indices(access.group("indices"))
        name, dimensions = info
        if len(indices) != len(dimensions):
            continue
        enclosing = [
            loop
            for loop in loops
            if loop["body_start"] <= access.start() < loop["end"]
        ]
        for dimension, (index, bounds) in enumerate(zip(indices, dimensions), start=1):
            if not _IDENTIFIER.fullmatch(index):
                continue
            counter = index.lower()
            matching = [loop for loop in enclosing if loop["counter"] == counter]
            if not matching:
                continue
            loop = max(matching, key=lambda item: item["start"])
            low, high = loop["low"], loop["high"]
            array_low, array_high = bounds
            if low >= array_low and high <= array_high:
                continue
            absolute = section.at(access.start("indices") + access.group("indices").lower().find(index.lower()))
            yield finding_in(
                message=(
                    f"FOR counter range [{low}..{high}] can access dimension "
                    f"{dimension} of array '{name}' outside declared bounds "
                    f"[{array_low}..{array_high}]"
                ),
                unit=unit,
                offset=absolute,
                end_offset=section.at(
                    access.start("indices")
                    + access.group("indices").lower().find(index.lower())
                    + len(index)
                ),
                anchor=access.group(0),
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
