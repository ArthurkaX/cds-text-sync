"""CTS0007: structural indentation drift in ST implementations."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules.impl.engine_blank import blank_noise
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0007"
SEVERITY = "style"

_OPENERS = re.compile(r"\b(IF|FOR|WHILE|REPEAT|CASE)\b", re.IGNORECASE)
_CLOSERS = re.compile(r"^END_(IF|FOR|WHILE|REPEAT|CASE)\b", re.IGNORECASE)
_BRANCH = re.compile(r"^(ELSE|ELSIF)\b", re.IGNORECASE)


def _is_continuation(previous):
    return bool(previous and re.search(r"(?:\b(?:AND|OR|XOR)|:=|,|\(|\.)\s*$", previous, re.I))


def _indent_width(prefix):
    # ST projects commonly use tabs for nesting. Spaces are counted as one
    # column here; the rule compares siblings, not visual alignment columns.
    return len(prefix.expandtabs(1))


def check(unit, ctx):
    """Report indentation that contradicts the actual block nesting.

    Declaration tables are intentionally excluded. They have their own future
    formatting rule and their visual alignment must not be mistaken for code
    nesting.
    """
    ctx.capability(Capability.ST_TEXT)
    text = unit.implementation
    if not text:
        return

    impl_start = next(
        (span.start_offset for span in unit.source_spans if span.role == "implementation"),
        0,
    )
    depth_indents = {0: 0}
    depth = 0
    previous_code = ""
    offset = 0

    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        code = blank_noise(line).strip()
        upper = code.upper()
        if not code:
            offset += len(raw_line)
            continue

        continuation = _is_continuation(previous_code)
        is_close = bool(_CLOSERS.match(upper))
        is_branch = bool(_BRANCH.match(upper))
        expected_depth = max(0, depth - (1 if is_close or is_branch else 0))

        if not continuation:
            actual = _indent_width(prefix)
            expected = depth_indents.setdefault(expected_depth, actual if expected_depth else 0)
            mixed = " " in prefix and "\t" in prefix
            if mixed or actual != expected:
                reason = "mixed tabs and spaces" if mixed else (
                    f"expected indentation for block level {expected_depth}, got {actual}"
                )
                yield finding_in(
                    rule_id=RULE_ID,
                    severity=SEVERITY,
                    message=f"structural indentation is inconsistent: {reason}",
                    unit=unit,
                    offset=impl_start + offset,
                    end_offset=impl_start + offset + len(prefix),
                    anchor=f"level:{expected_depth}",
                    context=line.lstrip(),
                    rule_title="Structural indentation",
                )

        if is_close:
            depth = max(0, depth - 1)
        elif is_branch:
            # ELSE/ELSIF belongs to the current block; its following body is
            # nested one level again.
            pass
        else:
            opens = _OPENERS.findall(upper)
            # A one-line IF/FOR is not a block opener unless it has no matching
            # END token on the same line.
            if opens and not re.search(r"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b", upper):
                depth += len(opens)

        previous_code = code
        offset += len(raw_line)
