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
"""

from __future__ import annotations

import re

from cds_static_analyzer.st.body import body

# Word-boundary keywords that delimit blocks and their arms, plus the
# separators that finish a header (THEN/DO/TO/BY) or enter label territory
# (OF). Case labels are captured separately as ``word:`` (never ``:=``).
_KEYWORDS = re.compile(
    r"\b(?:IF|CASE|FOR|WHILE|REPEAT|ELSIF|ELSE|END_IF|END_CASE|"
    r"END_FOR|END_WHILE|END_REPEAT|UNTIL|THEN|DO|TO|BY|OF)\b",
    re.IGNORECASE,
)
# A case label is a comma-separated list of tokens ending in ``:`` (never
# ``:=``, which is an assignment). Captured as one label so ``2, 3:`` is a
# single branch, not three.
_LABEL = re.compile(
    r"[^\s:=\n]+(?:\s*,\s*[^\s:=\n]+)*\s*:(?!=)", re.MULTILINE
)

_OPENERS = {"IF", "CASE", "FOR", "WHILE", "REPEAT"}
_CLOSERS = {
    "END_IF": "IF",
    "END_CASE": "CASE",
    "END_FOR": "FOR",
    "END_WHILE": "WHILE",
    "END_REPEAT": "REPEAT",
}


class Block:
    """One control-flow block. Offsets are absolute (into ``unit.text``)."""

    def __init__(self, kind, start, depth, at):
        self.kind = kind
        self._start = start  # local offset, converted lazily via ``at``
        self._end = None
        self.depth = depth
        self.parent = None
        self.children = []
        self._branches = []  # (label, start_local, end_local)
        self._at = at
        self._pending_start = None
        self._pending_label = None
        self._in_labels = False
        self.header_text = ""
        # Root-only bookkeeping.
        self.unbalanced = False
        self.issues = []

    @property
    def start_offset(self):
        return self._at(self._start)

    @property
    def end_offset(self):
        return self._at(self._end) if self._end is not None else None

    @property
    def branches(self):
        """``(label, start_offset, end_offset)`` for IF/ELSIF/ELSE arms or
        CASE labels, in source order. ``label`` is raw header/label text."""
        return [(label, self._at(s), self._at(e)) for (label, s, e) in self._branches]


def _tokens(text):
    """Yield ``(offset, word)`` for block keywords and case-label candidates,
    in source order. Keywords win over a label candidate at the same spot."""
    i = 0
    n = len(text)
    while i < n:
        km = _KEYWORDS.match(text, i)
        if km:
            yield km.start(), km.group().upper()
            i = km.end()
            continue
        lm = _LABEL.match(text, i)
        if lm:
            yield lm.start(), lm.group()
            i = lm.end()
            continue
        i += 1


def tree(unit):
    """Return the root block node for *unit*'s implementation nesting.

    The root is always returned; it is ``unbalanced`` and carries ``issues``
    when any block was left unterminated (closed at the section end).
    """
    section = body(unit)
    cached = getattr(unit, "_cts_block_tree_cache", None)
    if cached is not None and cached[0] is section:
        return cached[1]
    root = Block("ROOT", 0, 0, section.at)
    if not section:
        unit._cts_block_tree_cache = (section, root)
        return root
    text = section.text
    n = len(text)
    stack = [root]
    issues = []

    def finalize(block, end):
        if block._pending_start is not None:
            label = block._pending_label if block._pending_label is not None else ""
            block._branches.append((label, block._pending_start, end))
            block._pending_start = None

    for offset, word in _tokens(text):
        top = stack[-1]

        if word in _OPENERS:
            block = Block(word, offset, top.depth + 1, section.at)
            block.parent = top
            top.children.append(block)
            # Only IF/CASE carry branches; the opening keyword starts the
            # first IF arm, and the CASE body (before its labels) is tracked
            # until the selector is dropped at OF.
            if word in ("IF", "CASE"):
                block._pending_start = offset
            stack.append(block)
            continue

        if word in _CLOSERS:
            expected = _CLOSERS[word]
            if top.kind != expected:
                issues.append((section.at(offset), f"{word} without a matching {expected}"))
                continue
            finalize(top, offset)
            top._end = offset + len(word)
            stack.pop()
            continue

        if word == "THEN":
            # Ends an IF/ELSIF header; the arm label is that header text.
            if top.kind == "IF" and top._pending_start is not None:
                top.header_text = text[top._pending_start : offset].strip()
                top._pending_label = top.header_text
            continue

        if word == "OF":
            if top.kind == "CASE":
                top._in_labels = True
                top._pending_start = None  # the selector is not a branch
            continue

        if word in ("ELSE", "ELSIF"):
            if top.kind == "IF":
                finalize(top, offset)
                top._pending_start = offset
                top._pending_label = None if word == "ELSIF" else "ELSE"
            elif top.kind == "CASE" and word == "ELSE":
                finalize(top, offset)
                top._pending_start = offset
                top._pending_label = "ELSE"
            else:
                issues.append((section.at(offset), f"{word} outside a block"))
            continue

        if word == "UNTIL":
            continue  # ends a REPEAT body; not a branch

        # Remaining tokens are case-label candidates ("word:").
        if top.kind == "CASE" and top._in_labels:
            finalize(top, offset)
            top._pending_start = offset
            top._pending_label = word.rstrip(":").strip()

    while len(stack) > 1:  # unterminated blocks close at the section end
        block = stack.pop()
        finalize(block, n)
        block._end = n
        root.unbalanced = True
        issues.append((block.start_offset, f"unterminated {block.kind} block"))

    root.issues = issues
    unit._cts_block_tree_cache = (section, root)
    return root
