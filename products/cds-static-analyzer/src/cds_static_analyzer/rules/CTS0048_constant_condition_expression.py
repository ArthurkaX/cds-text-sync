"""CTS0048 - control-flow conditions that can be evaluated at analysis time."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body


_CONDITION = re.compile(
    r"\b(?:IF|ELSIF|WHILE)\b(?P<condition>.*?)\b(?:THEN|DO)\b",
    re.IGNORECASE | re.DOTALL,
)
_TOKEN = re.compile(
    r"(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<operator><>|<=|>=|=|<|>|\+|-|\*|/|\(|\))"
    r"|(?P<word>AND|OR|XOR|NOT|TRUE|FALSE)\b",
    re.IGNORECASE,
)
_COMPARISONS = {"=", "<>", "<", "<=", ">", ">="}


class _ConstantExpression:
    def __init__(self, text):
        self.tokens = []
        position = 0
        for match in _TOKEN.finditer(text):
            if text[position:match.start()].strip():
                raise ValueError("unsupported token")
            value = match.group(0)
            kind = "number" if match.group("number") else "word"
            self.tokens.append((kind, value.upper() if kind == "word" else value))
            position = match.end()
        if text[position:].strip():
            raise ValueError("unsupported token")
        self.index = 0

    def _peek(self, value=None):
        if self.index >= len(self.tokens):
            return False if value is not None else None
        token = self.tokens[self.index][1]
        return token == value if value is not None else token

    def _take(self, value=None):
        if not self._peek(value):
            raise ValueError("unexpected token")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parse(self):
        value = self._parse_or()
        if self.index != len(self.tokens) or not isinstance(value, bool):
            raise ValueError("condition is not boolean")
        return value

    def _parse_or(self):
        value = self._parse_and()
        while self._peek("OR") or self._peek("XOR"):
            operator = self._take()[1]
            right = self._parse_and()
            value = bool(value) or bool(right) if operator == "OR" else bool(value) != bool(right)
        return value

    def _parse_and(self):
        value = self._parse_not()
        while self._peek("AND"):
            self._take("AND")
            value = bool(value) and bool(self._parse_not())
        return value

    def _parse_not(self):
        if self._peek("NOT"):
            self._take("NOT")
            return not bool(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self):
        left = self._parse_arithmetic()
        if self._peek() not in _COMPARISONS:
            return left
        operator = self._take()[1]
        right = self._parse_arithmetic()
        if self._peek() in _COMPARISONS:
            raise ValueError("chained comparison")
        if operator == "=":
            return left == right
        if operator == "<>":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        return left >= right

    def _parse_arithmetic(self):
        value = self._parse_unary()
        while self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            right = self._parse_unary()
            value = value + right if operator == "+" else value - right
        return value

    def _parse_unary(self):
        if self._peek("+"):
            self._take("+")
            return +self._parse_unary()
        if self._peek("-"):
            self._take("-")
            return -self._parse_unary()
        value = self._parse_primary()
        while self._peek("*") or self._peek("/"):
            operator = self._take()[1]
            right = self._parse_primary()
            if operator == "*":
                value *= right
            else:
                if right == 0:
                    raise ValueError("division by zero")
                value /= right
        return value

    def _parse_primary(self):
        if self._peek("("):
            self._take("(")
            value = self._parse_or()
            self._take(")")
            return value
        kind, value = self._take()
        if kind == "number":
            return float(value) if any(char in value for char in ".eE") else int(value)
        if value == "TRUE":
            return True
        if value == "FALSE":
            return False
        raise ValueError("not a constant")


def _evaluate(condition):
    try:
        return _ConstantExpression(condition).parse()
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    section = body(unit)
    if not section:
        return

    for match in _CONDITION.finditer(section.text):
        condition = match.group("condition").strip()
        if condition.upper() in {"TRUE", "FALSE"}:
            # CTS0017 already reports the literal form.
            continue
        result = _evaluate(condition)
        if result is None:
            continue
        leading = len(match.group("condition")) - len(match.group("condition").lstrip())
        absolute = section.at(match.start("condition") + leading)
        yield finding_in(
            message=f"control-flow condition {condition!r} is always {str(result).lower()}",
            unit=unit,
            offset=absolute,
            end_offset=absolute + len(condition),
            anchor=condition,
            context=condition,
        )


RULE = RuleSpec(
    id="CTS0048",
    title="Constant control-flow expression",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="A control-flow condition evaluates to a constant result.",
    topic="Correctness",
    check=check,
)
