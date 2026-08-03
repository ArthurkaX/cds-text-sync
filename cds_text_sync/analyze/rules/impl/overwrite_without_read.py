"""CTS0012: sequential assignments that overwrite an unread value."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise, trim_strings
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0012"
SEVERITY = "suspicious"

_SIMPLE_ASSIGNMENT = re.compile(
    r"(?s)^\s*(?P<name>[A-Za-z_]\w*)\s*:=\s*(?P<expression>.+?)\s*$"
)


def _simple_statements(text):
    """Yield ``(offset, statement)`` for semicolon-terminated statements."""
    start = 0
    for match in re.finditer(r";", text):
        raw = text[start : match.end()]
        leading = len(raw) - len(raw.lstrip())
        statement = raw.strip()
        if statement:
            yield start + leading, statement[:-1]
        start = match.end()


def check(unit, ctx):
    """Report a simple assignment immediately overwritten by another one."""
    ctx.capability(Capability.ST_TEXT)
    body = unit.implementation
    if not body:
        return

    clean = trim_strings(blank_noise(body))
    impl_start = next(
        (span.start_offset for span in unit.source_spans if span.role == "implementation"),
        0,
    )
    previous = None
    for offset, statement in _simple_statements(clean):
        match = _SIMPLE_ASSIGNMENT.fullmatch(statement)
        if not match:
            previous = None
            continue
        name = match.group("name")
        expression = match.group("expression")
        reads_previous = re.search(
            rf"(?<![A-Za-z0-9_.^]){re.escape(name)}(?![A-Za-z0-9_])",
            expression,
            re.IGNORECASE,
        )
        if (
            previous is not None
            and previous["name"].lower() == name.lower()
            and not reads_previous
        ):
            old = previous
            yield finding_in(
                rule_id=RULE_ID,
                severity=SEVERITY,
                message=(
                    f"assignment to '{old['name']}' is overwritten before the value is read"
                ),
                unit=unit,
                offset=impl_start + old["offset"],
                end_offset=impl_start + old["offset"] + len(old["name"]),
                anchor=old["name"],
                context=old["statement"],
                rule_title="Overwrite without read",
            )
        previous = {"name": name, "offset": offset, "statement": statement}
