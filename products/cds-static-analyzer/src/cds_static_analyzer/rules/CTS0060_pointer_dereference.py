"""CTS0060 - pointer dereference without a simple dominating null check."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_DEREFERENCE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\^", re.IGNORECASE)
_GUARD = re.compile(
    r"^\s*(?:IF|ELSIF)\s*(?:\(\s*)?(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<operator><>|=)\s*0\s*(?:\))?\s*$",
    re.IGNORECASE,
)
_ZERO_GUARD = re.compile(
    r"\bIF\s+(?P<name>[A-Za-z_]\w*)\s*=\s*0\s+THEN"
    r"(?P<body>.*?)\bEND_IF\b",
    re.IGNORECASE | re.DOTALL,
)
_TERMINAL = re.compile(r"\bRETURN\b", re.IGNORECASE)
def _walk(node):
    for child in node.children:
        yield child
        yield from _walk(child)


def _pointer_names(unit):
    return {
        member["name"].casefold()
        for member in decl.all_members(unit)
        if classify_type(member.get("type", "")).get("base", "").upper() == "POINTER"
    }


def _branch_states(root, offset, name):
    states = []
    for block in _walk(root):
        if block.kind != "IF" or block.end_offset is None:
            continue
        if not block.start_offset <= offset < block.end_offset:
            continue
        branches = block.branches
        for index, (label, start, end) in enumerate(branches):
            if not start <= offset < end:
                continue
            match = _GUARD.fullmatch(label)
            if match and match.group("name").casefold() == name.casefold():
                states.append(("nonzero" if match.group("operator") == "<>" else "zero", start))
            elif label.strip().upper() == "ELSE":
                for previous in branches[:index]:
                    match = _GUARD.fullmatch(previous[0])
                    if match and match.group("name").casefold() == name.casefold():
                        states.append(("zero" if match.group("operator") == "<>" else "nonzero", start))
            break
    return states


def _guard_clause_exits(text, name, before):
    for match in _ZERO_GUARD.finditer(text, 0, before):
        if match.group("name").casefold() != name.casefold():
            continue
        if not _TERMINAL.search(match.group("body")):
            continue
        if re.search(
            rf"\b{re.escape(name)}\s*:=", text[match.end() : before], re.IGNORECASE
        ):
            continue
        return True
    return False


def _safe(root, section, name, absolute):
    local = absolute - section.base
    for state, branch_start in _branch_states(root, absolute, name):
        if state == "nonzero" and not re.search(
            rf"\b{re.escape(name)}\s*:=", section.text[branch_start - section.base : local], re.IGNORECASE
        ):
            return True
    return _guard_clause_exits(section.text, name, local)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    pointers = _pointer_names(unit)
    if not pointers:
        return
    root = tree(unit)
    for match in _DEREFERENCE.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in pointers:
            continue
        absolute = section.at(match.start("name"))
        if _safe(root, section, name, absolute):
            continue
        expression = match.group(0).strip()
        yield finding_in(
            message=f"pointer '{name}' is dereferenced without a dominating non-null check",
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0060",
    title="Unchecked pointer dereference",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A pointer is dereferenced without a simple dominating null check.",
    topic="Correctness",
    check=check,
)
