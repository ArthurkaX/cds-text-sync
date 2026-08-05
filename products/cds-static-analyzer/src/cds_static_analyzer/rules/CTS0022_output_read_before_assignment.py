"""CTS0022 - VAR_OUTPUT values read before being assigned."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z_]\w*)(?![A-Za-z0-9_])")
_WRITE_AFTER = re.compile(r"\s*:=" )
_CALL_OUTPUT_BEFORE = re.compile(r"=>\s*$")
_CALLABLE_KINDS = {"function", "method", "action", "property_get", "property_set"}


def _is_qualified(text, match):
    before = text[: match.start()].rstrip()
    after = text[match.end() :].lstrip()
    return before.endswith((".", "^")) or after.startswith((".", "["))


def check(unit, ctx):
    if unit.kind not in _CALLABLE_KINDS:
        return
    declarations = ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    outputs = declarations.output_members(unit)
    for member in outputs:
        name = member.get("name", "")
        if not name:
            continue
        for match in _IDENTIFIER.finditer(section.text):
            if match.group("name").casefold() != name.casefold():
                continue
            if _is_qualified(section.text, match):
                continue
            before = section.text[: match.start()]
            after = section.text[match.end() :]
            # In ``label => output`` the left identifier is a call label,
            # not a read of the output with the same name.
            if re.match(r"\s*=>", after):
                continue
            if _WRITE_AFTER.match(after):
                break
            if _CALL_OUTPUT_BEFORE.search(before):
                break
            if re.search(r"\bADR\s*\(\s*$", before, re.IGNORECASE):
                break
            offset = section.at(match.start())
            yield finding_in(
                message=f"output '{name}' is read before its first assignment",
                unit=unit,
                offset=offset,
                end_offset=offset + len(name),
                anchor=name,
                context=name,
            )
            break


RULE = RuleSpec(
    id="CTS0022",
    title="Output read before assignment",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="VAR_OUTPUT values read before the callable assigns them.",
    topic="Correctness",
    check=check,
)
