"""CTS0085 - a project POU call graph contains a recursive cycle."""

from __future__ import annotations

from collections import deque

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import kinds as K


def _key(name):
    return (name or "").strip().casefold()


def _path(start, target, edges, allowed):
    queue = deque([(start, [start])])
    seen = {start}
    while queue:
        current, path = queue.popleft()
        if current == target:
            return path
        for callee in sorted(edges.get(current, ())):
            if callee not in allowed or callee in seen:
                continue
            seen.add(callee)
            queue.append((callee, path + [callee]))
    return None


def _strongly_connected(nodes, edges):
    index = 0
    stack = []
    on_stack = set()
    indices = {}
    lowlinks = {}
    components = []

    def visit(node):
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for callee in sorted(edges.get(node, ())):
            if callee not in nodes:
                continue
            if callee not in indices:
                visit(callee)
                lowlinks[node] = min(lowlinks[node], lowlinks[callee])
            elif callee in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[callee])
        if lowlinks[node] != indices[node]:
            return
        component = set()
        while True:
            current = stack.pop()
            on_stack.remove(current)
            component.add(current)
            if current == node:
                break
        components.append(component)

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return components


def check(ctx):
    ctx.capability(Capability.EXECUTION_GRAPH)
    graph = ctx.capability(Capability.EXECUTION_GRAPH)
    units = {
        _key(unit.qualified_name): unit
        for unit in ctx.units
        if unit.kind in K.CALLABLE
    }
    if not units:
        return

    edges = {
        caller: {callee for callee in graph.calls.get(caller, ()) if callee in units}
        for caller in units
    }
    display = {name: units[name].qualified_name for name in units}
    for component in _strongly_connected(set(units), edges):
        if len(component) == 1:
            only = next(iter(component))
            if only not in edges.get(only, set()):
                continue
        candidates = []
        for caller in sorted(component):
            for callee, offset, expression in graph.call_sites.get(caller, ()):
                if callee not in component:
                    continue
                return_path = _path(callee, caller, edges, component)
                if not return_path:
                    continue
                cycle = [caller] + return_path
                cycle_text = " -> ".join(display[name] for name in cycle)
                candidates.append(
                    (
                        caller,
                        offset,
                        expression,
                        cycle_text,
                    )
                )
        if not candidates:
            continue
        caller, offset, expression, cycle_text = min(
            candidates, key=lambda item: (item[0], item[1], item[2])
        )
        unit = units[caller]
        anchor = expression.strip()
        yield finding_in(
            message=(
                f"recursive POU call cycle detected: {cycle_text}; "
                "the fixed PLC call stack may overflow"
            ),
            unit=unit,
            offset=offset,
            end_offset=offset + len(expression),
            anchor=anchor,
            context=anchor,
        )


RULE = RuleSpec(
    id="CTS0085",
    title="Recursive POU call cycle",
    severity="danger",
    scope=Scope.PROJECT,
    requires={Capability.EXECUTION_GRAPH},
    kinds="ANY",
    summary="Project POU calls must not form a direct or indirect recursion cycle.",
    topic="Correctness",
    check=check,
)
