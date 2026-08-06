"""CTS0053 - a call cannot be resolved to project or known library code."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.library import is_known_function_block


_BARE_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(", re.IGNORECASE)
_METHOD_CALL = re.compile(
    r"\b(?P<instance>[A-Za-z_]\w*)\s*\.\s*(?P<method>[A-Za-z_]\w*)\s*\(",
    re.IGNORECASE,
)
_NON_CALLS = {"IF", "FOR", "WHILE", "CASE", "REPEAT", "RETURN", "SEL", "MUX"}


def _local_library_instances(unit):
    return {
        member.get("name", "").casefold()
        for member in decl.all_members(unit)
        if member.get("name") and is_known_function_block(member.get("type", ""))
    }


def _finding(unit, section, start, end, name):
    return finding_in(
        message=(
            f"call '{name}' cannot be resolved to a project POU or known "
            "library symbol"
        ),
        unit=unit,
        offset=section.at(start),
        end_offset=section.at(end),
        anchor=name,
        context=f"{name}(...)",
    )


def check(ctx):
    execution = ctx.capability(Capability.EXECUTION_GRAPH)
    ctx.capability(Capability.ST_TEXT)

    for unit in ctx.units:
        if unit.kind not in K.CALLABLE:
            continue
        unresolved = {
            name.casefold()
            for name in execution.unresolved_calls.get(unit.qualified_name.casefold(), ())
        }
        if not unresolved:
            continue
        section = body(unit)
        if not section:
            continue
        local_library_instances = _local_library_instances(unit)
        method_starts = set()
        for match in _METHOD_CALL.finditer(section.text):
            method_starts.add(match.start("method"))
            name = f"{match.group('instance')}.{match.group('method')}"
            if name.casefold() not in unresolved:
                continue
            if match.group("instance").casefold() in {"this", "super"}:
                continue
            yield _finding(unit, section, match.start(), match.end(), name)

        for match in _BARE_CALL.finditer(section.text):
            if match.start() in method_starts:
                continue
            name = match.group("name")
            if name.upper() in _NON_CALLS:
                continue
            if name.casefold() in local_library_instances:
                continue
            if name.casefold() not in unresolved:
                continue
            yield _finding(unit, section, match.start(), match.end(), name)


RULE = RuleSpec(
    id="CTS0053",
    title="Unresolved call",
    severity="suspicious",
    scope=Scope.PROJECT,
    requires={Capability.EXECUTION_GRAPH, Capability.ST_TEXT},
    kinds="ANY",
    summary="A call is not resolved to a project POU or known library symbol.",
    topic="Code quality",
    check=check,
)
