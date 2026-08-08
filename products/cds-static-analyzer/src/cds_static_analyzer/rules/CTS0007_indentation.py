"""CTS0007 - structural indentation drift in ST implementations."""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body
from cds_static_analyzer.st.blanking import blank_noise, trim_strings

_OPENERS = re.compile(r"\b(IF|FOR|WHILE|REPEAT|CASE)\b", re.IGNORECASE)
_CLOSERS = re.compile(r"^END_(IF|FOR|WHILE|REPEAT|CASE)\b", re.IGNORECASE)
_BRANCH = re.compile(r"^(ELSE|ELSIF)\b", re.IGNORECASE)
# A CASE label is a structural branch, not a statement at the CASE body
# level.  CODESYS commonly writes labels at the CASE indentation and indents
# their statements one level further, for example ``1:`` followed by a TAB.
# Keep the pattern deliberately broad: labels may be integer ranges, enums,
# qualified names, or comma-separated alternatives.  ``:=`` is excluded so a
# normal assignment can never be mistaken for a label.
_CASE_LABEL = re.compile(r"^[^;:]+:(?!=)", re.IGNORECASE)
_CONTINUATION_START = re.compile(
    r"^(?:[,.)\]}]|(?:AND|OR|XOR)\b|[+\-*/])", re.IGNORECASE
)


def _is_continuation(previous, current=""):
    """Return whether a line belongs to the expression above it.

    ST projects commonly put call arguments on lines beginning with a comma,
    and put the closing ``);`` on its own line.  Looking only at the previous
    line made those perfectly intentional alignments look like block drift.
    """
    return bool(
        (previous and re.search(r"(?:\b(?:AND|OR|XOR)|:=|,|\(|\.)\s*$", previous, re.I))
        or (current and _CONTINUATION_START.match(current))
    )


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
    clean_lines = section.text.split("\n")
    depth_indents = {0: 0}
    depth = 0
    previous_code = ""

    for lineno, line_start, line in section.lines():
        # A malformed or partially reconstructed source section must not make
        # a style rule crash the whole analysis.  ``Section.lines()`` is based
        # on the raw text while ``clean_lines`` is based on the blanked text;
        # normally they are 1:1, but preserve analyzer resilience if a parser
        # adapter ever violates that assumption.
        if lineno < 1 or lineno > len(clean_lines):
            continue
        code = clean_lines[lineno - 1].strip()
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        upper = code.upper()
        if not code:
            continue

        continuation = _is_continuation(previous_code, code)
        is_close = bool(_CLOSERS.match(upper))
        is_branch = bool(_BRANCH.match(upper))
        is_case_label = bool(_CASE_LABEL.match(upper)) and depth > 0
        expected_depth = max(
            0, depth - (1 if is_close or is_branch or is_case_label else 0)
        )

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
        elif is_branch or is_case_label:
            # ELSE/ELSIF belongs to the current block; its following body is
            # nested one level again. CASE labels have the same structural
            # role: the label is at the parent level, while its body remains
            # at the CASE depth.
            pass
        else:
            opens = _OPENERS.findall(upper)
            # A one-line IF/FOR is not a block opener unless it has no matching
            # END token on the same line.
            if opens and not re.search(r"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b", upper):
                depth += len(opens)

        previous_code = code


def fix(text, finding):
    """Return *text* with the affected structural indentation corrected.

    The expected indentation is calculated with the same depth model as
    :func:`check`.  Only the source lines represented by the finding are
    changed; continuation lines and all non-leading content remain intact.
    """
    # ST source is line-oriented by LF.  ``str.splitlines`` also treats
    # Unicode control characters inside comments as line breaks.
    raw_lines = text.split("\n")
    clean_lines = trim_strings(blank_noise(text)).split("\n")
    target_lines = set()
    location = finding.get("location") if isinstance(finding, dict) else None
    if isinstance(location, dict) and location.get("line") is not None:
        start_line = int(location["line"])
        end_line = int(location.get("end_line") or start_line)
        target_lines.update(range(start_line, max(start_line, end_line) + 1))
    for value in (finding.get("member_lines", []) if isinstance(finding, dict) else []):
        try:
            target_lines.add(int(value))
        except (TypeError, ValueError):
            continue
    if not target_lines:
        return text

    depth_indents = {0: 0}
    depth = 0
    previous_code = ""
    records = []
    observed_prefixes = []

    for index, raw in enumerate(raw_lines):
        if index >= len(clean_lines):
            break
        code = clean_lines[index].strip()
        prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if not code:
            continue

        continuation = _is_continuation(previous_code, code)
        upper = code.upper()
        is_close = bool(_CLOSERS.match(upper))
        is_branch = bool(_BRANCH.match(upper))
        is_case_label = bool(_CASE_LABEL.match(upper)) and depth > 0
        expected_depth = max(
            0, depth - (1 if is_close or is_branch or is_case_label else 0)
        )
        if not continuation:
            actual = _indent_width(prefix)
            expected = depth_indents.setdefault(
                expected_depth, actual if expected_depth else 0
            )
            mixed = " " in prefix and "\t" in prefix
            if prefix and not mixed:
                observed_prefixes.append(prefix)
            records.append((index, actual, expected, mixed, prefix))

        if is_close:
            depth = max(0, depth - 1)
        elif not (is_branch or is_case_label):
            opens = _OPENERS.findall(upper)
            if opens and not re.search(
                r"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b", upper
            ):
                depth += len(opens)
        previous_code = code

    tab_columns = sum(prefix.count("\t") for prefix in observed_prefixes)
    space_columns = sum(prefix.count(" ") for prefix in observed_prefixes)
    use_tabs = tab_columns > space_columns

    def prefix_for(expected):
        if expected <= 0:
            return ""
        for prefix in observed_prefixes:
            if _indent_width(prefix) == expected:
                return prefix
        return ("\t" if use_tabs else " ") * expected

    for index, actual, expected, mixed, prefix in records:
        if index + 1 not in target_lines or (actual == expected and not mixed):
            continue
        raw = raw_lines[index]
        raw_lines[index] = prefix_for(expected) + raw[len(prefix) :]

    return "\n".join(raw_lines)


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
    merge="adjacent",
    options={"merge": True},
    fix=fix,
)
