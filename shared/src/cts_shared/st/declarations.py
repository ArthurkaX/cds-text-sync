"""Neutral Structured Text declaration and type helpers.

This module is deliberately self-contained.  The static analyzer operates on
``.st`` projections and must not import the synchronization engine, CODESYS
host modules, or XML tooling just to understand declarations.
"""

import re

from .blanking import blank_noise


SCALAR_TYPES = frozenset(
    {
        "BOOL", "BIT", "BYTE", "WORD", "DWORD", "LWORD",
        "SINT", "USINT", "INT", "UINT", "DINT", "UDINT", "LINT", "ULINT",
        "REAL", "LREAL", "TIME", "LTIME", "TIME_OF_DAY", "TOD", "DATE",
        "DATE_AND_TIME", "DT", "LTIME_OF_DAY", "LTOD", "LDATE",
        "LDATE_AND_TIME", "LDT", "STRING", "WSTRING", "CHAR", "WCHAR",
        "POINTER", "REFERENCE",
    }
)

_VAR_OPENERS = frozenset(
    {
        "VAR_GLOBAL", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP",
        "VAR_STAT", "VAR_EXTERNAL", "VAR_CONFIG", "VAR_INST", "VAR",
    }
)


def _split_top_level(text, separator):
    depth = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char in "'\"":
            quote = char
            i += 1
            while i < len(text):
                if text[i] == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(separator, i):
            if separator != ":" or not text.startswith(":=", i):
                return i
        i += 1
    return -1


