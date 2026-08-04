"""CTS0007 - structural indentation drift in ST implementations."""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.rules_api import RuleSpec, finding_in
from cds_text_sync.analyze.st.body import body

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
    if not unit.implementation:
        return

    section = body(unit)
    # Blanking is 1:1, so the blanked text splits into the same lines as the
    # raw text and gives the comment-free code for each of them.
    clean_lines = section.text.splitlines()
    depth_indents = {0: 0}
    depth = 0
    previous_code = ""

    for lineno, line_start, line in section.lines():
        code = clean_lines[lineno - 1].strip()
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        upper = code.upper()
        if not code:
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
                    message=f"structural indentation is inconsistent: {reason}",
                    unit=unit,
                    offset=line_start,
                    end_offset=line_start + len(prefix),
                    anchor=f"level:{expected_depth}",
                    context=line.lstrip(),
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


RULE = RuleSpec(
    id="CTS0007",
    title="Structural indentation",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Implementation indentation must reflect actual ST block nesting.",
    topic="Style",
    check=check,
)
