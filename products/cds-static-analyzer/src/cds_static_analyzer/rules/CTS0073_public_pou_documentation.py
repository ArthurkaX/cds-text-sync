"""CTS0073 - public POU and interface declarations need documentation."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blanking import comment_spans
from cds_static_analyzer.st.body import declaration

_PUBLIC_HEADER = re.compile(
    r"^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+(?P<name>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)
_ATTRIBUTE = re.compile(r"^\s*\{.*\}\s*$")
_INTERFACE_SCOPES = {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT"}


def _line_ranges(text):
    ranges = []
    offset = 0
    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        ranges.append((offset, end, line.rstrip("\r\n")))
        offset = end
    if not ranges and text:
        ranges.append((0, len(text), text))
    return ranges


def _comment_map(text):
    spans = comment_spans(text)

    def overlaps(start, end):
        return any(span_start < end and span_end > start for span_start, span_end, _ in spans)

    def comment_only(start, end, line):
        if not overlaps(start, end):
            return False
        covered = list(line)
        for span_start, span_end, _content in spans:
            left = max(start, span_start) - start
            right = min(end, span_end) - start
            if left < right:
                for index in range(max(0, left), min(len(covered), right)):
                    covered[index] = " "
        return not "".join(covered).strip()

    return overlaps, comment_only


def _has_preceding_comment(lines, ranges, index, comment_only):
    cursor = index - 1
    while cursor >= 0:
        start, end, line = ranges[cursor]
        stripped = line.strip()
        if not stripped or _ATTRIBUTE.fullmatch(stripped):
            cursor -= 1
            continue
        return comment_only(start, end, line)
    return False


def _member_offset(section, lines, member):
    line_number = member.get("line", 0)
    index = line_number - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index][2].find(member["name"])
    if position < 0:
        return None
    return section.at(lines[index][0] + position)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    section = declaration(unit)
    if not section or not unit.declaration:
        return

    raw = unit.declaration
    ranges = _line_ranges(raw)
    overlaps, comment_only = _comment_map(raw)
    lines = [line for _start, _end, line in ranges]

    if unit.kind in {"program", "function_block", "function"}:
        header_match = next(
            (
                (index, match)
                for index, line in enumerate(lines)
                for match in [_PUBLIC_HEADER.match(line)]
                if match
            ),
            (None, None),
        )
        header_index, header = header_match
        if header_index is not None:
            start, end, line = ranges[header_index]
            if not _has_preceding_comment(lines, ranges, header_index, comment_only):
                yield finding_in(
                    message=(
                        f"public POU '{header.group('name')}' has no documentation comment"
                    ),
                    unit=unit,
                    offset=section.at(start + len(line) - len(line.lstrip())),
                    end_offset=section.at(start + len(line)),
                    anchor=header.group("name"),
                    context=line.strip(),
                )

    for member in decl.all_members(unit):
        if (member.get("scope") or "").upper() not in _INTERFACE_SCOPES:
            continue
        index = member.get("line", 0) - 1
        if not 0 <= index < len(ranges):
            continue
        start, end, line = ranges[index]
        inline_comment = overlaps(start, end)
        preceding_comment = _has_preceding_comment(lines, ranges, index, comment_only)
        if inline_comment or preceding_comment:
            continue
        offset = _member_offset(section, ranges, member)
        yield finding_in(
            message=(
                f"interface parameter '{member.get('name', '')}' has no "
                "documentation comment"
            ),
            unit=unit,
            offset=offset,
            anchor=member.get("name"),
            context=f"{member.get('name', '')} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0073",
    title="Missing public POU documentation",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds=["program", "function_block", "function"],
    summary="Public POUs and interface parameters should explain their contract.",
    topic="Code quality",
    check=check,
)
