"""fsm_plantuml.py - Render a Machine as a PlantUML state diagram.

Pure rendering: consumes :class:`Machine` objects and never looks at source
text or re-scans. IronPython-safe.
"""

from __future__ import print_function

from .fsm_mermaid import sanitize_guard


def to_plantuml(machine, title=None):
    """Return a PlantUML state-diagram block for *machine*."""
    lines = ["@startuml"]
    if title:
        lines.append("title {0}".format(sanitize_guard(title)))
    if machine.deferred:
        lines.append(
            "' transitions write the next-state variable; they take effect "
            "on the following scan"
        )

    index = {}
    for order, state in enumerate(machine.states):
        index[state.label] = "s{0}".format(order)
        lines.append('state "{0}" as s{1}'.format(sanitize_guard(state.label), order))

    if any(t.source is None for t in machine.transitions):
        lines.append('state "(any state)" as ANY')

    for t in sorted(machine.transitions, key=lambda t: t.offset):
        src = index.get(t.source) if t.source is not None else "ANY"
        dst = index.get(t.target, "s0")
        guard = sanitize_guard(t.guard)
        if guard:
            lines.append("{0} --> {1} : {2}".format(src, dst, guard))
        else:
            lines.append("{0} --> {1}".format(src, dst))

    lines.append("@enduml")

    return "\n".join(lines)
