"""CTS0025 - shared project data written from multiple execution contexts."""

from __future__ import annotations

import re
from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st import kinds as K
from cds_text_sync.analyze.st.body import body
from cds_text_sync.analyze.st.decl import all_members

_TARGET = re.compile(
    r"^\s*(?P<name>[A-Za-z_]\w*\s*\.\s*[A-Za-z_]\w*)\s*:="
)


def _global_members(ctx):
    globals_by_name = {}
    for unit in ctx.units:
        if unit.kind not in (K.GVL, K.GVL_PERSISTENT):
            continue
        for member in all_members(unit):
            name = member.get("name", "")
            if name:
                globals_by_name[f"{unit.qualified_name}.{name}".casefold()] = member
    return globals_by_name


def check(ctx):
    execution = ctx.capability(Capability.EXECUTION_GRAPH)
    ctx.capability(Capability.DECLARATIONS)
    globals_by_name = _global_members(ctx)
    if not globals_by_name:
        return

    writes = {}
    for unit in ctx.units:
        if unit.kind != K.PROGRAM:
            continue
        tasks = execution.tasks_for(unit.qualified_name)
        if not tasks:
            continue
        section = body(unit)
        if not section:
            continue
        for offset, statement in section.statements():
            match = _TARGET.match(statement)
            if not match:
                continue
            name = re.sub(r"\s+", "", match.group("name")).casefold()
            if name not in globals_by_name:
                continue
            for task in tasks:
                writes.setdefault(name, []).append((task, unit, offset, match.group("name")))

    for name, occurrences in writes.items():
        tasks = {task for task, _unit, _offset, _target in occurrences}
        if len(tasks) < 2:
            continue
        first_task = occurrences[0][0]
        for task, unit, offset, target in occurrences[1:]:
            if task == first_task:
                continue
            yield finding_in(
                message=(
                    f"project variable '{target}' is written from multiple tasks "
                    f"({first_task}, {task})"
                ),
                unit=unit,
                offset=offset,
                end_offset=offset + len(target.replace(" ", "")),
                anchor=target.replace(" ", ""),
                context=target,
            )


RULE = RuleSpec(
    id="CTS0025",
    title="Concurrent writes to shared data",
    severity="suspicious",
    scope=Scope.PROJECT,
    requires={Capability.DECLARATIONS, Capability.EXECUTION_GRAPH},
    kinds="ANY",
    summary="Shared project data written by programs running in different contexts.",
    topic="Data consistency",
    check=check,
)
