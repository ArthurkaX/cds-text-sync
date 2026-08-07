"""
blanking.py - Comment/string blanking helpers for the analyzer.

The shared implementation lives in :mod:`st_text.blanking` so the analyzer
and the CPython engine use the same lexical behavior without depending on one
another.
"""

from __future__ import annotations

import re

__all__ = [
    "blank_noise",
    "trim_strings",
    "comment_spans",
    "has_intentional_noop_comment",
]

_INTENTIONAL_NOOP_COMMENT = re.compile(
    r"\b(?:wait|waiting|reset|intentionally|reserved|not\s+applicable|"
    r"no[-\s]?op|nothing\s+to\s+do)\b",
    re.IGNORECASE,
)


def blank_noise(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                out.append(d)
                if d == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        out.append(text[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "(" and nxt == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == ")"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
            continue
        if c == "{":
            depth = 1
            out.append(" ")
            i += 1
            while i < n and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def trim_strings(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                if d == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        out.append(" ")
                        i += 2
                        continue
                    out.append(c)
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def comment_spans(text):
    """Return ``(start, end, content)`` for line and block comments."""
    out = []
    i = 0
    n = len(text or "")
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < n:
                if text[i] == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and nxt == "/":
            start = i
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            out.append((start, i, text[start + 2 : i]))
            continue
        if c == "(" and nxt == "*":
            start = i
            i += 2
            content_start = i
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == ")"):
                i += 1
            content_end = i
            if i < n:
                i += 2
            out.append((start, i, text[content_start:content_end]))
            continue
        i += 1
    return out


def has_intentional_noop_comment(text, position):
    """Return whether a nearby comment documents a deliberate no-op.

    Only comments immediately preceding *position* are considered. This is
    intentionally narrow so a stray comment elsewhere cannot hide a blank
    branch.
    """
    for _start, end, content in reversed(comment_spans(text[:position])):
        if text[end:position].strip():
            break
        return bool(_INTENTIONAL_NOOP_COMMENT.search(content))
    return False