def _split_statements(body: str):
    depth = 0
    start = 0
    i = 0
    while i < len(body):
        char = body[i]
        if char in "'\"":
            quote = char
            i += 1
            while i < len(body):
                if body[i] == quote:
                    if i + 1 < len(body) and body[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            yield body[start:i], start
            start = i + 1
        i += 1
    if body[start:].strip():
        yield body[start:], start


def _parse_member_statement(statement: str):
    colon = _split_top_level(statement, ":")
    if colon < 0:
        return None
    left = statement[:colon].strip()
    right = statement[colon + 1:].strip()
    if not left or not right:
        return None
    at_match = re.search(r"(?i)\bAT\b", left)
    if at_match:
        left = left[:at_match.start()].strip()
    names = [part.strip() for part in left.split(",") if part.strip()]
    if not names or any(not re.match(r"^[A-Za-z_]\w*$", name) for name in names):
        return None
    assign = _split_top_level(right, ":=")
    if assign >= 0:
        type_name = right[:assign].strip()
        initial = right[assign + 2:].strip()
    else:
        type_name = right
        initial = ""
    return names, re.sub(r"\s+", " ", type_name), initial


def parse_var_blocks(declaration):
    """Return ``VAR_*`` blocks with parsed member dictionaries."""
    text = blank_noise(declaration or "")
    lines = text.split("\n")
    starts = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1

    blocks = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        tokens = stripped.split()
        opener = tokens[0].upper() if tokens else ""
        if opener not in _VAR_OPENERS:
            index += 1
            continue
        modifiers = [token.upper() for token in tokens[1:]]
        body_start = starts[index] + len(lines[index]) + 1
        end = index + 1
        while end < len(lines) and not lines[end].strip().upper().startswith("END_VAR"):
            end += 1
        body_end = starts[end] if end < len(lines) else len(text)
        members = []
        warnings = []
        for statement, relative in _split_statements(text[body_start:body_end]):
            parsed = _parse_member_statement(statement)
            if not parsed:
                if statement.strip():
                    line = (body_start + relative - text.rfind("\n", 0, body_start + relative))
                    warnings.append("unparsed member near line {0}".format(line))
                continue
            names, type_name, initial = parsed
            member_start = body_start + relative + len(statement) - len(statement.lstrip())
            member_end = body_start + relative + len(statement.rstrip())
            span = _source_span(declaration or "", member_start, member_end)
            line = span["line"]
            for name in names:
                members.append({"name": name, "type": type_name, "scope": opener,
                                "line": line, "initial": initial,
                                "source_span": dict(span)})
        blocks.append({
            "scope": opener, "modifiers": modifiers,
            "retain": "RETAIN" in modifiers,
            "persistent": "PERSISTENT" in modifiers,
            "constant": "CONSTANT" in modifiers,
            "members": members, "warnings": warnings,
        })
        index = end + 1
    return blocks


def _split_enum_items(text: str):
    items = []
    current = []
    depth = 0
    quote = None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        items.append("".join(current).strip())
    return items


_ATTRIBUTE_RE = re.compile(
    r"(?is)\{\s*attribute\s+'([^']+)'(?:\s*:?=\s*([^}]*))?\s*\}"
)


def _declaration_attributes(declaration):
    """Return normalized declaration attributes without discarding values."""
    names = []
    values = {}
    for match in _ATTRIBUTE_RE.finditer(declaration or ""):
        name = re.sub(r"\s+", "_", match.group(1).strip()).lower()
        if not name:
            continue
        names.append(name)
        value = (match.group(2) or "").strip()
        if value:
            values[name] = value
    return names, values


def member_comment(text, name):
    """Find a short trailing comment for a declaration member.

    The declaration parser intentionally blanks comments before parsing.  This
    helper restores only the comment attached to one named member; it never
    returns source code or a whole comment block.
    """
    pattern = re.compile(r"(?i)(?<![A-Za-z0-9_])" + re.escape(name) + r"\b")
    for line in (text or "").splitlines():
        if not pattern.search(line):
            continue
        marker = line.find("//")
        if marker >= 0:
            return line[marker + 2 :].strip()
    return ""


# Kept for older internal callers while the public helper is adopted by
# documentation and analyzer consumers.
_line_comment_for_name = member_comment


def _member_line(text, name):
    pattern = re.compile(r"(?i)(?<![A-Za-z0-9_])" + re.escape(name) + r"\b")
    for number, line in enumerate((text or "").splitlines(), 1):
        if pattern.search(line):
            return number
    return None


def _source_span(text, start, end):
    line = text.count("\n", 0, start) + 1
    column = start - text.rfind("\n", 0, start)
    end_line = text.count("\n", 0, end) + 1
    end_column = end - text.rfind("\n", 0, end)
    return {
        "start": start, "end": end,
        "line": line, "column": column,
        "end_line": end_line, "end_column": end_column,
    }


def parse_dut(declaration):
    """Parse a TYPE declaration into a neutral DUT description."""
    original = declaration or ""
    attribute_names, attribute_values = _declaration_attributes(original)
    strict_attribute = "strict" in attribute_names
    qualified_only = "qualified_only" in attribute_names
    text = blank_noise(original)
    match = re.search(
        r"(?is)\bTYPE\s+([A-Za-z_]\w*)\s*"
        r"(?:\bEXTENDS\s+([A-Za-z_][\w.]*)\s*)?"
        r":(.*?)\bEND_TYPE\b",
        text,
    )
    if not match:
        return None
    name, extends_base, body = match.group(1), match.group(2), match.group(3)
    upper = body.upper()
    for keyword, end_keyword in (("STRUCT", "END_STRUCT"), ("UNION", "END_UNION")):
        if keyword not in upper or end_keyword not in upper:
            continue
        inner = re.search(r"(?is)" + keyword + r"(.*?)" + end_keyword, body)
        fields = []
        warnings = []
        for statement, _ in _split_statements(inner.group(1) if inner else ""):
            parsed = _parse_member_statement(statement)
            if parsed:
                for field in parsed[0]:
                    fields.append({
                        "name": field,
                        "type": parsed[1],
                        "initial": parsed[2],
                "comment": member_comment(original, field),
                        "line": _member_line(original, field),
                    })
            elif statement.strip():
                warnings.append("unparsed {0} member".format(keyword.lower()))
        return {
            "name": name,
            "kind": "union" if keyword == "UNION" else "struct",
            "fields": fields,
            "base": extends_base,
            "extends": extends_base,
            "attributes": attribute_names,
            "attribute_values": attribute_values,
            "qualified_only": qualified_only,
            "strict": strict_attribute,
            "warnings": warnings,
        }

    strict = strict_attribute
    stripped = re.sub(r"(?is)^\s*(?:\{\s*attribute\s+'[^']+'[^}]*\}\s*)+", "", body).strip()
    if stripped.startswith("("):
        close = stripped.rfind(")")
        inside = stripped[1:close] if close >= 0 else ""
        base = stripped[close + 1:].strip().rstrip(";").strip() if close >= 0 else ""
        fields = []
        warnings = []
        last_value = -1
        can_infer = True
        for item in _split_enum_items(inside):
            item = re.sub(r"\{[^}]*\}", " ", item).strip().rstrip(",").strip()
            enum_match = re.match(r"^([A-Za-z_]\w*)\s*(?::=\s*([^,]+))?$", item)
            if not enum_match:
                if item:
                    warnings.append("unparsed enum member")
                continue
            raw_value = enum_match.group(2).strip() if enum_match.group(2) else None
            value = None
            if raw_value is None and can_infer and last_value is not None:
                value = last_value + 1
            elif raw_value is not None:
                try:
                    value = int(raw_value, 0)
                except ValueError:
                    value = None
            if value is not None:
                last_value = value
            elif raw_value is not None:
                can_infer = False
            member_name = enum_match.group(1)
            field = {
                "name": member_name,
                "type": base or "INT",
                "initial": raw_value if raw_value is not None else (str(value) if value is not None else ""),
                "value": value,
                "raw_value": raw_value,
                "comment": member_comment(original, member_name),
                "line": _member_line(original, member_name),
            }
            fields.append(field)
        return {
            "name": name,
            "kind": "enum",
            "fields": fields,
            "base": base or "INT",
            "base_type": base or "INT",
            "strict": strict,
            "qualified_only": qualified_only,
            "attributes": attribute_names,
            "attribute_values": attribute_values,
            "warnings": warnings,
        }
    return {"name": name, "kind": "alias", "fields": [], "base": stripped.rstrip(";").strip()}


def _base_type_name(type_name):
    match = re.match(r"(?i)^(W?STRING)\s*(\(.*\)|\[.*\])?\s*$", type_name.strip())
    if match:
        return match.group(1).upper()
    match = re.match(r"(?i)^(POINTER|REFERENCE)\s+TO\b", type_name.strip())
    return match.group(1).upper() if match else type_name.strip().upper()


def _split_dims(text: str):
    parts, current, depth = [], [], 0
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def classify_type(type_name):
    """Describe an IEC type as scalar, array, or reference."""
    text = (type_name or "").strip()
    match = re.match(r"(?is)^ARRAY\s*\[(.*?)\]\s*OF\s+(.+)$", text)
    if match:
        dimensions = []
        for part in _split_dims(match.group(1)):
            bounds = part.split("..")
            dimensions.append((bounds[0].strip(), bounds[-1].strip()))
        return {"kind": "array", "elem": match.group(2).strip(), "dims": dimensions}
    base = _base_type_name(text)
    if base in SCALAR_TYPES:
        return {"kind": "scalar", "base": base}
    return {"kind": "ref", "name": text}
