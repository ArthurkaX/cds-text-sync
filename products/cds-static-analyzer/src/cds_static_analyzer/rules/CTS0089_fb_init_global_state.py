"""CTS0089 - dangerous global state access during FB_Init."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.function_blocks import (
    function_block_types,
    global_members,
    is_function_block_type,
)


_IDENTIFIER = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\b")
_METHOD_HEADER = re.compile(
    r"\bMETHOD(?:\s+(?:PUBLIC|PROTECTED|PRIVATE|INTERNAL))?\s+"
    r"(?P<name>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)


def _is_fb_init(unit):
    match = _METHOD_HEADER.search(unit.declaration or "")
    name = match.group("name") if match else unit.qualified_name.rsplit(".", 1)[-1]
    return name.casefold() == "fb_init"


def check(unit, ctx):
    if unit.kind != K.METHOD or not _is_fb_init(unit):
        return
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    names = function_block_types(ctx)
    globals_by_name = global_members(ctx)
    if not globals_by_name:
        return
    local_names = {
        member.get("name", "").casefold()
        for member in decl.all_members(unit)
        if member.get("name")
    }
    reported = set()
    text = section.text
    for match in _IDENTIFIER.finditer(text):
        name = match.group("name")
        key = name.casefold()
        if key in local_names or key not in globals_by_name or key in reported:
            continue
        after = text[match.end():]
        next_token = re.match(r"\s*(?P<token>\.|\(|:=|;|$)", after)
        token = next_token.group("token") if next_token else ""
        _owner, member = globals_by_name[key]
        is_global_fb = is_function_block_type(member.get("type", ""), names)
        is_write = token == ":=" or (
            token == "."
            and re.match(r"\s*\.\s*[A-Za-z_]\w*\s*:=", after)
        )
        if not is_global_fb and not is_write:
            continue
        reported.add(key)
        if is_global_fb:
            reason = "global function-block state is used during initialization"
        else:
            reason = "global state is written during initialization"
        yield finding_in(
            message=f"global '{name}' is accessed from FB_Init; {reason}",
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=name,
            context=match.group(0),
        )


RULE = RuleSpec(
    id="CTS0089",
    title="Global state access during FB_Init",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds=(K.METHOD,),
    summary="Global FB state or writes during FB_Init can depend on initialization order.",
    topic="Correctness",
    check=check,
)
