"""CTS0044 - overlapping numeric CASE ranges make part of a branch unreachable."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.blocks import tree
from cds_static_analyzer.st.body import body


_INTEGER_RANGE = re.compile(r"^\s*([+-]?\d+)\s*(?:\.\.\s*([+-]?\d+))?\s*$")


def _numeric_ranges(raw):
    """Return ``(display, low, high)`` for the decimal labels in *raw*.

    CASE labels can also be enum members, constants, or expressions. Those are
    deliberately ignored here because their values require type resolution.
    """
    for part in re.split(r"\s*,\s*", raw):
        match = _INTEGER_RANGE.fullmatch(part)
        if not match:
            continue
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) is not None else first
        yield part.strip(), min(first, last), max(first, last)


def _cases(node):
    if node.kind == "CASE":
        yield node
    for child in node.children:
        yield from _cases(child)


def check(unit, ctx):
    ctx.capability(Capability.ST_TEXT)
    ctx.capability(Capability.BLOCK_STRUCTURE)
    section = body(unit)
    if not section:
        return

    for case in _cases(tree(unit)):
        previous = []
        for raw_label, absolute_start, _ in case.branches:
            current_ranges = list(_numeric_ranges(raw_label))
            if not current_ranges:
                continue

            overlaps = []
            for display, low, high in current_ranges:
                for previous_display, previous_low, previous_high in previous:
                    if (low, high) == (previous_low, previous_high):
                        # CTS0015 owns exact duplicate labels. Avoid producing
                        # two findings for the same defect.
                        continue
                    if low <= previous_high and previous_low <= high:
                        overlaps.append((display, previous_display))
                        break

            if overlaps:
                display, previous_display = overlaps[0]
                local_start = absolute_start - section.base
                yield finding_in(
                    message=(
                        f"CASE range {display!r} overlaps previous range "
                        f"{previous_display!r}; part of this branch is unreachable"
                    ),
                    unit=unit,
                    offset=section.at(local_start),
                    end_offset=section.at(local_start + len(raw_label)),
                    anchor=display,
                    context=raw_label,
                )

            previous.extend(current_ranges)


RULE = RuleSpec(
    id="CTS0044",
    title="Overlapping CASE range",
    severity="danger",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT, Capability.BLOCK_STRUCTURE},
    kinds="CALLABLE",
    summary="Numeric CASE ranges must not overlap an earlier branch.",
    topic="Correctness",
    check=check,
)
