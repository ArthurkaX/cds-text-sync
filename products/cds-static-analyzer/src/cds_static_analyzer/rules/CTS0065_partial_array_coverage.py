"""CTS0065 - a literal FOR range covers only part of an array."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type

_FOR = re.compile(r"\bFOR\s+(?P<counter>[A-Za-z_]\w*)\s*:=\s*(?P<start>[+-]?\d+)\s+TO\s+(?P<end>[+-]?\d+)(?:\s+BY\s+(?P<step>[+-]?\d+))?\s+DO\b", re.I)
_ACCESS = re.compile(r"\b(?P<array>[A-Za-z_]\w*)\s*\[\s*(?P<index>[A-Za-z_]\w*)\s*\]")

def _walk(node):
    for child in node.children:
        yield child
        yield from _walk(child)

def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    arrays = {}
    for member in decl.all_members(unit):
        info = classify_type(member.get("type", ""))
        if info.get("kind") != "array" or len(info.get("dims", ())) != 1:
            continue
        try:
            lo, hi = (int(value, 0) for value in info["dims"][0])
        except (TypeError, ValueError):
            continue
        arrays[member["name"].lower()] = (member["name"], lo, hi)
    for block in _walk(tree(unit)):
        if block.kind != "FOR" or block.end_offset is None:
            continue
        start = block.start_offset - section.base
        end = block.end_offset - section.base
        match = _FOR.search(section.text, start, end)
        if not match:
            continue
        low, high = sorted((int(match["start"]), int(match["end"])))
        counter = match["counter"].lower()
        for access in _ACCESS.finditer(section.text, match.end(), end):
            if access["index"].lower() != counter:
                continue
            info = arrays.get(access["array"].lower())
            if not info or not (info[1] <= low <= high <= info[2]):
                continue
            if low == info[1] and high == info[2]:
                continue
            absolute = section.at(access.start())
            yield finding_in(
                message=f"FOR range [{low}..{high}] covers only part of array '{info[0]}' [{info[1]}..{info[2]}]",
                unit=unit, offset=absolute, end_offset=section.at(access.end()),
                anchor=access.group(0), context=access.group(0),
            )

RULE = RuleSpec(id="CTS0065", title="Partial array coverage", severity="suspicious",
                scope=Scope.UNIT, requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
                kinds="CALLABLE", summary="A FOR loop indexes only part of an array.", topic="Code quality", check=check)
