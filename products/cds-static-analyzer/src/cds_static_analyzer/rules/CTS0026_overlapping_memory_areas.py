"""CTS0026 - explicit AT declarations overlap in memory."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import declaration


_AT_DECL = re.compile(
    r"^\s*(?P<name>[A-Za-z_]\w*)\s+AT\s+%"
    r"(?P<area>[IQM])(?P<width>[XB WDL])(?P<byte>\d+)"
    r"(?:\.(?P<bit>\d+))?\s*:\s*(?P<type>[A-Za-z_]\w*)\s*;",
    re.IGNORECASE | re.MULTILINE,
)

_TYPE_BITS = {
    "BOOL": 1,
    "BYTE": 8,
    "SINT": 8,
    "USINT": 8,
    "WORD": 16,
    "INT": 16,
    "UINT": 16,
    "DWORD": 32,
    "DINT": 32,
    "UDINT": 32,
    "REAL": 32,
    "LWORD": 64,
    "LINT": 64,
    "ULINT": 64,
    "LREAL": 64,
}
_ADDRESS_BITS = {"X": 1, "B": 8, "W": 16, "D": 32, "L": 64}


def _declarations(ctx):
    for unit in ctx.units:
        section = declaration(unit)
        if not section:
            continue
        for match in _AT_DECL.finditer(section.text):
            area = match.group("area").upper()
            width = match.group("width").replace(" ", "").upper()
            bit = match.group("bit")
            if width == "X" and bit is None:
                continue
            if width != "X" and bit is not None:
                continue
            if bit is not None and int(bit) > 7:
                continue
            type_bits = _TYPE_BITS.get(match.group("type").upper())
            if type_bits is None:
                continue
            start = int(match.group("byte")) * _ADDRESS_BITS[width]
            if bit is not None:
                start += int(bit)
            yield {
                "area": area,
                "start": start,
                "end": start + type_bits,
                "unit": unit,
                "section": section,
                "match": match,
                "name": match.group("name"),
                "address": f"%{area}{width}{match.group('byte')}"
                + (f".{bit}" if bit is not None else ""),
            }


def check(ctx):
    ctx.capability(Capability.DECLARATIONS)
    by_area = {}
    for item in _declarations(ctx):
        by_area.setdefault(item["area"], []).append(item)

    for items in by_area.values():
        items.sort(key=lambda item: item["match"].start())
        for index, item in enumerate(items):
            for other in items[:index]:
                if item["start"] >= other["end"] or other["start"] >= item["end"]:
                    continue
                yield finding_in(
                    message=(
                        f"AT variable '{item['name']}' overlaps "
                        f"'{other['name']}' at {item['address']}"
                    ),
                    unit=item["unit"],
                    offset=item["section"].at(item["match"].start("name")),
                    end_offset=item["section"].at(item["match"].end("name")),
                    anchor=item["name"],
                    context=f"{other['name']} / {item['address']}",
                )
                break


RULE = RuleSpec(
    id="CTS0026",
    title="Overlapping AT memory areas",
    severity="danger",
    scope=Scope.PROJECT,
    requires={Capability.DECLARATIONS},
    kinds="ANY",
    summary="Explicit AT declarations must not claim overlapping memory.",
    topic="Correctness",
    check=check,
)
