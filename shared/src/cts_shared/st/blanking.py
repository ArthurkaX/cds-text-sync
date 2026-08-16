"""
blanking.py - Comment/string blanking helpers for the analyzer.

The shared implementation lives in :mod:`st_text.blanking` so the analyzer
and the CPython engine use the same lexical behavior without depending on one
another.
"""

from __future__ import print_function

import re

__all__ = ["blank_noise", "trim_strings", "comment_spans"]


# Regex to find the next special character that starts a comment, string, or
# pragma. This lets us skip over large chunks of plain text in one slice
# instead of looping character-by-character, which is critical for IronPython
# performance on large files.
_SPECIAL = re.compile(r"['\"/({]")


def blank_noise(text):
    """Blank comments and pragmas, preserving newlines and string contents.

    Optimized for IronPython: uses regex to skip over plain text regions
    instead of looping character-by-character, which is 10-100x faster on
    large files.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        # Find the next special character
        m = _SPECIAL.search(text, i)
        if m is None:
            # No more special characters - copy the rest
            out.append(text[i:])
            break
        # Copy plain text up to the special character
        out.append(text[i:m.start()])
        i = m.start()
        c = text[i]
        if c in ("'", '"'):
            # String literal - preserve contents
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
        elif c == "/":
            if i + 1 < n and text[i + 1] == "/":
                # Line comment - blank until newline
                j = text.find("\n", i)
                if j < 0:
                    # Comment extends to end of file
                    out.append(" " * (n - i))
                    i = n
                else:
                    out.append(" " * (j - i))
                    i = j
            else:
                # Not a comment - copy the slash
                out.append(c)
                i += 1
        elif c == "(":
            if i + 1 < n and text[i + 1] == "*":
                # Block comment - blank until *) but preserve newlines so
                # downstream line numbering stays correct.
                start = i
                j = i + 2
                while j < n:
                    if text[j] == "*" and j + 1 < n and text[j + 1] == ")":
                        # Found the end - blank the span, keeping newlines.
                        span = text[start:j + 2]
                        lines = span.split("\n")
                        out.append("\n".join(" " * len(line) for line in lines))
                        i = j + 2
                        break
                    j += 1
                else:
                    # Unterminated comment - blank to end, keeping newlines.
                    span = text[start:]
                    lines = span.split("\n")
                    out.append("\n".join(" " * len(line) for line in lines))
                    i = n
            else:
                # Not a comment - copy the paren
                out.append(c)
                i += 1
        elif c == "{":
            # Pragma - blank until matching }
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
    return "".join(out)

def blanked(text):
    """The canonical blanking pipeline: ``trim_strings(blank_noise(text))``.

    This composition - not ``blank_noise`` alone - is what the block scanner
    and statement splitter consume. Keeping it in one place guarantees the
    analyzer and the FSM extractor see identical text.
    """
    return trim_strings(blank_noise(text))


_STRING_START = re.compile(r"['\"]")


def trim_strings(text):
    """Blank string contents, keeping the surrounding quotes.

    Optimized for IronPython: uses regex to skip plain text regions.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        m = _STRING_START.search(text, i)
        if m is None:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        i = m.start()
        quote = text[i]
        out.append(quote)
        i += 1
        # Inside the string: blank content, keep the closing quote.
        while i < n:
            d = text[i]
            if d == quote:
                if i + 1 < n and text[i + 1] == quote:
                    # Escaped quote: two quote chars become two spaces.
                    out.append("  ")
                    i += 2
                    continue
                out.append(quote)
                i += 1
                break
            out.append(" ")
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
