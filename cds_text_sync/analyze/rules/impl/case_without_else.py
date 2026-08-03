"""CTS0003: CASE statements must define a fallback branch."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise, trim_strings
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0003"
SEVERITY = "suspicious"

_TOKEN_RE = re.compile(
    r"\b(?:CASE|END_CASE|IF|END_IF|FOR|END_FOR|WHILE|END_WHILE|REPEAT|END_REPEAT|ELSE)\b",
    re.IGNORECASE,
)


def _missing_else(implementation):
    """Return offsets of CASE tokens whose matching block has no ELSE.

    A small block tracker keeps ELSE branches belonging to nested IF/CASE
    constructs from being attributed to the outer CASE.
    """
    clean = trim_strings(blank_noise(implementation or ""))
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
    body = unit.implementation if unit.implementation is not None else unit.text
    if not body:
        return
    impl_start = next((span.start_offset for span in unit.source_spans if span.role == "implementation"), 0)
    for offset in _missing_else(body):
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message="CASE statement has no ELSE branch for unexpected values",
            unit=unit,
            offset=impl_start + offset,
            anchor="CASE",
            context="CASE without ELSE",
            rule_title="CASE without ELSE",
        )
