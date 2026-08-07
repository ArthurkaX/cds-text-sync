"""Execution contexts and call reachability for project-wide analysis.

This module deliberately works from ``ProjectSnapshot`` units.  It is the
analyzer's conservative execution model: task roots come from task
configuration projections and calls are resolved only against project units
and locally declared FB instances.  Unknown library or dynamic calls do not
invent edges.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict, deque

from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.decl import all_members
from cds_static_analyzer.st.library import is_known_function, is_known_function_block


_BARE_CALL = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(")
_METHOD_CALL = re.compile(
    r"\b(?P<instance>[A-Za-z_]\w*)\s*\.\s*(?P<method>[A-Za-z_]\w*)\s*\("
)
_NON_CALLS = {
    "IF", "FOR", "WHILE", "CASE", "REPEAT", "RETURN", "SEL", "MUX",
}


def _key(name):
    return (name or "").strip().casefold()


def _short(name):
    return _key(name).rsplit(".", 1)[-1]


def _task_roots(unit):
    """Return program names listed by a task configuration projection."""
    try:
        root = ET.fromstring(unit.text)
    except (ET.ParseError, TypeError):
        return set()
    names = set()
    for element in root.iter():
        if element.attrib.get("Name") != "PouList":
            continue
        for child in element.iter():
            if child.attrib.get("Name") == "Name" and child.text:
                names.add(child.text.strip())
    return names


class ExecutionGraph:
    """Conservative task-to-unit reachability graph for one snapshot."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.task_roots = {}
        self.calls = defaultdict(set)
        self.call_sites = defaultdict(list)
        self.unresolved_calls = defaultdict(set)
        self._units = {}
        self._name_index = defaultdict(set)
        self._tasks_by_unit = defaultdict(set)
        self._build()

    def _build(self):
        for unit in self.snapshot.units:
            if unit.kind == K.UNKNOWN:
                continue
            self._units[_key(unit.qualified_name)] = unit
            self._name_index[_key(unit.qualified_name)].add(_key(unit.qualified_name))
            self._name_index[_short(unit.qualified_name)].add(_key(unit.qualified_name))

        for unit in self.snapshot.units:
            if unit.kind == K.TASK_CONFIG:
                self.task_roots[unit.qualified_name] = {
                    self._resolve_name(name) for name in _task_roots(unit)
                }
                self.task_roots[unit.qualified_name].discard(None)

        for unit in self.snapshot.units:
            if unit.kind in K.CALLABLE:
                self._collect_calls(unit)

        for task, roots in self.task_roots.items():
            queue = deque(roots)
            seen = set()
            while queue:
                current = queue.popleft()
                if current in seen:
                    continue
                seen.add(current)
                self._tasks_by_unit[current].add(task)
                for callee in sorted(self.calls.get(current, ())):
                    queue.append(callee)

    def _resolve_name(self, name):
        candidates = self._name_index.get(_key(name), set())
        return next(iter(candidates)) if len(candidates) == 1 else None

    def _resolve_type(self, name):
        resolved = self._resolve_name(name)
        if resolved is not None:
            return resolved
        candidates = self._name_index.get(_short(name), set())
        return next(iter(candidates)) if len(candidates) == 1 else None

    def _collect_calls(self, unit):
        section = body(unit)
        if not section:
            return
        caller = _key(unit.qualified_name)

        def add_call(callee, match):
            if callee is None:
                return
            self.calls[caller].add(callee)
            self.call_sites[caller].append(
                (
                    callee,
                    section.at(match.start()),
                    match.group(0),
                )
            )

        local_types = {
            _key(member.get("name")): member.get("type", "").strip()
            for member in all_members(unit)
            if member.get("name") and member.get("type")
        }
        method_spans = set()
        for match in _METHOD_CALL.finditer(section.text):
            method_spans.add(match.start("method"))
            instance = _key(match.group("instance"))
            method = match.group("method")
            type_name = local_types.get(instance)
            callee = None
            if type_name:
                fb_type = self._resolve_type(type_name)
                if fb_type is not None:
                    add_call(fb_type, match)
                callee = self._resolve_name(f"{type_name}.{method}")
            if callee is None:
                self.unresolved_calls[caller].add(f"{match.group('instance')}.{method}")
            else:
                add_call(callee, match)

        for match in _BARE_CALL.finditer(section.text):
            if match.start() in method_spans:
                continue
            name = match.group("name")
            if name.upper() in _NON_CALLS:
                continue
            type_name = local_types.get(_key(name))
            callee = self._resolve_type(type_name) if type_name else self._resolve_name(name)
            if callee is None:
                if is_known_function(name) or is_known_function_block(name):
                    continue
                if type_name and is_known_function_block(type_name):
                    continue
                self.unresolved_calls[caller].add(name)
            else:
                add_call(callee, match)

    def tasks_for(self, unit_name):
        """Return task names that can reach *unit_name*."""
        return frozenset(self._tasks_by_unit.get(_key(unit_name), ()))

    def reachable_from(self, task_name):
        """Return canonical unit names reachable from one task."""
        task = next((name for name in self.task_roots if _key(name) == _key(task_name)), None)
        if task is None:
            return frozenset()
        return frozenset(
            unit for unit, tasks in self._tasks_by_unit.items() if task in tasks
        )
