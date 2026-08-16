# -*- coding: utf-8 -*-
"""Line-aware diff model for the Project_fmt preview.

Replaces index-to-index comparison with a pure diff over line sequences.
``difflib.SequenceMatcher(..., autojunk=False)`` is available in Python 2.7
and produces insert/delete/replace opcodes; the opcodes are converted into
immutable preview rows so every view (changed-line count, navigation
positions, side-by-side rows, line-by-line rows) derives from one model.

Performance safeguards:

* ``SequenceMatcher`` is disabled above a tested worst-case threshold; a
  prefix/suffix plus changed-middle representation is used instead so a
  pathological document cannot freeze the IDE.
* Character-level highlighting is computed only inside bounded ``replace``
  blocks, never across the complete document.

The module is IronPython 2.7 safe (no f-strings, no annotations, no
dataclasses, no Python 3-only builtin keywords).
"""

from __future__ import print_function

import difflib

# Above these thresholds the full SequenceMatcher is replaced by a
# prefix/suffix + changed-middle representation.  The values are chosen so a
# representative large POU (a few thousand lines) stays well inside the
# budget while a pathological repeated-line document cannot stall the UI.
MAX_DIFF_LINES = 20000
MAX_DIFF_CHARS = 2 * 1024 * 1024
MAX_REPLACE_BLOCK_LINES = 400

# Row kinds, mirroring SequenceMatcher opcodes.
EQUAL = "equal"
DELETE = "delete"
INSERT = "insert"
REPLACE = "replace"


class DiffRow(object):
    """One immutable preview row.

    ``old``/``new`` hold the line text ("" for a side without a line);
    ``old_no``/``new_no`` are 1-based source line numbers (0 = absent).
    """

    __slots__ = ("kind", "old", "new", "old_no", "new_no")

    def __init__(self, kind, old, new, old_no=0, new_no=0):
        self.kind = kind
        self.old = old
        self.new = new
        self.old_no = old_no
        self.new_no = new_no

    def __repr__(self):
        return "DiffRow({0}, {1!r} -> {2!r})".format(self.kind, self.old, self.new)


