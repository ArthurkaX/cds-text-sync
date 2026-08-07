"""CTS0063 - provably unsafe MEMCPY/MemMove size expressions."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.declarations import classify_type


_CALL = re.compile(r"\b(?P<name>MEMCPY|MEMMOVE)\s*\(", re.IGNORECASE)
_ADR = re.compile(r"^\s*ADR\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*$", re.IGNORECASE)
_SIZEOF = re.compile(r"^\s*SIZEOF\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*$", re.IGNORECASE)
_INTEGER = re.compile(r"^\s*(?P<value>\d+)\s*$")

_SCALAR_SIZES = {
    "BOOL": 1, "BIT": 1, "SINT": 1, "USINT": 1, "BYTE": 1, "CHAR": 1,
    "INT": 2, "UINT": 2, "WORD": 2, "WCHAR": 2,
    "DINT": 4, "UDINT": 4, "DWORD": 4, "REAL": 4, "TIME": 4,
    "LINT": 8, "ULINT": 8, "LWORD": 8, "LREAL": 8, "LTIME": 8,
}


def _split_args(text):
    args = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
    args.append(text[start:].strip())
    return args


def _static_size(type_name):
    info = classify_type(type_name)
    if info.get("kind") == "scalar":
        base = str(info.get("base", "")).upper()
        string_match = re.fullmatch(
            r"W?STRING\s*\(\s*(\d+)\s*\)", type_name.strip(), re.IGNORECASE
        )
        if string_match:
            return int(string_match.group(1)) + (2 if base == "WSTRING" else 1)
        return _SCALAR_SIZES.get(base)
    if info.get("kind") != "array":
        return None
    element_size = _static_size(info.get("elem", ""))
    if element_size is None:
        return None
    count = 1
    for lower, upper in info.get("dims", ()):
        try:
            count *= int(upper, 0) - int(lower, 0) + 1
        except ValueError:
            return None
    return element_size * count


def _members(unit):
    result = {}
    for member in decl.all_members(unit):
        type_name = member.get("type", "")
        info = classify_type(type_name)
        result[member.get("name", "").casefold()] = {
            "type": type_name,
            "size": _static_size(type_name),
            "pointer": info.get("kind") == "scalar" and str(info.get("base", "")).upper() == "POINTER",
        }
    return result


def _find_close(text, opening):
    depth = 1
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _argument_offset(text, start, end, argument):
    relative = text[start:end].find(argument)
    return start + (relative if relative >= 0 else 0)


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return
    members = _members(unit)
    if not members:
        return

    for match in _CALL.finditer(section.text):
        close = _find_close(section.text, match.end())
        if close is None:
            continue
        args = _split_args(section.text[match.end() : close])
        if len(args) != 3:
            continue
        destination = _ADR.fullmatch(args[0])
        source = _ADR.fullmatch(args[1])
        size = _SIZEOF.fullmatch(args[2])
        destination_name = destination.group("name").casefold() if destination else None
        source_name = source.group("name").casefold() if source else None
        reason = None
        reason_start = match.start()
        reason_end = close + 1

        if size:
            size_name = size.group("name").casefold()
            size_member = members.get(size_name)
            if size_member and size_member["pointer"]:
                reason = (
                    f"SIZEOF({size.group('name')}) is the pointer size rather than "
                    "the pointed object size"
                )
                reason_start = _argument_offset(section.text, match.end(), close, args[2])
                reason_end = reason_start + len(args[2])
            else:
                destination_member = members.get(destination_name) if destination_name else None
                source_member = members.get(source_name) if source_name else None
                if (
                    destination_member
                    and source_member
                    and destination_member["size"] is not None
                    and source_member["size"] is not None
                    and size_name == source_name
                    and destination_member["size"] < source_member["size"]
                ):
                    reason = (
                        f"destination '{destination.group('name')}' is {destination_member['size']} bytes "
                        f"but SIZEOF({source.group('name')}) copies {source_member['size']} bytes"
                    )
        else:
            literal = _INTEGER.fullmatch(args[2])
            destination_member = members.get(destination_name) if destination_name else None
            if literal and destination_member and destination_member["size"] is not None:
                requested = int(literal.group("value"))
                if requested > destination_member["size"]:
                    reason = (
                        f"destination '{destination.group('name')}' is {destination_member['size']} bytes "
                        f"but the call requests {requested} bytes"
                    )

        if reason:
            expression = section.text[match.start() : close + 1]
            yield finding_in(
                message=f"{match.group('name')} has an inconsistent size: {reason}",
                unit=unit,
                offset=section.at(reason_start),
                end_offset=section.at(reason_end),
                anchor=expression,
                context=expression,
            )


RULE = RuleSpec(
    id="CTS0063",
    title="Inconsistent MEMCPY/MemMove size",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A memory-copy size may exceed the destination or use pointer size.",
    topic="Correctness",
    check=check,
)
