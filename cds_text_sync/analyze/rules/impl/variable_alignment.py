"""CTS0008: table-like alignment of ST variable declarations."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0008"
SEVERITY = "style"

_SECTION_START = re.compile(r"^VAR(?:_INPUT|_OUTPUT|_IN_OUT|_TEMP|_GLOBAL)?\b", re.I)
_SECTION_END = re.compile(r"^END_VAR\b", re.I)
_DECLARATION = re.compile(
    r"^(?P<indent>[ \t]*)(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*:\s*(?P<type>.+?);\s*$"
)


def _width(value):
    return len(value.expandtabs(1))


def _declaration(line):
    clean = blank_noise(line)
    return _DECLARATION.match(clean)


def check(unit, ctx):
    """Report non-tabular declaration indentation/alignment.

    A blank line starts a new alignment group. Comments and attributes do not
    become table rows, but they also do not force a new group.
    """
    ctx.capability(Capability.ST_TEXT)
    text = unit.declaration
    if not text:
        return

    decl_start = next(
        (span.start_offset for span in unit.source_spans if span.role == "declaration"),
        0,
    )
    group = []
    offset = 0
    in_section = False

    def emit(rows):
        if len(rows) < 2:
            return
        expected_indent = rows[0][2]
        expected_colon = max(row[3] for row in rows)
        for line_no, line, indent, colon, name in rows:
            problems = []
            if _width(indent) != _width(expected_indent):
                problems.append("base indentation differs from the declaration group")
            if colon != expected_colon:
                problems.append("the ':' is not aligned with the declaration group")
            if not problems:
                continue
            yield finding_in(
                rule_id=RULE_ID,
                severity=SEVERITY,
                message="variable declaration is not aligned: " + "; ".join(problems),
                unit=unit,
                offset=decl_start + line_no,
                end_offset=decl_start + line_no + len(indent) + len(name),
                anchor=f"column:{expected_colon}",
                context=line.strip(),
                rule_title="Variable declaration alignment",
            )

    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        stripped = blank_noise(line).strip()
        if not in_section:
            if _SECTION_START.match(stripped):
                in_section = True
            offset += len(raw_line)
            continue
        if _SECTION_END.match(stripped):
            yield from emit(group)
            group = []
            in_section = False
            offset += len(raw_line)
            continue
        if not stripped:
            yield from emit(group)
            group = []
            offset += len(raw_line)
            continue
        match = _declaration(line)
        if match:
            indent = match.group("indent")
            name = match.group("names")
            # Use the actual colon position, including spacing after the
            # identifier. ``names`` intentionally excludes that spacing.
            colon = blank_noise(line).find(":")
            group.append((offset, line, indent, colon, name))
        elif stripped.startswith(("//", "(*", "{", "(")):
            pass
        else:
            yield from emit(group)
            group = []
        offset += len(raw_line)

    yield from emit(group)
