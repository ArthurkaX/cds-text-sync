"""CTS0008 - table-like alignment of ST variable declarations."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.blanking import blank_noise

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
    # ``str.splitlines()`` also treats control characters such as U+0085 as
    # line boundaries.  They can occur in legacy-encoded comments exported by
    # a CODESYS-based IDE, while the ST source still has only LF line endings.
    # Keep the blanked text aligned with Section.lines(), which is LF-based.
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


def fix(text, finding):
    """Return *text* with the affected declaration group aligned.

    This fixer deliberately changes whitespace before the declaration colon
    only.  It uses the same section/group boundaries as :func:`check`, so a
    preview can never silently reformat an unrelated declaration block.
    """
    # Use the source newline convention, not every Unicode line-separator
    # character that may be present in a comment from a legacy export.
    raw_lines = text.split("\n")
    clean_lines = blank_noise(text).split("\n")
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

    def content(raw):
        return raw.rstrip("\r\n")

    def align_group(rows):
        if len(rows) < 2 or not target_lines.intersection(row[0] for row in rows):
            return
        expected_indent = rows[0][3].group("indent")
        # Keep one readable space before the colon, including for the longest
        # declaration in a group.
        expected_colon = max(row[5] for row in rows) + 1
        for line_no, index, raw, match, name_end, colon in rows:
            new_prefix = expected_indent + raw[len(match.group("indent")) : name_end]
            padding = max(1, expected_colon - len(new_prefix))
            replacement = new_prefix + (" " * padding) + raw[colon:]
            raw_lines[index] = replacement

    in_section = False
    group = []
    for index, clean_raw in enumerate(clean_lines):
        clean = content(clean_raw)
        stripped = clean.strip()
        if not in_section:
            if _SECTION_START.match(stripped):
                in_section = True
            continue
        if _SECTION_END.match(stripped):
            align_group(group)
            group = []
            in_section = False
            continue
        if not stripped:
            align_group(group)
            group = []
            continue
        match = _DECLARATION.match(clean)
        if match:
            colon = clean.find(":")
            group.append(
                (
                    index + 1,
                    index,
                    content(raw_lines[index]),
                    match,
                    match.end("names"),
                    colon,
                )
            )
        elif stripped.startswith(("//", "(*", "{", "(")):
            pass
        else:
            align_group(group)
            group = []
    align_group(group)
    return "\n".join(raw_lines)


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
