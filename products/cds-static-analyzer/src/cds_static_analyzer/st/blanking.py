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
    trim_strings,
)

__all__ = [
    "blank_noise",
    "trim_strings",
    "comment_spans",
    "has_intentional_noop_comment",
]
