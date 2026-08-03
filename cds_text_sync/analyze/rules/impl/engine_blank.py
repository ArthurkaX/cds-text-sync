"""
engine_blank.py - Comment/string blanking helpers reused by rules.

These mirror the engine's ``variable_map._blank_noise`` and
``call_tree._trim_string_literals`` without dragging the flat-import engine
modules into the analyzer. Kept here so text rules share one implementation.
"""

from __future__ import annotations


def blank_noise(text):
    """Replace comments and pragmas with spaces, preserving offsets/newlines.

    String literals are respected so a // or (* inside a string is not
    treated as a comment.
    """
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
                out.append(" ")
                i += 2
            continue
        if c == "{":
            while i < n and text[i] != "}":
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append(" ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def trim_strings(text):
    """Replace string-literal contents with spaces (delimiters kept)."""
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
