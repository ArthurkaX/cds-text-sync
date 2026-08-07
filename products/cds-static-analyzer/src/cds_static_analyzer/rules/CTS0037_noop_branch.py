"""CTS0037 - control-flow branch containing only a no-op statement."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.blanking import has_intentional_noop_comment
from cds_static_analyzer.st.body import body


_END_HEADER = re.compile(r"\bTHEN\b", re.IGNORECASE)


def _walk(block):
    for child in block.children:
        yield child
        yield from _walk(child)


def _content_start(label, text, start):
    """Return the local offset immediately after a branch header."""
    upper = label.strip().upper()
    if upper == "ELSE":
        match = re.match(r"\s*ELSE\b", text[start:], re.IGNORECASE)
        return start + (match.end() if match else 0)
    if upper.startswith(("IF ", "ELSIF ")):
        match = _END_HEADER.search(text, start)
        return match.end() if match else start
    # CASE labels end at their colon.
    colon = text.find(":", start)
    return colon + 1 if colon >= 0 else start


def check(unit, ctx):
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    text = section.text
    for block in _walk(tree(unit)):
        if block.kind not in ("IF", "CASE"):
            continue
        for label, absolute_start, absolute_end in block.branches:
            if absolute_end is None:
                continue
            start = absolute_start - section.base
            end = absolute_end - section.base
            content_start = _content_start(label, text, start)
            content = text[content_start:end]
            if content.strip() != ";":
                continue
            semicolon = text.find(";", content_start, end)
            if semicolon < 0:
                continue
            if has_intentional_noop_comment(section.raw, semicolon):
                continue
            absolute = section.at(semicolon)
            yield finding_in(
                message="branch contains only a no-op statement",
                unit=unit,
                offset=absolute,
                end_offset=absolute + 1,
                anchor=";",
                context=label.strip(),
            )


RULE = RuleSpec(
    id="CTS0037",
    title="No-op control-flow branch",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="An IF or CASE branch contains only a standalone no-op statement.",
    topic="Code quality",
    check=check,
)
