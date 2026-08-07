"""CTS0071 - variables whose statically known size exceeds the limit."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import declaration
from cds_static_analyzer.st.declarations import classify_type

_LIMIT = 1024
_SCALAR_BYTES = {
    "BOOL": 1, "BIT": 1, "SINT": 1, "USINT": 1, "BYTE": 1, "CHAR": 1,
    "INT": 2, "UINT": 2, "WORD": 2, "WCHAR": 2, "DINT": 4, "UDINT": 4,
    "DWORD": 4, "REAL": 4, "TIME": 4, "LINT": 8, "ULINT": 8,
    "LWORD": 8, "LREAL": 8, "LTIME": 8,
}
_STRING = re.compile(r"^(?P<wide>WSTRING|STRING)\s*\(\s*(?P<size>\d+)\s*\)$", re.I)


def _type_size(type_name):
    text = (type_name or "").strip()
    string = _STRING.fullmatch(text)
    if string:
        size = int(string.group("size"))
        return size * (2 if string.group("wide").upper() == "WSTRING" else 1) + 2
    info = classify_type(text)
    if info["kind"] == "scalar":
        return _SCALAR_BYTES.get(info["base"])
    if info["kind"] != "array":
        return None
    element_size = _type_size(info["elem"])
    if element_size is None:
        return None
    count = 1
    for low, high in info["dims"]:
        try:
            count *= int(high, 0) - int(low, 0) + 1
        except ValueError:
            return None
    return count * element_size


def _member_offset(unit, member):
    section = declaration(unit)
    if not section or not unit.declaration:
        return None
    lines = unit.declaration.split("\n")
    index = member.get("line", 0) - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return section.at(sum(len(lines[i]) + 1 for i in range(index)) + position)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    for member in decl.all_members(unit):
        size = _type_size(member.get("type", ""))
        if size is None or size <= _LIMIT:
            continue
        name = member.get("name", "")
        yield finding_in(
            message=f"variable '{name}' has a statically known size of {size} bytes",
            unit=unit,
            offset=_member_offset(unit, member),
            anchor=name,
            context=f"{name} : {member.get('type', '')}",
        )


RULE = RuleSpec(
    id="CTS0071",
    title="Large variable",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="Variables with a statically known size above the configured limit need review.",
    topic="Code quality",
    check=check,
)
