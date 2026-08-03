"""CTS0010 - IF/ELSE blocks that select between TRUE and FALSE."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body

_TOKEN = re.compile(r"\b(?P<token>IF|ELSE|ELSIF|END_IF)\b", re.IGNORECASE)
_THEN = re.compile(r"\bTHEN\b", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?P<target>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?)\s*:=\s*"
    r"(?P<value>TRUE|FALSE)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def _branch_assignment(branch):
    match = _ASSIGNMENT.fullmatch(branch.strip())
    if match is None:
        return None
    target = match.group("target").replace(" ", "")
    return target, target.lower(), match.group("value").upper()


def _blocks(text):
    """Yield non-nested IF/ELSE blocks without regex backtracking."""
    stack = []
    for token_match in _TOKEN.finditer(text):
        token = token_match.group("token").upper()
        if token == "IF":
            stack.append(
                {
                    "start": token_match.start(),
                    "if_end": token_match.end(),
                    "else": None,
                    "elsif": False,
                    "child": False,
                    "nested": bool(stack),
                }
            )
            continue
        if not stack:
            continue
        current = stack[-1]
        if token == "ELSE":
            current["else"] = token_match
        elif token == "ELSIF":
            current["elsif"] = True
        elif token == "END_IF":
            block = stack.pop()
            if stack:
                stack[-1]["child"] = True
            if block["nested"] or block["child"] or block["else"] is None or block["elsif"]:
                continue
            then = _THEN.search(text, block["if_end"])
            if then is None or then.start() > block["else"].start():
                continue
            yield {
                "start": block["start"],
                "end": token_match.end(),
                "condition": text[block["if_end"] : then.start()],
                "then": text[then.end() : block["else"].start()],
                "else": text[block["else"].end() : token_match.start()],
            }


def check(unit, ctx):
    """Report boolean IF/ELSE assignments that can be one expression."""
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    clean = section.text
    for block in _blocks(clean):
        then_assignment = _branch_assignment(block["then"])
        else_assignment = _branch_assignment(block["else"])
        if then_assignment is None or else_assignment is None:
            continue
        then_display, then_target, then_value = then_assignment
        else_display, else_target, else_value = else_assignment
        if then_target != else_target or then_value == else_value:
            continue

        condition = " ".join(block["condition"].split())
        expression = condition if then_value == "TRUE" else f"NOT ({condition})"
        yield finding_in(
            message=(
                f"boolean IF/ELSE assignment to '{then_display}' can be simplified "
                f"to '{then_display} := {expression};'"
            ),
            unit=unit,
            offset=section.at(block["start"]),
            end_offset=section.at(block["end"]),
            anchor=then_display,
            context=clean[block["start"] : block["end"]].strip(),
        )


RULE = RuleSpec(
    id="CTS0010",
    title="Redundant boolean IF",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Boolean IF/ELSE assignments that can be written as one expression.",
    topic="Style",
    check=check,
)
