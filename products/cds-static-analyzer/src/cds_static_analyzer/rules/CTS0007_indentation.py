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
# The closing bracket must stay escaped *and* close the class: writing it as
# ``[,.)}\]`` leaves the class open, swallows the whole alternation below and
# silently turns the pattern into "any of the letters A N D O R X b", so every
# statement starting with one of them was skipped as a continuation line.
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


def _scan(raw_lines, clean_lines):
    """Yield ``(index, actual, expected, mixed, prefix, level)`` per checked line.

    ``raw_lines[i]`` is the raw source line (line ending already stripped) and
    ``clean_lines[i]`` is its comment/string-blanked counterpart.  Every
    non-continuation code line is yielded, whether or not it drifts; the
    caller decides what a mismatch means.

    The indentation model is block-local instead of an absolute depth table,
    so an implementation whose whole body is uniformly shifted one level is not
    flagged (the outermost expected indent is *learned* from the first line,
    not hard-coded to 0), and each CASE block keeps whatever label style it
    chose.  The model tracks three things in order:

    ``base`` - expected indent of every statement at the outermost level,
    learned once from the first non-continuation, non-empty code line.
    ``step`` - the unit-wide indent increment, learned the first time a block
    body line sits deeper than its reference indent; falls back to 1.
    ``stack`` - one frame per open block, carrying ``opener_indent``, ``kind``
    ('case' for CASE openers, else 'block') and, for cases, ``label_indent``.
    """
    base = None  # expected indent of outermost statements, learned once
    step = None  # unit-wide indent increment, learned on first block body
    stack = []  # one frame per open block: opener_indent, kind, label_indent
    previous_code = ""

    for index, raw in enumerate(raw_lines):
        if index >= len(clean_lines):
            break
        code = clean_lines[index].strip()
        prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if not code:
            continue
        upper = code.upper()
        actual = _indent_width(prefix)
        level = len(stack)

        continuation = _is_continuation(previous_code, code)
        is_close = bool(_CLOSERS.match(upper))
        is_branch = bool(_BRANCH.match(upper))
        is_case_label = (
            bool(_CASE_LABEL.match(upper))
            and bool(stack)
            and stack[-1]["kind"] == "case"
        )

        if not continuation:
            mixed = " " in prefix and "\t" in prefix
            if is_close:
                # A closer sits at its opener's column, so it belongs to the
                # enclosing level; an empty stack means an unmatched closer at
                # the outermost level.
                expected = stack[-1]["opener_indent"] if stack else base
            elif is_branch:
                # ELSE/ELSIF attaches to the current block; expected at the
                # opener's column, its following body nests one level again.
                expected = stack[-1]["opener_indent"] if stack else base
            elif is_case_label:
                # The label style is a local choice of that CASE block; the
                # rule enforces consistency within the block instead of
                # imposing one of the two legal styles (label at the CASE
                # column, or one level in).  Learn it verbatim from the first
                # label so either style is accepted unchanged.
                if stack[-1]["label_indent"] is None:
                    stack[-1]["label_indent"] = actual
                expected = stack[-1]["label_indent"]
            elif stack:
                # Body of a block: one step deeper than its reference.  For a
                # CASE whose label style is known, the reference is the label
                # column; otherwise it is the opener's column.
                frame = stack[-1]
                if frame["kind"] == "case" and frame["label_indent"] is not None:
                    reference = frame["label_indent"]
                else:
                    reference = frame["opener_indent"]
                if step is None and actual > reference:
                    step = actual - reference
                    expected = actual
                else:
                    expected = reference + (step if step is not None else 1)
            else:
                # Outermost statement.  ``base`` is learned once so a whole
                # body shifted one level is not treated as drift.
                if base is None:
                    base = actual
                expected = base

            # Every checked line is yielded, correct ones included: the fixer
            # learns the file's real indent prefixes from them, so a repair
            # reuses the project's own tabs or spaces instead of synthesizing
            # a prefix from the faulty lines alone.
            yield (index, actual, expected, mixed, prefix, level)

        if is_close:
            if stack:
                stack.pop()
        elif not (is_branch or is_case_label):
            opens = _OPENERS.findall(upper)
            # A one-line IF/FOR is not a block opener unless it has no matching
            # END token on the same line.
            if opens and not re.search(r"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b", upper):
                for opener in opens:
                    stack.append(
                        {
                            "opener_indent": actual,
                            "kind": "case" if opener.upper() == "CASE" else "block",
                            "label_indent": None,
                        }
                    )

        previous_code = code


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
    # raw text and gives the comment-free code for each of them.  The offset
    # of every raw line is kept alongside so findings can be anchored at the
    # absolute position.
    raw_lines = []
    starts = []
    for _lineno, line_start, line in section.lines():
        raw_lines.append(line)
        starts.append(line_start)
    clean_lines = section.text.split("\n")

    for index, actual, expected, mixed, prefix, level in _scan(raw_lines, clean_lines):
        if not (mixed or actual != expected):
            continue
        reason = "mixed tabs and spaces" if mixed else (
            f"expected indentation for block level {level}, got {actual}"
        )
        yield finding_in(
            message=f"structural indentation is inconsistent: {reason}",
            unit=unit,
            offset=starts[index],
            end_offset=starts[index] + len(prefix),
            anchor=f"level:{level}",
            context=raw_lines[index].lstrip(),
        )


def _implementation_start(raw_lines):
    """Return the 0-based index of the first implementation line.

    ``fix`` has no ``Unit``, so it cannot reuse the project splitter and must
    re-derive the boundary here.  The marker knowledge is mirrored from
    ``project._split_st_with_offsets`` (an ``IMPLEMENTATION`` keyword or a
    ``// --- implementation ---`` comment, never allowed to be the very first
    line); keeping it in one helper prevents the two rules drifting again.
    """
    for i, line in enumerate(raw_lines):
        stripped = line.rstrip("\r")
        if stripped == "IMPLEMENTATION" or stripped == "// --- implementation ---":
            if i != 0:
                start = i + 1
                while start < len(raw_lines) and raw_lines[start].rstrip("\r") == "":
                    start += 1
                return start
    return 0


def fix(text, finding):
    """Return *text* with the affected structural indentation corrected.

    HARD INVARIANT: this never changes the number of lines, because the UI
    applies group fixes using line numbers captured at analysis time.

    The whole file text (declaration + implementation) is scanned here, but
    ``_scan`` must run over the implementation slice only: ``base`` is learned
    from the first code line, so a declaration line would otherwise teach it a
    wrong outer indent and the fixer would disagree with ``check`` (which only
    ever sees the implementation section).  Only the source lines represented
    by the finding are changed; continuation lines and all non-leading content
    remain intact.
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

    impl_start = _implementation_start(raw_lines)
    impl_raw = raw_lines[impl_start:]
    impl_clean = clean_lines[impl_start:]

    records = []
    observed_prefixes = []
    for index, actual, expected, mixed, prefix, _level in _scan(impl_raw, impl_clean):
        if prefix and not mixed:
            observed_prefixes.append(prefix)
        records.append((impl_start + index, actual, expected, mixed, prefix))

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
