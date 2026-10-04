"""
blanking.py - Comment/string blanking helpers for the analyzer.

The implementation lives in :mod:`cts_shared.st.blanking`; this module re-exports
it so the analyzer's rule modules keep their existing import path. Adding a
second copy is what used to let the two drift apart.
"""

from __future__ import print_function

from cts_shared.st.blanking import (  # noqa: F401 - re-exported
    blank_noise,
    comment_spans,
    has_intentional_noop_comment,
)

__all__ = [
    "blank_noise",
    "trim_strings",
    "comment_spans",
    "has_intentional_noop_comment",
]


def trim_strings(text):
    """Blank string contents, keeping the surrounding quotes.

    Kept local for now: its escaped-quote handling differs from the shared copy
    (it writes one space where the shared copy writes two), so switching the
    analyzer rule that calls it is a separate, behaviour-changing step.
    """
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
