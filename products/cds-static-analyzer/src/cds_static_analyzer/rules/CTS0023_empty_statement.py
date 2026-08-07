"""CTS0023 - standalone or duplicated empty statements."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.blanking import (
    comment_spans,
    has_intentional_noop_comment,
)

_STANDALONE = re.compile(r"(?m)^[ \t]*;[ \t]*(?:\r?$)")
_DUPLICATE = re.compile(r";[ \t]*;")
_EMPTY_BLOCK_HEADER = re.compile(
    r"^(?:IF\b.*\bTHEN\b|ELSIF\b.*\bTHEN\b|ELSE\b|"
    r"CASE\b.*\bOF\b|FOR\b.*\bDO\b|WHILE\b.*\bDO\b|REPEAT\b)",
    re.IGNORECASE,
)


def _is_empty_statement(position, text):
    """Return whether a standalone semicolon is actually empty.

    A terminator is valid on its own line after a multiline expression or a
    block closer.  It is still an empty statement after an IF/CASE branch
    header, so that common placeholder remains diagnosable.
    """
    before = text[:position]
    previous = next(
        (line.strip() for line in reversed(before.splitlines()) if line.strip()),
        "",
    )
    since_semicolon = before[before.rfind(";") + 1 :]
    if not since_semicolon.strip():
        return True
    if _EMPTY_BLOCK_HEADER.match(previous) or previous.endswith(":"):
        return True
    return False


def _has_comment_on_line(position, raw_text):
    """Return whether the source line explicitly documents this semicolon."""
    line_start = raw_text.rfind("\n", 0, position) + 1
    line_end = raw_text.find("\n", position)
    if line_end < 0:
        line_end = len(raw_text)
    return any(
        start < line_end and end > line_start
        for start, end, _content in comment_spans(raw_text)
    )


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    reported = set()
    for match in _STANDALONE.finditer(section.text):
        absolute = section.at(match.start() + match.group().find(";"))
        if _has_comment_on_line(match.start(), section.raw):
            continue
        if has_intentional_noop_comment(section.raw, match.start()):
            continue
        if not _is_empty_statement(match.start(), section.text):
            continue
        reported.add(absolute)
        yield finding_in(
            message="standalone empty statement has no effect",
            unit=unit,
            offset=absolute,
            end_offset=absolute + 1,
            anchor=";",
            context=";",
        )

    for match in _DUPLICATE.finditer(section.text):
        second = match.start() + match.group().rfind(";")
        absolute = section.at(second)
        if absolute in reported:
            continue
        yield finding_in(
            message="duplicate semicolon creates an empty statement",
            unit=unit,
            offset=absolute,
            end_offset=absolute + 1,
            anchor=";",
            context=match.group(),
        )


RULE = RuleSpec(
    id="CTS0023",
    title="Empty statement",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Standalone or duplicated semicolons that produce empty statements.",
    topic="Style",
    check=check,
    merge="identical",
    options={"merge": True},
)
