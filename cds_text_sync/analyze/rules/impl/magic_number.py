"""CTS0004: repeated numeric literals that should have a name."""

from __future__ import annotations

import re
from collections import Counter

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise, trim_strings
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0004"
SEVERITY = "style"

# IEC 61131-3 integer and real literals, including based integer literals
# such as 16#FF.  The surrounding boundaries keep digits in identifiers and
# already named literals out of the matches.
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_#])"
    r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"(?:2|8|16)#(?:[0-9A-Fa-f]+))"
    r"(?![A-Za-z0-9_#])"
)


def _is_trivial(value):
    """Return whether *value* is a common small literal."""
    if "#" in value:
        return False
    try:
        number = float(value)
    except ValueError:
        return False
    if number.is_integer():
        return abs(number) <= 10
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
    body = unit.implementation if unit.implementation is not None else unit.text
    if not body:
        return

    clean = trim_strings(blank_noise(body))
    matches = []
    for match in _NUMBER_RE.finditer(clean):
        if _is_trivial(match.group()):
            continue
        before = clean[: match.start()].rstrip()
        after = clean[match.end() :].lstrip()
        # Array indexes and bit selectors are structural positions, not
        # configurable thresholds.  The latter are written as ``word.7``.
        bit_selector = after.startswith("]") and re.match(r"\]\s*\.\s*\d", after)
        if before.endswith("[") or bit_selector:
            continue
        matches.append(match)
    counts = Counter(_normalise(m.group()) for m in matches)
    impl_start = next(
        (span.start_offset for span in unit.source_spans if span.role == "implementation"),
        0,
    )

    for match in matches:
        value = _normalise(match.group())
        if counts[value] < 2:
            continue
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message=(
                f"repeated numeric literal {match.group()} could be a CONSTANT "
                "or input parameter"
            ),
            unit=unit,
            offset=impl_start + match.start(),
            end_offset=impl_start + match.end(),
            anchor=value,
            context=match.group(),
            rule_title="Magic numeric literal",
        )
