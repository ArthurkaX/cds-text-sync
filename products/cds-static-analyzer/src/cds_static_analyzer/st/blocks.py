"""blocks.py - Control-flow nesting scanner for the analyzer.

Consumes the blanked implementation text (``Section.text``, item 3) so
keywords inside comments and strings never match. It builds a tree of
IF/CASE/FOR/WHILE/REPEAT blocks and nothing else - no expression parsing, no
symbol resolution. Rules get a reliable view of nesting and keep using
regexes for expressions.

Malformed input is tolerated: an unterminated block is closed at the end of
the section, the root records ``unbalanced = True`` and the offending spots
go into ``root.issues``. The provider surfaces those as Diagnostics rather
than failing the capability (a rule still analyses what did parse).

The scanner itself lives in :mod:`cts_shared.st.blocks`; this module is a thin
wrapper that feeds it the unit's blanked implementation section.
"""

from __future__ import annotations

from cts_shared.st.blocks import Block, scan

from cds_static_analyzer.st.body import body

__all__ = ["Block", "tree"]


def tree(unit):
    """Return the root block node for *unit*'s implementation nesting.

    The root is always returned; it is ``unbalanced`` and carries ``issues``
    when any block was left unterminated (closed at the section end).
    """
    section = body(unit)
    cached = getattr(unit, "_cts_block_tree_cache", None)
    if cached is not None and cached[0] is section:
        return cached[1]
    root = scan(section.text, base=section.base)
    unit._cts_block_tree_cache = (section, root)
    return root
