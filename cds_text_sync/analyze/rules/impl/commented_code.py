"""
commented_code.py - CTS0001: ST statements that survive inside comments.

Text-level rule (ST_TEXT capability): no declaration or symbol model is
needed, which is exactly why it is the first rule - it exercises the whole
``rule -> Finding -> text/json -> exit code`` path with the smallest possible
surface.

Semantics: a comment is flagged when its content looks executable:

* a top-level ``:=`` (assignment),
* an identifier followed by ``(`` (a call),
* a control-flow keyword that is never ordinary English (RETURN, EXIT,
  END_IF, ...), or a keyword pair (IF..THEN, FOR..TO/DO, WHILE..DO,
  CASE..OF, REPEAT..UNTIL, ELSIF..THEN).

Plain prose comments never match - "for" inside "disabled for TICKET-482" is
not ST. The anchor is the normalised comment content, so reindenting a
comment or inserting lines above it does not change the finding's
fingerprint.
"""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.model import normalize_context
from cds_text_sync.analyze.rules.impl.engine_blank import comment_spans
from cds_text_sync.analyze.rules_api import finding_in

RULE_ID = "CTS0001"
SEVERITY = "suspicious"

_ASSIGN_RE = re.compile(r":=")
_CALL_RE = re.compile(r"\b[A-Za-z_]\w*\s*\(")
# Keywords that are also common English words only count when paired with
# their ST structural partner (IF..THEN, FOR..TO/DO, ...).
_PAIRED_KEYWORDS = [
    (re.compile(r"\bIF\b", re.IGNORECASE), re.compile(r"\bTHEN\b", re.IGNORECASE)),
    (
        re.compile(r"\bFOR\b", re.IGNORECASE),
        re.compile(r"\b(?:TO|DO)\b", re.IGNORECASE),
    ),
    (re.compile(r"\bWHILE\b", re.IGNORECASE), re.compile(r"\bDO\b", re.IGNORECASE)),
    (re.compile(r"\bCASE\b", re.IGNORECASE), re.compile(r"\bOF\b", re.IGNORECASE)),
    (re.compile(r"\bREPEAT\b", re.IGNORECASE), re.compile(r"\bUNTIL\b", re.IGNORECASE)),
    (re.compile(r"\bELSIF\b", re.IGNORECASE), re.compile(r"\bTHEN\b", re.IGNORECASE)),
]
# Keywords that are never ordinary English words: strong signals alone.
_STRONG_KEYWORD_RE = re.compile(
    r"\b(ELSE|RETURN|EXIT|END_IF|END_FOR|END_WHILE|END_CASE|END_REPEAT)\b",
    re.IGNORECASE,
)

_MIN_SIGNIFICANT = 4


def _looks_like_code(content):
    stripped = content.strip()
    if not stripped:
        return False
    significant = re.sub(r"\s+", "", stripped)
    if len(significant) < _MIN_SIGNIFICANT:
        return False
    if _ASSIGN_RE.search(stripped) or _CALL_RE.search(stripped):
        return True
    if _STRONG_KEYWORD_RE.search(stripped):
        return True
    return any(a.search(stripped) and b.search(stripped) for a, b in _PAIRED_KEYWORDS)


def check(unit, ctx):
    """Flag CALLABLE units whose comments still carry executable ST."""
    ctx.capability(Capability.ST_TEXT)
    for start, _end, content in comment_spans(unit.text or ""):
        if not _looks_like_code(content):
            continue
        yield finding_in(
            rule_id=RULE_ID,
            severity=SEVERITY,
            message="commented-out code: " + _trim(content),
            unit=unit,
            offset=start,
            end_offset=start + len(content),
            anchor=normalize_context(content),
            context=_trim(content),
            rule_title="Commented-out code",
        )


def _trim(content, limit=60):
    collapsed = re.sub(r"\s+", " ", content).strip()
    if len(collapsed) > limit:
        return collapsed[: limit - 1] + "\u2026"
    return collapsed
