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


def scan_indentation(raw_lines, clean_lines):
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
        is_case_label = (
            bool(_CASE_LABEL.match(upper))
            and bool(stack)
            and stack[-1]["kind"] == "case"
        )

        if not continuation:
            mixed = " " in prefix and "\t" in prefix
            if is_close or is_branch:
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
                    expected = reference + (step if step is not None else 1)
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
    raw_lines = text.split("\n")
    clean_lines = _clean(text).split("\n")
    records = list(scan_indentation(raw_lines, clean_lines))
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
        for _line_no, index, raw, match, name_end, colon in rows:
            new_prefix = expected_indent + raw[len(match.group("indent")):name_end]
            padding = max(1, expected_colon - len(new_prefix))
            raw_lines[index] = new_prefix + (" " * padding) + raw[colon:]
    return "\n".join(raw_lines)


def format_text(text, declaration=False):
    return format_declarations(text) if declaration else format_implementation(text)


__all__ = [
    "format_declarations",
    "format_implementation",
    "format_text",
    "scan_indentation",
]
