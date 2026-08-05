"""CTS0004 - repeated numeric literals that should have a name."""

from __future__ import annotations

import re
from collections import Counter

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

# IEC 61131-3 integer and real literals, including based integer literals
# such as 16#FF. The surrounding boundaries keep digits in identifiers and
# already named literals out of the matches.
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_#])"
    r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"(?:2|8|16)#(?:[0-9A-Fa-f]+))"
    r"(?![A-Za-z0-9_#])"
)


def _is_trivial(value, max_trivial_integer):
    """Return whether *value* is a common small literal."""
    if "#" in value:
        return False
    try:
        number = float(value)
    except ValueError:
        return False
    if number.is_integer():
        return abs(number) <= max_trivial_integer
    # Not a tunable: fractions below 1 are ratios, never named constants.
    return abs(number) <= 1


def _normalise(value):
    """Return a stable spelling used to group equivalent occurrences."""
    value = value.upper()
    if "#" not in value:
        try:
            number = float(value)
        except ValueError:
            pass
        else:
            if number.is_integer():
                return str(int(number))
            return format(number, ".15g")
    if value.startswith("+"):
        value = value[1:]
    return value


def check(unit, ctx):
    """Flag repeated non-trivial numeric literals in a callable unit."""
    ctx.capability(Capability.ST_TEXT)
    max_trivial_integer = ctx.option("max_trivial_integer")
    min_occurrences = ctx.option("min_occurrences")
    section = body(unit)
    if not section:
        return

    clean = section.text
    matches = []
    for match in _NUMBER_RE.finditer(clean):
        if _is_trivial(match.group(), max_trivial_integer):
            continue
        before = clean[: match.start()].rstrip()
        after = clean[match.end() :].lstrip()
        # Array indexes and bit selectors are structural positions, not
        # configurable thresholds. The latter are written as ``word.7``.
        bit_selector = after.startswith("]") and re.match(r"\]\s*\.\s*\d", after)
        if before.endswith("[") or bit_selector:
            continue
        matches.append(match)
    counts = Counter(_normalise(m.group()) for m in matches)

    for match in matches:
        value = _normalise(match.group())
        if counts[value] < min_occurrences:
            continue
        yield finding_in(
            message=(
                f"repeated numeric literal {match.group()} could be a CONSTANT "
                "or input parameter"
            ),
            unit=unit,
            offset=section.at(match.start()),
            end_offset=section.at(match.end()),
            anchor=value,
            context=match.group(),
        )


RULE = RuleSpec(
    id="CTS0004",
    title="Magic numeric literal",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Repeated non-trivial numeric literals should be named constants or parameters.",
    topic="Code quality",
    check=check,
    options={"min_occurrences": 2, "max_trivial_integer": 10},
)
