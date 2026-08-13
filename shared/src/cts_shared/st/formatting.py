"""Pure Structured Text whitespace formatting shared by analyzer and IDE.

The module deliberately has no project model or runtime dependencies.  It is
safe to import from the CPython analyzer and from the IronPython CODESYS host.
All transformations preserve the LF/CRLF convention and the number of lines.
"""

from __future__ import print_function

import re

from .blanking import blank_noise, trim_strings


_SECTION_START = re.compile(r"^VAR(?:_INPUT|_OUTPUT|_IN_OUT|_TEMP|_GLOBAL)?\b", re.I)
_SECTION_END = re.compile(r"^END_VAR\b", re.I)
_DECLARATION = re.compile(
    r"^(?P<indent>[ \t]*)(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*:\s*(?P<type>.+?);\s*$"
)
_CLOSER = re.compile(r"^END_(IF|FOR|WHILE|REPEAT|CASE)\b", re.I)
_BRANCH = re.compile(r"^(ELSE|ELSIF)\b", re.I)
_OPENER = re.compile(r"\b(IF|FOR|WHILE|REPEAT|CASE)\b", re.I)
_CASE_LABEL = re.compile(r"^[^;:]+:(?!=)")
_CONTINUATION_START = re.compile(
    r"^(?:[,.)\]}]|(?:AND|OR|XOR)\b|[+\-*/])", re.I
)
_CONDITION_HEADER = re.compile(r"^(?P<indent>[ \t]*)(?P<keyword>IF|ELSIF)\b", re.I)
_HEADER_END = re.compile(r"^(?:THEN|DO|OF)\b", re.I)
_INLINE_ELSE = re.compile(r"^(?P<indent>[ \t]*)ELSE\b", re.I)


def _clean(text):
    # blank_noise keeps strings intact so callers that need to inspect them
    # can still use offsets; indentation must additionally hide their words.
    return trim_strings(blank_noise(text))


def _indent_width(prefix):
    return len(prefix.expandtabs(1))


def _is_continuation(previous, current=""):
    return bool(
        (previous and re.search(r"(?:\b(?:AND|OR|XOR)|:=|,|\(|\.)\s*$", previous, re.I))
        or (current and _CONTINUATION_START.match(current))
    )


def _top_level_logical_operators(clean):
    """Return ranges of top-level ``AND``/``OR``/``XOR`` operators.

    *clean* has the same offsets as the source but strings and comments are
    blanked.  This lets the formatter split a condition without treating an
    operator in a string, comment, or parenthesized expression as a boundary.
    """
    operators = []
    depth = 0
    for match in re.finditer(r"\b(?:AND|OR|XOR)\b", clean, re.I):
        before = clean[:match.start()]
        # Count only punctuation before this candidate.  Quoted/comment text
        # is spaces in *clean*, and each line is handled independently.
        depth = before.count("(") - before.count(")")
        if depth == 0:
            operators.append((match.start(), match.end()))
    return operators


def _expand_condition_headers(raw_lines):
    """Put compound IF/ELSIF headers into a readable multi-line form.

    Only an entire single-line header ending in THEN is expanded.  Incomplete
    or already multi-line expressions are left untouched, which keeps this a
    whitespace-only transformation with no attempt to repair ST syntax.
    """
    expanded = []
    for raw in raw_lines:
        clean = _clean(raw)
        header = _CONDITION_HEADER.match(clean)
        then_match = re.search(r"\bTHEN\b", clean, re.I)
        if header is None or then_match is None:
            expanded.append(raw)
            continue
        # There must be no executable text after THEN.  A trailing comment is
        # fine: blank_noise already turns it into spaces in *clean*.
        if clean[then_match.end():].strip():
            expanded.append(raw)
            continue
        condition_start = header.end()
        condition_end = then_match.start()
        condition_clean = clean[condition_start:condition_end]
        operators = _top_level_logical_operators(condition_clean)
        if not operators:
            expanded.append(raw)
            continue

        indent = raw[:len(raw) - len(raw.lstrip(" \t"))]
        continuation_indent = indent + "    "
        parts = []
        part_start = condition_start
        for operator_start, operator_end in operators:
            boundary = condition_start + operator_start
            parts.append(raw[part_start:boundary].strip())
            part_start = boundary
        parts.append(raw[part_start:condition_end].strip())
        if not all(parts):
            expanded.append(raw)
            continue

        expanded.append(indent + header.group("keyword").upper() + " " + parts[0])
        expanded.extend(continuation_indent + part for part in parts[1:])
        trailing = raw[then_match.end():].rstrip()
        expanded.append(indent + "THEN" + trailing)
    result = []
    for raw in expanded:
        clean = _clean(raw)
        branch = _INLINE_ELSE.match(clean)
        if branch is None or not clean[branch.end():].strip():
            result.append(raw)
            continue
        indent = raw[:len(raw) - len(raw.lstrip(" \t"))]
        result.append(indent + "ELSE")
        result.append(indent + "    " + raw[branch.end():].strip())
    return result


