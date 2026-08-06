"""CTS0049 - a constant arithmetic result does not fit its target type."""

from __future__ import annotations

import ast
import math
import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st import decl
from cds_static_analyzer.st.body import body, declaration
from cds_static_analyzer.st.declarations import classify_type


_RANGES = {
    "SINT": (-128, 127),
    "USINT": (0, 255),
    "BYTE": (0, 255),
    "INT": (-32768, 32767),
    "UINT": (0, 65535),
    "WORD": (0, 65535),
    "DINT": (-2147483648, 2147483647),
    "UDINT": (0, 4294967295),
    "DWORD": (0, 4294967295),
    "LINT": (-9223372036854775808, 9223372036854775807),
    "ULINT": (0, 18446744073709551615),
    "LWORD": (0, 18446744073709551615),
}
_ASSIGNMENT = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\s*:=\s*(?P<expression>[^;]+)",
    re.IGNORECASE,
)
_NUMERIC_EXPRESSION = re.compile(r"[0-9\s.+\-*/%()eE]+$")


def _evaluate(expression):
    text = re.sub(r"\bMOD\b", "%", expression, flags=re.IGNORECASE).strip()
    if not text or not _NUMERIC_EXPRESSION.fullmatch(text):
        return None
    try:
        node = ast.parse(text, mode="eval").body
        value = _evaluate_node(node)
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _evaluate_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_node(node.operand)
        return +value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, (ast.Div, ast.FloorDiv)):
            if right == 0:
                raise ZeroDivisionError
            return left / right if isinstance(node.op, ast.Div) else left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise ZeroDivisionError
            return left % right
    raise ValueError("not a constant arithmetic expression")


def _member_offset(unit, member):
    section = declaration(unit)
    if not section:
        return None
    lines = unit.declaration.split("\n")
    index = member.get("line", 0) - 1
    if not 0 <= index < len(lines):
        return None
    position = lines[index].find(member["name"])
    if position < 0:
        return None
    return section.at(sum(len(lines[line]) + 1 for line in range(index)) + position)


def _integer_targets(unit):
    targets = {}
    for member in decl.all_members(unit):
        typ = classify_type(member.get("type", ""))
        base = str(typ.get("base", "")).upper()
        if base in _RANGES:
            targets[member.get("name", "").casefold()] = (
                member,
                base,
                _RANGES[base],
            )
    return targets


def _finding(unit, target, base, limits, expression, value, offset, context):
    low, high = limits
    name = target["name"]
    return finding_in(
        message=(
            f"constant expression {expression!r} evaluates to {value} outside "
            f"{base} range [{low}..{high}]"
        ),
        unit=unit,
        offset=offset,
        end_offset=(offset + len(name) if offset is not None else None),
        anchor=name,
        context=context,
    )


def check(unit, ctx):
    ctx.capability(Capability.DECLARATIONS)
    ctx.capability(Capability.ST_TEXT)
    targets = _integer_targets(unit)
    if not targets:
        return

    for member, base, limits in targets.values():
        expression = member.get("initial", "").strip()
        value = _evaluate(expression)
        if value is None or limits[0] <= value <= limits[1]:
            continue
        yield _finding(
            unit,
            member,
            base,
            limits,
            expression,
            value,
            _member_offset(unit, member),
            f"{member['name']} : {member.get('type', '')} := {expression}",
        )

    section = body(unit)
    if not section:
        return
    for match in _ASSIGNMENT.finditer(section.text):
        target_info = targets.get(match.group("name").casefold())
        if target_info is None:
            continue
        expression = match.group("expression").strip()
        value = _evaluate(expression)
        if value is None or target_info[2][0] <= value <= target_info[2][1]:
            continue
        target, base, limits = target_info
        name_offset = section.at(match.start("name"))
        yield _finding(
            unit,
            target,
            base,
            limits,
            expression,
            value,
            name_offset,
            match.group(0).strip(),
        )


RULE = RuleSpec(
    id="CTS0049",
    title="Constant arithmetic overflow",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS, Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A constant arithmetic result does not fit its integer target type.",
    topic="Correctness",
    check=check,
)
