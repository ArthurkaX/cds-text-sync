"""CTS0023 - standalone or duplicated empty statements."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_STANDALONE = re.compile(r"(?m)^[ \t]*;[ \t]*(?:\r?$)")
_DUPLICATE = re.compile(r";[ \t]*;")


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    reported = set()
    for match in _STANDALONE.finditer(section.text):
        absolute = section.at(match.start() + match.group().find(";"))
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