def scan_indentation(raw_lines, clean_lines, default_step=1):
    """Yield ``(index, actual, expected, mixed, prefix, level)`` records."""
    base = None
    step = None
    stack = []
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
        is_close = bool(_CLOSER.match(upper))
        is_branch = bool(_BRANCH.match(upper))
        is_header_end = bool(_HEADER_END.match(upper))
        is_case_label = (
            bool(_CASE_LABEL.match(upper))
            and bool(stack)
            and stack[-1]["kind"] == "case"
        )

        if not continuation:
            mixed = " " in prefix and "\t" in prefix
            if is_close or is_branch or is_header_end:
                expected = stack[-1]["opener_indent"] if stack else base
            elif is_case_label:
                if stack[-1]["label_indent"] is None:
                    stack[-1]["label_indent"] = actual
                expected = stack[-1]["label_indent"]
            elif stack:
                frame = stack[-1]
                reference = (
                    frame["label_indent"]
                    if frame["kind"] == "case" and frame["label_indent"] is not None
                    else frame["opener_indent"]
                )
                if step is None and actual > reference:
                    step = actual - reference
                    expected = actual
                else:
                    expected = reference + (step if step is not None else default_step)
            else:
                if base is None:
                    base = actual
                expected = base
            yield index, actual, expected, mixed, prefix, level

        if is_close:
            if stack:
                stack.pop()
        elif not (is_branch or is_case_label):
            openers = _OPENER.findall(upper)
            if openers and not re.search(
                r"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b", upper
            ):
                # Use the effective indentation of the opener.  This makes
                # the cascade stable when the first nested line is repaired.
                opener_indent = expected if not continuation else actual
                for opener in openers:
                    stack.append(
                        {
                            "opener_indent": opener_indent,
                            "kind": "case" if opener.upper() == "CASE" else "block",
                            "label_indent": None,
                        }
                    )
        previous_code = code


def format_implementation(text):
    original_lines = text.split("\n")
    raw_lines = _expand_condition_headers(original_lines)
    clean_lines = _clean("\n".join(raw_lines)).split("\n")
    # A condition expanded by this formatter has an explicit four-space
    # continuation indent; use that same unit for its newly exposed body.
    default_step = 4 if len(raw_lines) != len(original_lines) else 1
    records = list(scan_indentation(raw_lines, clean_lines, default_step=default_step))
    observed = [record[4] for record in records if record[4] and not record[3]]
    use_tabs = sum(value.count("\t") for value in observed) > sum(
        value.count(" ") for value in observed
    )

    def prefix_for(expected):
        if expected is None or expected <= 0:
            return ""
        for prefix in observed:
            if _indent_width(prefix) == expected:
                return prefix
        return ("\t" if use_tabs else " ") * expected

    for index, prefix, actual, expected, mixed, _level in (
        (record[0], record[4], record[1], record[2], record[3], record[5])
        for record in records
    ):
        if mixed or actual != expected:
            raw_lines[index] = prefix_for(expected) + raw_lines[index][len(prefix):]
    return "\n".join(raw_lines)


def _declaration_groups(raw_lines, clean_lines):
    in_section = False
    group = []
    for index, clean_raw in enumerate(clean_lines):
        clean = clean_raw.rstrip("\r")
        stripped = clean.strip()
        if not in_section:
            if _SECTION_START.match(stripped):
                in_section = True
            continue
        if _SECTION_END.match(stripped) or not stripped:
            if group:
                yield group
            group = []
            if _SECTION_END.match(stripped):
                in_section = False
            continue
        match = _DECLARATION.match(clean)
        if match:
            colon = clean.find(":")
            group.append(
                (index + 1, index, raw_lines[index], match, match.end("names"), colon)
            )
        elif stripped.startswith(("//", "(*", "{", "(")):
            continue
        else:
            if group:
                yield group
            group = []
    if group:
        yield group


def _trailing_comment_start(line, after=0):
    """Return the first comment delimiter after a declaration's type.

    A comment marker inside a quoted default value is not a comment.  ST
    doubles quotes to escape them, so skip those pairs while looking for a
    trailing ``//`` or ``(*`` comment.
    """
    index = max(0, after)
    while index < len(line):
        char = line[index]
        if char in ("'", '"'):
            quote = char
            index += 1
            while index < len(line):
                if line[index] == quote:
                    if index + 1 < len(line) and line[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if line[index:index + 2] in ("//", "(*"):
            return index
        index += 1
    return -1


def format_declarations(text, target_lines=None):
    """Align declaration groups, optionally limiting them to source lines."""
    raw_lines = text.split("\n")
    clean_lines = blank_noise(text).split("\n")
    targets = set(target_lines) if target_lines is not None else None
    for rows in _declaration_groups(raw_lines, clean_lines):
        if len(rows) < 2:
            continue
        if targets is not None and not targets.intersection(row[0] for row in rows):
            continue
        expected_indent = rows[0][3].group("indent")
        expected_colon = (
            max(
                len(expected_indent) + row[4] - len(row[3].group("indent"))
                for row in rows
            )
            + 1
        )
        formatted_rows = []
        for _line_no, index, raw, match, name_end, colon in rows:
            new_prefix = expected_indent + raw[len(match.group("indent")):name_end]
            padding = max(1, expected_colon - len(new_prefix))
            formatted = new_prefix + (" " * padding) + raw[colon:]
            comment_start = _trailing_comment_start(
                formatted, after=len(new_prefix) + padding
            )
            formatted_rows.append((index, formatted, comment_start))

        comment_column = max(
            (len(formatted[:comment_start].rstrip()) + 2
             for _index, formatted, comment_start in formatted_rows
             if comment_start >= 0),
            default=-1,
        )
        for index, formatted, comment_start in formatted_rows:
            if comment_start >= 0:
                comment = formatted[comment_start:]
                formatted = (
                    formatted[:comment_start].rstrip()
                    + (" " * max(2, comment_column - len(formatted[:comment_start].rstrip())))
                    + comment
                )
            raw_lines[index] = formatted
    return "\n".join(raw_lines)


def format_text(text, declaration=False):
    return format_declarations(text) if declaration else format_implementation(text)


__all__ = [
    "format_declarations",
    "format_implementation",
    "format_text",
    "scan_indentation",
]