class DiffModel(object):
    """The single source of truth for one before/after comparison."""

    def __init__(self, before, after, reduced=False):
        self.before = before or ""
        self.after = after or ""
        self.reduced = reduced
        self.rows = self._build_rows(self.before, self.after, reduced)
        self.changed_count = sum(1 for row in self.rows if row.kind != EQUAL)
        self.changed_lines = self._changed_line_count()
        self._changed_rows = [
            index for index, row in enumerate(self.rows) if row.kind != EQUAL
        ]

    # -- construction ----------------------------------------------------

    def _build_rows(self, before, after, reduced):
        left = before.split("\n")
        right = after.split("\n")
        if (
            reduced
            or len(left) + len(right) > MAX_DIFF_LINES
            or (len(before) + len(after) > MAX_DIFF_CHARS)
        ):
            return self._prefix_suffix_rows(left, right)
        matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
        rows = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == EQUAL:
                for offset in range(i2 - i1):
                    rows.append(
                        DiffRow(
                            EQUAL,
                            left[i1 + offset],
                            right[j1 + offset],
                            i1 + offset + 1,
                            j1 + offset + 1,
                        )
                    )
            elif tag == DELETE:
                for offset in range(i2 - i1):
                    rows.append(
                        DiffRow(DELETE, left[i1 + offset], "", i1 + offset + 1, 0)
                    )
            elif tag == INSERT:
                for offset in range(j2 - j1):
                    rows.append(
                        DiffRow(INSERT, "", right[j1 + offset], 0, j1 + offset + 1)
                    )
            else:  # replace
                for offset in range(max(i2 - i1, j2 - j1)):
                    old = left[i1 + offset] if offset < i2 - i1 else ""
                    new = right[j1 + offset] if offset < j2 - j1 else ""
                    rows.append(
                        DiffRow(
                            REPLACE,
                            old,
                            new,
                            i1 + offset + 1 if offset < i2 - i1 else 0,
                            j1 + offset + 1 if offset < j2 - j1 else 0,
                        )
                    )
        return rows

    def _prefix_suffix_rows(self, left, right):
        """Reduced representation: equal prefix, changed middle, equal suffix."""
        prefix = 0
        while (
            prefix < len(left) and prefix < len(right) and left[prefix] == right[prefix]
        ):
            prefix += 1
        suffix = 0
        while (
            suffix < len(left) - prefix
            and suffix < len(right) - prefix
            and left[len(left) - 1 - suffix] == right[len(right) - 1 - suffix]
        ):
            suffix += 1
        rows = []
        for offset in range(prefix):
            rows.append(
                DiffRow(EQUAL, left[offset], right[offset], offset + 1, offset + 1)
            )
        left_mid = left[prefix : len(left) - suffix] if suffix else left[prefix:]
        right_mid = right[prefix : len(right) - suffix] if suffix else right[prefix:]
        for offset in range(max(len(left_mid), len(right_mid))):
            old = left_mid[offset] if offset < len(left_mid) else ""
            new = right_mid[offset] if offset < len(right_mid) else ""
            rows.append(
                DiffRow(
                    REPLACE,
                    old,
                    new,
                    prefix + offset + 1 if offset < len(left_mid) else 0,
                    prefix + offset + 1 if offset < len(right_mid) else 0,
                )
            )
        for offset in range(suffix):
            index = len(left) - suffix + offset
            rows.append(DiffRow(EQUAL, left[index], right[index], index + 1, index + 1))
        return rows

    # -- derived views ---------------------------------------------------

    def _changed_line_count(self):
        """Number of source lines touched by any non-equal row."""
        old_lines = set()
        new_lines = set()
        for row in self.rows:
            if row.kind == EQUAL:
                continue
            if row.old_no:
                old_lines.add(row.old_no)
            if row.new_no:
                new_lines.add(row.new_no)
        return len(old_lines | new_lines)

    def changed_indexes(self, side="old"):
        """Sorted 0-based line indexes of changed lines on one side."""
        result = set()
        for row in self.rows:
            if row.kind == EQUAL:
                continue
            number = row.old_no if side == "old" else row.new_no
            if number:
                result.add(number - 1)
        return sorted(result)

    def navigation_groups(self):
        """List of (start_row, end_row) indexes of contiguous change groups."""
        groups = []
        start = None
        previous = -2
        for index in self._changed_rows:
            if start is None or index != previous + 1:
                if start is not None:
                    groups.append((start, previous))
                start = index
            previous = index
        if start is not None:
            groups.append((start, previous))
        return groups

    def character_spans(self, row_index):
        """Bounded character-level highlight spans for one replace row.

        Returns ``(old_start, old_end, new_start, new_end)`` or None when the
        row is not a bounded replace block.
        """
        row = self.rows[row_index]
        if row.kind != REPLACE:
            return None
        if len(self._changed_rows) > MAX_REPLACE_BLOCK_LINES:
            return None
        old = row.old
        new = row.new
        prefix = 0
        while prefix < len(old) and prefix < len(new) and old[prefix] == new[prefix]:
            prefix += 1
        old_end = len(old)
        new_end = len(new)
        while (
            old_end > prefix
            and new_end > prefix
            and old[old_end - 1] == new[new_end - 1]
        ):
            old_end -= 1
            new_end -= 1
        return prefix, old_end, prefix, new_end


def diff_lines(before, after, reduced=False):
    """Return the list of :class:`DiffRow` for one comparison."""
    return DiffModel(before, after, reduced=reduced).rows


__all__ = [
    "DiffModel",
    "DiffRow",
    "diff_lines",
    "EQUAL",
    "DELETE",
    "INSERT",
    "REPLACE",
    "MAX_DIFF_LINES",
    "MAX_DIFF_CHARS",
    "MAX_REPLACE_BLOCK_LINES",
]
