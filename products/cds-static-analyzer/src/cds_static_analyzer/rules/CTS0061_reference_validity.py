"""CTS0061 - reference member access without __ISVALIDREF validation."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_ACCESS = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*\.\s*(?P<member>[A-Za-z_]\w*)",
    re.IGNORECASE,
)
_VALID_GUARD = re.compile(
    r"^\s*(?:IF|ELSIF)\s*(?:\(\s*)?(?P<negative>NOT\s+)?"
    r"__ISVALIDREF\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*(?:\))?\s*$",
    re.IGNORECASE,
)
_INVALID_GUARD = re.compile(
    r"\bIF\s+NOT\s+__ISVALIDREF\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)"
    r"\s+THEN(?P<body>.*?)\bEND_IF\b",
    re.IGNORECASE | re.DOTALL,
)
_TERMINAL = re.compile(r"\bRETURN\b", re.IGNORECASE)


def _walk(node):
    for child in node.children:
        yield child
        yield from _walk(child)


def _reference_names(unit):
    return {
        member["name"].casefold()
        for member in decl.all_members(unit)
        if classify_type(member.get("type", "")).get("base", "").upper() == "REFERENCE"
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
            match = _VALID_GUARD.fullmatch(label)
            if match and match.group("name").casefold() == name.casefold():
                states.append(("invalid" if match.group("negative") else "valid", start))
            elif label.strip().upper() == "ELSE":
                for previous in branches[:index]:
                    match = _VALID_GUARD.fullmatch(previous[0])
                    if match and match.group("name").casefold() == name.casefold():
                        states.append(("valid" if match.group("negative") else "invalid", start))
            break
    return states


def _guard_clause_exits(text, name, before):
    for match in _INVALID_GUARD.finditer(text, 0, before):
        if match.group("name").casefold() != name.casefold():
            continue
        if _TERMINAL.search(match.group("body")):
            return True
    return False


def _safe(root, section, name, absolute):
    local = absolute - section.base
    if any(state == "valid" for state, _ in _branch_states(root, absolute, name)):
        return True
    return _guard_clause_exits(section.text, name, local)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return
    references = _reference_names(unit)
    if not references:
        return
    root = tree(unit)
    for match in _ACCESS.finditer(section.text):
        name = match.group("name")
        if name.casefold() not in references:
            continue
        absolute = section.at(match.start("name"))
        if _safe(root, section, name, absolute):
            continue
        expression = match.group(0).strip()
        yield finding_in(
            message=(
                f"reference '{name}' is used without a dominating "
                "__ISVALIDREF check"
            ),
            unit=unit,
            offset=absolute,
            end_offset=section.at(match.end()),
            anchor=expression,
            context=expression,
        )


RULE = RuleSpec(
    id="CTS0061",
    title="Unchecked reference use",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="A REFERENCE is used without a simple dominating __ISVALIDREF check.",
    topic="Correctness",
    check=check,
)
