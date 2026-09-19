"""CTS0025 - shared project data written from multiple execution contexts."""

from __future__ import annotations

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.global_access import global_access_index
from cds_static_analyzer.rules_api import RuleSpec, finding_in


def check(ctx):
    execution = ctx.capability(Capability.EXECUTION_GRAPH)
    ctx.capability(Capability.DECLARATIONS)
    accesses = {}
    index = global_access_index(ctx)
    for unit in ctx.units:
        tasks = execution.tasks_for(unit.qualified_name)
        if not tasks:
            continue
        for access in index.accesses_for(unit):
            name = f"{access.global_unit.qualified_name}.{access.member['name']}"
            key = name.casefold()
            for task in sorted(tasks):
                accesses.setdefault(key, {"name": name, "read": [], "write": []})[
                    "write" if access.write else "read"
                ].append((task, unit, access.offset, name))

    for key in sorted(accesses):
        by_kind = accesses[key]
        writes = _by_task(by_kind["write"])
        reads = _by_task(by_kind["read"])
        display = by_kind["name"]

        for first_task, second_task in _task_pairs(writes):
            occurrence = writes[second_task][0]
            yield _finding(
                display,
                occurrence,
                f"project variable '{display}' is written from multiple tasks "
                f"({first_task}, {second_task})",
            )

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
