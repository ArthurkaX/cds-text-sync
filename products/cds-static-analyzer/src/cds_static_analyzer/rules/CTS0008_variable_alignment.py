"""CTS0008 - table-like alignment of ST variable declarations."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import declaration
from cts_shared.st.blanking import blank_noise
from cts_shared.st.formatting import format_declarations

_SECTION_START = re.compile(r"^VAR(?:_INPUT|_OUTPUT|_IN_OUT|_TEMP|_GLOBAL)?\b", re.I)
_SECTION_END = re.compile(r"^END_VAR\b", re.I)
_DECLARATION = re.compile(
    r"^(?P<indent>[ \t]*)(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*:\s*(?P<type>.+?);\s*$"
)


def _width(value):
    return len(value.expandtabs(1))


def check(unit, ctx):
    """Report non-tabular declaration indentation/alignment."""
    ctx.capability(Capability.ST_TEXT)
    section = declaration(unit)
    if not section:
        return

    clean_lines = section.text.split("\n")
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
            if problems:
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
            group.append((line_start, line, indent, clean.find(":"), name))
        elif stripped.startswith(("//", "(*", "{", "(")):
            continue
        else:
            yield from emit(group)
            group = []
    yield from emit(group)


def fix(text, finding):
    """Align the declaration group containing the reported source line(s)."""
    target_lines = set()
    location = finding.get("location") if isinstance(finding, dict) else None
    if isinstance(location, dict) and location.get("line") is not None:
        target_lines.add(int(location["line"]))
    for value in (finding.get("member_lines", []) if isinstance(finding, dict) else []):
        try:
            target_lines.add(int(value))
        except (TypeError, ValueError):
            continue
    if not target_lines:
        return text
    return format_declarations(text, target_lines=target_lines)


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
    merge="adjacent",
    options={"merge": True},
    fix=fix,
)
