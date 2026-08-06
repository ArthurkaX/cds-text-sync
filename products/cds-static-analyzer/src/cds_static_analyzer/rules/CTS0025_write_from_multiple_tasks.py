"""CTS0025 - shared project data written from multiple execution contexts."""

from __future__ import annotations

import re
from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.decl import all_members

_GLOBAL_ACCESS = re.compile(r"\b(?P<name>[A-Za-z_]\w*\s*\.\s*[A-Za-z_]\w*)\b")


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

    accesses = {}
    for unit in ctx.units:
        if unit.kind not in K.CALLABLE:
            continue
        tasks = execution.tasks_for(unit.qualified_name)
        if not tasks:
            continue
        section = body(unit)
        if not section:
            continue
        for match in _GLOBAL_ACCESS.finditer(section.text):
            name = re.sub(r"\s+", "", match.group("name")).casefold()
            if name not in globals_by_name:
                continue
            absolute = section.at(match.start())
            end = match.end()
            is_write = bool(re.match(r"\s*:=", section.text[end:]))
            for task in sorted(tasks):
                accesses.setdefault(name, {"read": [], "write": []})[
                    "write" if is_write else "read"
                ].append((task, unit, absolute, match.group("name")))

    for name in sorted(accesses):
        by_kind = accesses[name]
        writes = _by_task(by_kind["write"])
        reads = _by_task(by_kind["read"])
        display = name

        for first_task, second_task in _task_pairs(writes):
            occurrence = writes[second_task][0]
            yield _finding(
                display,
                occurrence,
                f"project variable '{display}' is written from multiple tasks "
                f"({first_task}, {second_task})",
            )

        # When both tasks write the same variable, the write/write finding is
        # the stronger and more useful diagnostic.  Do not add reciprocal
        # read/write findings caused by a read-modify-write expression.
        if len(writes) > 1:
            continue
        for write_task in sorted(writes):
            for read_task in sorted(reads):
                if write_task == read_task:
                    continue
                occurrence = reads[read_task][0]
                yield _finding(
                    display,
                    occurrence,
                    f"project variable '{display}' is written in task "
                    f"'{write_task}' and read in task '{read_task}'",
                )


def _by_task(occurrences):
    grouped = {}
    for task, unit, offset, target in occurrences:
        grouped.setdefault(task, []).append((task, unit, offset, target))
    return grouped


def _task_pairs(grouped):
    tasks = sorted(grouped)
    for index, first in enumerate(tasks):
        for second in tasks[index + 1 :]:
            yield first, second


def _finding(display, occurrence, message):
    _task, unit, offset, target = occurrence
    return finding_in(
        message=message,
        unit=unit,
        offset=offset,
        end_offset=offset + len(target.replace(" ", "")),
        anchor=target.replace(" ", ""),
        context=target,
    )


RULE = RuleSpec(
    id="CTS0025",
    title="Concurrent access to shared data",
    severity="suspicious",
    scope=Scope.PROJECT,
    requires={Capability.DECLARATIONS, Capability.EXECUTION_GRAPH},
    kinds="ANY",
    summary="Shared project data accessed by programs running in different contexts.",
    topic="Data consistency",
    check=check,
)
