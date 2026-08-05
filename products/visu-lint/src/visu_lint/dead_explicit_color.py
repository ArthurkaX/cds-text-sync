"""VISU001: validate ignored ExplicitColor literals in generated XML."""

from __future__ import annotations

import re

RULE_ID = "VISU001"
_MEMBER_TYPE = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}"
_COLOR_TYPE = "{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}"
_MEMBER_OPEN_RE = re.compile(
    r'<Single Type="' + re.escape(_MEMBER_TYPE) + r'" Method="IArchivable">'
)
_EXPLICIT_RE = re.compile(r'<Single Name="ExplicitColor" Type="int">(-?\d+)</Single>')
_LIVE_NAMED_RE = re.compile(
    r'<Single Name="NamedColor" Type="' + re.escape(_COLOR_TYPE) + r'" Method="IArchivable">'
)


def lint(text: str, path: str = "") -> list[dict]:
    """Return JSON-ready VISU001 findings for one generated XML document."""
    findings = []
    for start, end in _member_blocks(text or ""):
        inner = text[start:end]
        explicit = _EXPLICIT_RE.search(inner)
        if explicit is None or _LIVE_NAMED_RE.search(inner) is None:
            continue
        value = explicit.group(1)
        canonical = _canonical_name(inner)
        offset = start + explicit.start(1)
        line = (text or "").count("\n", 0, offset) + 1
        column = offset - (text or "").rfind("\n", 0, offset)
        findings.append(
            {
                "rule_id": RULE_ID,
                "severity": "error",
                "message": (
                    f"ExplicitColor {value} is ignored: a live NamedColor"
                    + (f" ({canonical})" if canonical else "")
                    + " takes precedence; generated XML must not carry both"
                ),
                "location": {"path": path, "line": line, "column": column},
                "anchor": f"{value}:{canonical or ''}",
            }
        )
    return findings


def _member_blocks(text: str):
    pos = 0
    while True:
        match = _MEMBER_OPEN_RE.search(text, pos)
        if match is None:
            return
        start, depth, index = match.start(), 1, match.end()
        while index < len(text):
            next_open, next_close = text.find("<Single", index), text.find("</Single>", index)
            if next_close < 0:
                break
            if 0 <= next_open < next_close:
                depth, index = depth + 1, next_open + len("<Single")
            else:
                depth -= 1
                if depth == 0:
                    yield start, next_close + len("</Single>")
                    break
                index = next_close + len("</Single>")
        pos = start + 1


def _canonical_name(text: str) -> str:
    match = re.search(r'<Single Name="CanonicalName" Type="string">([^<]*)</Single>', text)
    return match.group(1) if match else ""
