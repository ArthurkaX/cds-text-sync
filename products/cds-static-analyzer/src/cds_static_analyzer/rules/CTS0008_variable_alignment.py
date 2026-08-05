"""CTS0008 - table-like alignment of ST variable declarations."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import declaration

_SECTION_START = re.compile(r"^VAR(?:_INPUT|_OUTPUT|_IN_OUT|_TEMP|_GLOBAL)?\b", re.I)
_SECTION_END = re.compile(r"^END_VAR\b", re.I)
_DECLARATION = re.compile(
    r"^(?P<indent>[ \t]*)(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*:\s*(?P<type>.+?);\s*$"
)


def _width(value):
    return len(value.expandtabs(1))


def check(unit, ctx):
    """Report non-tabular declaration indentation/alignment.

    A blank line starts a new alignment group. Comments and attributes do not
    become table rows, but they also do not force a new group.
    """
    ctx.capability(Capability.ST_TEXT)
    section = declaration(unit)
    if not section:
        return

    # Blanking is 1:1, so line N of the blanked text is line N of the raw
    # text with comments and string contents already removed.
    clean_lines = section.text.splitlines()
    group = []
    in_section = False

    def emit(rows):
        if len(rows) < 2:
            return
        expected_indent = rows[0][2]
        expected_colon = max(row[3] for row in rows)
        for line_start, line, indent, colon, name in rows:
            problems = []
            if _width(indent) != _width(expected_indent):
                problems.append("base indentation differs from the declaration group")
            if colon != expected_colon:
                problems.append("the ':' is not aligned with the declaration group")
            if not problems:
                continue
            yield finding_in(
                message="variable declaration is not aligned: " + "; ".join(problems),
                unit=unit,
                offset=line_start,
                end_offset=line_start + len(indent) + len(name),
                anchor=f"column:{expected_colon}",
                context=line.strip(),
            )

    for lineno, line_start, line in section.lines():
        clean = clean_lines[lineno - 1]
        stripped = clean.strip()
        if not in_section:
            if _SECTION_START.match(stripped):
                in_section = True
            continue
        if _SECTION_END.match(stripped):
            yield from emit(group)
            group = []
            in_section = False
            continue
        if not stripped:
            yield from emit(group)
            group = []
            continue
        match = _DECLARATION.match(clean)
        if match:
            indent = match.group("indent")
            name = match.group("names")
            # Use the actual colon position, including spacing after the
            # identifier. ``names`` intentionally excludes that spacing.
            colon = clean.find(":")
            group.append((line_start, line, indent, colon, name))
        elif stripped.startswith(("//", "(*", "{", "(")):
            pass
        else:
            yield from emit(group)
            group = []

    yield from emit(group)


RULE = RuleSpec(
    id="CTS0008",
    title="Variable declaration alignment",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="ANY",
    summary="Variable declarations in one group should form a readable aligned table.",
    topic="Style",
    check=check,
)
