"""CTS0087 - an R_TRIG/F_TRIG instance is not called every cycle."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl, kinds as K
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(", re.IGNORECASE)
_TRIGGER_TYPES = {"r_trig", "f_trig"}


def _inside_blocks(node, offset, result):
    for child in node.children:
        if child.start_offset <= offset < (child.end_offset or offset + 1):
            result.append(child.kind)
            _inside_blocks(child, offset, result)


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    instances = {}
    for member in decl.all_members(unit):
        type_name = (member.get("type") or "").strip().casefold()
        base = type_name.rsplit(".", 1)[-1]
        if member.get("name") and base in _TRIGGER_TYPES:
            instances[member["name"].casefold()] = member["name"]
    if not instances:
        return

    root = tree(unit)
    for match in _CALL.finditer(section.text):
        name = match.group("name").casefold()
        if name not in instances:
            continue
        absolute = section.at(match.start("name"))
        containing = []
        _inside_blocks(root, absolute, containing)
        if not containing:
            continue
        trigger = instances[name]
        kinds = ", ".join(containing)
        yield finding_in(
            message=(
                f"edge-trigger instance '{trigger}' is called inside {kinds}; "
                "the edge detector may miss or consume a transition"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end("name")),
            anchor=match.group("name"),
            context=f"{trigger}(...) in {kinds}",
        )


RULE = RuleSpec(
    id="CTS0087",
    title="Conditional edge-trigger call",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="R_TRIG and F_TRIG instances must be called once on every cycle.",
    topic="Correctness",
    check=check,
)
