"""CTS0052 - a function-block field is read before its current-cycle call."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body


_ACCESS = re.compile(
    r"\b(?P<instance>[A-Za-z_]\w*)\s*\.\s*(?P<field>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)
_CALL = re.compile(r"\b(?P<instance>[A-Za-z_]\w*)\s*\(", re.IGNORECASE)
_KNOWN_OUTPUTS = {
    "ton": {"q", "et"},
    "tof": {"q", "et"},
    "tp": {"q", "et"},
    # CLK is an input in the IEC edge-trigger FBs, but direct reads of it are
    # still state-dependent and are covered with Q for lifecycle consistency.
    "r_trig": {"q", "clk"},
    "f_trig": {"q", "clk"},
}


def _type_names(unit):
    qualified = unit.qualified_name.casefold()
    return {qualified, qualified.rsplit(".", 1)[-1]}


def _function_block_outputs(ctx):
    outputs = {}
    for candidate in ctx.units:
        if candidate.kind != K.FUNCTION_BLOCK:
            continue
        fields = {
            member.get("name", "").casefold()
            for member in decl.output_members(candidate)
            if member.get("name")
        }
        for name in _type_names(candidate):
            outputs[name] = fields
    return outputs


def _instances(unit, ctx):
    custom_outputs = _function_block_outputs(ctx)
    instances = {}
    for member in decl.all_members(unit):
        name = member.get("name", "")
        type_name = member.get("type", "").strip()
        if not name or not type_name:
            continue
        base = type_name.casefold().rsplit(".", 1)[-1]
        fields = _KNOWN_OUTPUTS.get(base)
        if fields is None:
            fields = custom_outputs.get(type_name.casefold())
            if fields is None:
                fields = custom_outputs.get(base)
        if fields:
            instances[name.casefold()] = (name, fields)
    return instances


def check(unit, ctx):
    if unit.kind not in K.CALLABLE:
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    instances = _instances(unit, ctx)
    if not instances:
        return

    text = section.text
    first_call = {}
    for match in _CALL.finditer(text):
        name = match.group("instance").casefold()
        if name in instances:
            first_call.setdefault(name, match.start())

    for access in _ACCESS.finditer(text):
        instance_key = access.group("instance").casefold()
        info = instances.get(instance_key)
        if info is None:
            continue
        instance_name, fields = info
        field = access.group("field")
        if field.casefold() not in fields:
            continue
        # A field assignment or named-output syntax is not a read.
        if re.match(r"\s*:=", text[access.end() :]) or re.match(
            r"\s*=>", text[access.end() :]
        ):
            continue
        call_offset = first_call.get(instance_key)
        if call_offset is not None and call_offset < access.start():
            continue
        if call_offset is None:
            message = (
                f"function-block instance '{instance_name}' is never called "
                f"before reading '.{field}' in this cycle"
            )
        else:
            message = (
                f"function-block instance '{instance_name}' field '.{field}' "
                "is read before the instance is called in this cycle"
            )
        yield finding_in(
            message=message,
            unit=unit,
            offset=section.at(access.start()),
            end_offset=section.at(access.end()),
            anchor=f"{instance_name}.{field}",
            context=access.group(0),
        )


RULE = RuleSpec(
    id="CTS0052",
    title="Function-block output read before call",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A stateful function-block field is read before its current-cycle call.",
    topic="Correctness",
    check=check,
)
