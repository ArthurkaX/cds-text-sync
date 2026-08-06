"""CTS0045 - callable POUs that cannot be reached from a task root."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K


_HEADER = re.compile(
    r"\b(?:PROGRAM|FUNCTION_BLOCK|FUNCTION|METHOD|ACTION|PROPERTY)\s+"
    r"(?P<name>[A-Za-z_]\w*)",
    re.IGNORECASE,
)


def _key(name):
    return (name or "").casefold()


def _header_location(unit):
    """Return the source offset of a callable's declaration name, if known."""
    declaration = unit.declaration or ""
    match = _HEADER.search(declaration)
    if match is None:
        return None
    # Declaration spans are the first source section for normal ST units.
    for span in unit.source_spans:
        if span.role == "declaration":
            return span.start_offset + match.start("name")
    return match.start("name")


def check(ctx):
    execution = ctx.capability(Capability.EXECUTION_GRAPH)
    visible = {
        _key(unit.qualified_name): unit
        for unit in ctx.units
        if unit.kind in K.CALLABLE
    }
    if not visible:
        return

    # Without a resolved root, reachability is unknown rather than negative.
    roots = {
        root
        for task_roots in execution.task_roots.values()
        for root in task_roots
        if root is not None
    }
    if not roots:
        return

    reachable = set()
    for task_name in execution.task_roots:
        reachable.update(execution.reachable_from(task_name))
    unreachable = set(visible) - {_key(name) for name in reachable}

    for name in sorted(unreachable):
        unit = visible[name]
        caller_keys = sorted(
            caller
            for caller, callees in execution.calls.items()
            if name in callees and _key(caller) in unreachable
        )
        if caller_keys:
            caller_text = ", ".join(
                visible[caller].qualified_name for caller in caller_keys
            )
            message = (
                f"POU '{unit.qualified_name}' is reachable only through "
                f"unreachable POU(s): {caller_text}"
            )
        else:
            message = (
                f"POU '{unit.qualified_name}' is not reachable from any "
                "configured task"
            )

        offset = _header_location(unit)
        name_start = offset
        yield finding_in(
            message=message,
            unit=unit,
            offset=offset,
            end_offset=(name_start + len(unit.qualified_name.rsplit(".", 1)[-1])
                        if name_start is not None else None),
            anchor=unit.qualified_name,
            context=unit.kind,
        )


RULE = RuleSpec(
    id="CTS0045",
    title="Unreachable POU",
    severity="suspicious",
    scope=Scope.PROJECT,
    requires={Capability.EXECUTION_GRAPH},
    kinds="ANY",
    summary="Callable POUs must be reachable from a configured task root.",
    topic="Dead code",
    check=check,
)
