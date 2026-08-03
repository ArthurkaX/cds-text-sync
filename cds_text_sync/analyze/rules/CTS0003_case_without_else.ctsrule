"""CTS0003 - CASE statements must define a fallback branch."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body

_TOKEN_RE = re.compile(
    r"\b(?:CASE|END_CASE|IF|END_IF|FOR|END_FOR|WHILE|END_WHILE|REPEAT|END_REPEAT|ELSE)\b",
    re.IGNORECASE,
)


def _missing_else(clean):
    """Return local offsets of CASE tokens whose matching block has no ELSE.

    A small block tracker keeps ELSE branches belonging to nested IF/CASE
    constructs from being attributed to the outer CASE.
    """
    stack = []
    missing = []
    for match in _TOKEN_RE.finditer(clean):
        token = match.group(0).upper()
        if token in {"CASE", "IF", "FOR", "WHILE", "REPEAT"}:
            stack.append({"kind": token, "offset": match.start(), "has_else": False})
        elif token == "ELSE":
            if stack and stack[-1]["kind"] in {"CASE", "IF"}:
                stack[-1]["has_else"] = True
        elif token.startswith("END_"):
            kind = token[4:]
            for index in range(len(stack) - 1, -1, -1):
                if stack[index]["kind"] == kind:
                    block = stack.pop(index)
                    if kind == "CASE" and not block["has_else"]:
                        missing.append(block["offset"])
                    break
    return missing


def check(unit, ctx):
    """Flag CASE blocks that do not explicitly handle other values."""
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    for offset in _missing_else(section.text):
        yield finding_in(
            message="CASE statement has no ELSE branch for unexpected values",
            unit=unit,
            offset=section.at(offset),
            anchor="CASE",
            context="CASE without ELSE",
        )


RULE = RuleSpec(
    id="CTS0003",
    title="CASE without ELSE",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="CASE statements must explicitly handle unexpected values.",
    topic="Correctness",
    check=check,
)
