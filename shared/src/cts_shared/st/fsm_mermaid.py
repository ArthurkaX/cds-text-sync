"""fsm_mermaid.py - Render a Machine as a mermaid ``stateDiagram-v2``.

Pure rendering: consumes :class:`Machine` objects and never looks at source
text or re-scans. IronPython-safe.
"""

from __future__ import print_function

import re

_WS = re.compile(r"\s+")
_SANITIZE = re.compile(r"[:;#\"\n]")


def _sanitize_guard(guard):
    text = _WS.sub(" ", guard or "").strip()
    text = _SANITIZE.sub(" ", text)
    if len(text) > 60:
        text = text[:60].rstrip() + "..."
    return text


def to_mermaid(machine, title=None):
    """Return a mermaid ``stateDiagram-v2`` block for *machine*."""
    lines = ["stateDiagram-v2"]
    if title:
        lines.append("    title: {0}".format(title))
    if machine.deferred:
        lines.append(
            "    %% transitions write the next-state variable; they take effect "
            "on the following scan"
        )

    index = {}
    for order, state in enumerate(machine.states):
        index[state.label] = "s{0}".format(order)
        lines.append("    s{0} : {1}".format(order, state.label))

    if any(t.source is None for t in machine.transitions):
        lines.append("    ANY : (any state)")

    for t in sorted(machine.transitions, key=lambda t: t.offset):
        src = index.get(t.source) if t.source is not None else "ANY"
        dst = index.get(t.target, "s0")
        guard = _sanitize_guard(t.guard)
        if guard:
            lines.append("    {0} --> {1} : {2}".format(src, dst, guard))
        else:
            lines.append("    {0} --> {1}".format(src, dst))

    return "\n".join(lines)
