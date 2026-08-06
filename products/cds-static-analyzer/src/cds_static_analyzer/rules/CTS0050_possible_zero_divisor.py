"""CTS0050 - division by a variable without a simple non-zero guard."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_DIVISION = re.compile(
    r"/\s*(?P<name>[A-Za-z_]\w*)\b(?!\s*#)", re.IGNORECASE
)
_GUARD = re.compile(
    r"^\s*(?:IF|ELSIF)\s*\(?\s*"
    r"(?P<name>[A-Za-z_]\w*)\s*(?P<operator><>|<=|>=|=|<|>)\s*"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\)?\s*$",
    re.IGNORECASE,
)
_GUARD_EXIT = re.compile(
    r"\bIF\s+(?P<name>[A-Za-z_]\w*)\s*=\s*0\s+THEN"
    r"(?P<body>.*?)\bEND_IF\b",
    re.IGNORECASE | re.DOTALL,
)
_TERMINAL = re.compile(r"\b(?:RETURN|EXIT|CONTINUE)\b", re.IGNORECASE)


def _walk(node):
    for child in node.children:
        yield child
        yield from _walk(child)


def _simple_guard(label):
    match = _GUARD.fullmatch(label)
    if match is None:
        return None
    try:
        value = float(match.group("value"))
    except ValueError:
        return None
    name = match.group("name").casefold()
    operator = match.group("operator")
    if operator == "<>" and value == 0:
        return name, "nonzero"
    if operator == "=" and value == 0:
        return name, "zero"
    if operator == ">" and value >= 0:
        return name, "nonzero"
    if operator == "<" and value <= 0:
        return name, "nonzero"
    if operator == ">=" and value > 0:
        return name, "nonzero"
    if operator == "<=" and value < 0:
        return name, "nonzero"
    return None


def _branch_guards(root, offset):
    """Return simple guards active at an absolute source offset."""
    guards = []
    for block in _walk(root):
        if block.kind != "IF" or block.end_offset is None:
            continue
        if not block.start_offset <= offset < block.end_offset:
            continue
        branches = block.branches
        for index, (label, start, end) in enumerate(branches):
            if not start <= offset < end:
                continue
            if label.strip().upper() == "ELSE":
                prior = [_simple_guard(item[0]) for item in branches[:index]]
                prior = [guard for guard in prior if guard is not None]
                if len(prior) == 1:
                    name, state = prior[0]
                    guards.append((name, "nonzero" if state == "zero" else "zero"))
            else:
                guard = _simple_guard(label)
                if guard is not None:
                    guards.append(guard)
            break
    return guards


def _guard_clause_exits(section_text, divisor, before_offset):
    for match in _GUARD_EXIT.finditer(section_text, 0, before_offset):
        if match.group("name").casefold() != divisor.casefold():
            continue
        if not _TERMINAL.search(match.group("body")):
            continue
        between = section_text[match.end() : before_offset]
        if re.search(rf"\b{re.escape(divisor)}\s*:=", between, re.IGNORECASE):
            continue
        return True
    return False


def _safe_for_divisor(root, section, divisor, offset):
    guards = _branch_guards(root, offset)
    states = [state for name, state in guards if name == divisor.casefold()]
    if "zero" in states:
        return "zero"
    if "nonzero" in states:
        return "nonzero"
    if _guard_clause_exits(section.text, divisor, offset - section.base):
        return "nonzero"
    return None


def check(unit, ctx):
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    root = tree(unit)

    for match in _DIVISION.finditer(section.text):
        divisor = match.group("name")
        absolute = section.at(match.start("name"))
        state = _safe_for_divisor(root, section, divisor, absolute)
        if state == "nonzero":
            continue
        if state == "zero":
            message = (
                f"division by '{divisor}' occurs on a branch where the divisor "
                "is proven to be zero"
            )
        else:
            message = (
                f"division by '{divisor}' is not protected by a simple non-zero "
                "check on this path"
            )
        yield finding_in(
            message=message,
            unit=unit,
            offset=absolute,
            end_offset=absolute + len(divisor),
            anchor=divisor,
            context=match.group(0).strip(),
        )


RULE = RuleSpec(
    id="CTS0050",
    title="Possible zero divisor",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A variable divisor is not protected by a simple non-zero path check.",
    topic="Correctness",
    check=check,
)
