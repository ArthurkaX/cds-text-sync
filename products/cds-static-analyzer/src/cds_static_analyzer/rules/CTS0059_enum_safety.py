"""CTS0059 - enum assignments and CASE statements must stay within the enum."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body, declaration
from cds_static_analyzer.st.declarations import classify_type


_ASSIGNMENT = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\s*:=\s*(?P<value>[^;]+)", re.IGNORECASE
)
_CASE_HEADER = re.compile(
    r"\bCASE\s+(?P<selector>[A-Za-z_]\w*)\s+OF\b", re.IGNORECASE
)
_INTEGER = re.compile(r"^[+-]?\d+$")
_QUALIFIED_NAME = re.compile(r"(?:[A-Za-z_]\w*[.#])?(?P<name>[A-Za-z_]\w*)$")


def _member_offset(unit, member):
    if not member.get("line") or not unit.declaration:
        return None
    lines = unit.declaration.split("\n")
    index = member["line"] - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return declaration(unit).at(sum(len(lines[i]) + 1 for i in range(index)) + position)


def _enum_definitions(ctx):
    enums = {}
    for unit in ctx.units:
        info = decl.dut_info(unit)
        if not info or info.get("kind") != "enum":
            continue
        members = {}
        for field in info.get("fields", ()):
            members[field["name"].casefold()] = field.get("value")
        if members:
            enums[info["name"].casefold()] = {
                "name": info["name"],
                "members": members,
                "values": {value for value in members.values() if value is not None},
            }
    return enums


def _enum_variables(unit, enums):
    variables = {}
    for member in decl.all_members(unit):
        info = classify_type(member.get("type", ""))
        if info.get("kind") != "ref":
            continue
        enum = enums.get(str(info.get("name", "")).casefold())
        if enum:
            variables[member["name"].casefold()] = (member, enum)
    return variables


def _literal_value(raw, enum):
    value = raw.strip()
    if _INTEGER.fullmatch(value):
        number = int(value)
        return number if number in enum["values"] else None
    typed = re.match(r"^(?:[A-Za-z_]\w*[#.]\s*)?([A-Za-z_]\w*)$", value)
    if typed and typed.group(1).casefold() in enum["members"]:
        return typed.group(1).casefold()
    return None


def _assignment_finding(unit, section, match, enum, value, target, offset_override=None):
    if value is None:
        return None
    if isinstance(value, int):
        expected = ", ".join(
            f"{name}={number}" for name, number in enum["members"].items()
        )
        detail = f"numeric value {match.group('value').strip()} is not one of {expected}"
    else:
        detail = f"member {match.group('value').strip()} is not declared"
    if offset_override is None:
        offset = section.at(match.start("value"))
        end_offset = section.at(match.end("value"))
        anchor = match.group("value").strip()
    else:
        offset = offset_override
        end_offset = offset + len(target)
        anchor = target
    return finding_in(
        message=(
            f"assignment to enum '{enum['name']}' variable '{target}' is invalid: "
            f"{detail}"
        ),
        unit=unit,
        offset=offset,
        end_offset=end_offset,
        anchor=anchor,
        context=match.group(0).strip(),
    )


def _covered_enum_members(raw_labels, enum):
    covered = set()
    for raw in re.split(r"\s*,\s*", raw_labels):
        label = raw.strip()
        if not label:
            continue
        if _INTEGER.fullmatch(label):
            value = int(label)
            covered.update(
                name for name, number in enum["members"].items() if number == value
            )
            continue
        match = _QUALIFIED_NAME.fullmatch(label)
        if match:
            name = match.group("name").casefold()
            if name in enum["members"]:
                covered.add(name)
    return covered


def _walk(node):
    for child in node.children:
        yield child
        yield from _walk(child)


def check(ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    enums = _enum_definitions(ctx)
    if not enums:
        return

    for unit in ctx.units:
        variables = _enum_variables(unit, enums)
        if not variables:
            continue

        for member, enum in variables.values():
            initial = member.get("initial", "").strip()
            if not initial:
                continue
            valid = _literal_value(initial, enum)
            if valid is not None:
                continue
            match = re.match(r"(?P<value>.+)", initial)
            finding = _assignment_finding(
                unit,
                declaration(unit),
                match,
                enum,
                initial if _INTEGER.fullmatch(initial) and int(initial) not in enum["values"] else "unknown",
                member["name"],
                offset_override=_member_offset(unit, member),
            )
            if finding:
                yield finding

        section = body(unit)
        if section:
            for match in _ASSIGNMENT.finditer(section.text):
                target_info = variables.get(match.group("name").casefold())
                if target_info is None:
                    continue
                member, enum = target_info
                value = match.group("value").strip()
                if _INTEGER.fullmatch(value):
                    valid = int(value) in enum["values"]
                else:
                    valid = bool(
                        re.fullmatch(
                            r"(?:[A-Za-z_]\w*[.#])?[A-Za-z_]\w*", value
                        )
                        and value.rsplit("#", 1)[-1].rsplit(".", 1)[-1].casefold()
                        in enum["members"]
                    )
                if valid:
                    continue
                invalid = int(value) if _INTEGER.fullmatch(value) else "unknown"
                finding = _assignment_finding(
                    unit, section, match, enum, invalid, member["name"]
                )
                if finding:
                    yield finding

            for case in _walk(tree(unit)):
                if case.kind != "CASE" or case.end_offset is None:
                    continue
                local_start = case.start_offset - section.base
                local_end = case.end_offset - section.base
                header = _CASE_HEADER.search(section.text, local_start, local_end)
                if not header:
                    continue
                selector_info = variables.get(header.group("selector").casefold())
                if selector_info is None or any(
                    label.strip().upper() == "ELSE" for label, _, _ in case.branches
                ):
                    continue
                _, enum = selector_info
                covered = set()
                for label, _, _ in case.branches:
                    covered.update(_covered_enum_members(label, enum))
                missing = [name for name in enum["members"] if name not in covered]
                if not missing:
                    continue
                expression = header.group(0).strip()
                absolute = section.at(header.start())
                yield finding_in(
                    message=(
                        f"CASE on enum '{enum['name']}' does not cover members: "
                        f"{', '.join(missing)} and has no ELSE branch"
                    ),
                    unit=unit,
                    offset=absolute,
                    end_offset=section.at(header.end()),
                    anchor=expression,
                    context=expression,
                )


RULE = RuleSpec(
    id="CTS0059",
    title="Unsafe enumeration use",
    severity="danger",
    scope=Scope.PROJECT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT, Capability.BLOCK_STRUCTURE},
    kinds="ANY",
    summary="Enumeration assignments and CASE branches must use declared members.",
    topic="Correctness",
    check=check,
)
