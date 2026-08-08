"""
external_refs.py - Symbol paths referenced from the XML side of project-view.

Visualizations, text lists and the task configuration bind PLC symbols by
name. Those files are not part of the ST snapshot (build_st_snapshot reads
only .st), so a symbol read exclusively from a screen looks dead to every
ST-only rule. This index closes that gap without pulling XML into the unit
model.

This is a deliberately textual match: dotted identifiers are extracted with a
regular expression over the raw file bytes. It can produce false NEGATIVES for
the rules that consume it - a symbol wrongly considered used because its name
happens to appear in an XML attribute or unrelated text. That is the correct
direction of error for a ``suspicious`` rule that would otherwise fail CI on a
legitimate HMI binding: better to under-report (silence a true dead output)
than to over-report and break a build whose visualization genuinely reads the
symbol. An XML file that cannot be read is skipped and counted, never raised,
so a scan can never break an analysis run.
"""

from __future__ import annotations

import os
import re

# A dotted identifier path of at least two segments, each an IEC identifier
# optionally followed by an array index. Array indexes are captured so they can
# be stripped before splitting: ``arr[0].done`` must become ``arr`` +
# ``done``, not ``arr[0]`` + ``done``.
_PATH = re.compile(
    r"(?P<path>[A-Za-z_]\w*(?:\[[^\]\n]*\])?(?:\s*\.\s*[A-Za-z_]\w*(?:\[[^\]\n]*\])?)+)",
    re.IGNORECASE,
)

# Removes an array-index suffix from a single identifier segment. The index
# body may itself contain a dot (``arr[1..10]``), so stripping happens before
# the segment is split on dots.
_INDEX = re.compile(r"\[[^\]]*\]")

# Only files that might carry a symbol binding are scanned.
_SUFFIX = ".xml"


class ExternalReferences:
    """Symbol paths referenced from the XML side of project-view.

    Visualizations, text lists and the task configuration bind PLC symbols by
    name. Those files are not part of the ST snapshot (build_st_snapshot reads
    only .st), so a symbol read exclusively from a screen looks dead to every
    ST-only rule. This index closes that gap without pulling XML into the unit
    model.
    """

    def __init__(self, root):
        # Construction never does IO: the walk happens on the first query.
        self.root = root
        self._index = None
        # Number of XML files that could not be read during the lazy scan.
        # Exposed for a future diagnostic; a scan never raises, so it is not
        # otherwise visible to the analysis run.
        self.unreadable_count = 0

    def is_referenced(self, owner_path, member):
        """True if *owner_path*.*member* appears in the XML side of the tree.

        Both arguments are casefolded (IEC identifiers are case-insensitive).
        The index is built lazily on the first query and cached for the rest
        of the instance's lifetime.
        """
        index = self._ensure_built()
        return (owner_path.casefold(), member.casefold()) in index

    def _ensure_built(self):
        if self._index is not None:
            return self._index
        index = set()
        root = self.root
        if root and os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                # Hidden directories are not part of the exported project view
                # (mirror build_st_snapshot).
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for filename in filenames:
                    if not filename.lower().endswith(_SUFFIX):
                        continue
                    self._scan_file(index, os.path.join(dirpath, filename))
        self._index = index
        return index

    def _scan_file(self, index, full_path):
        try:
            with open(full_path, encoding="utf-8-sig", errors="replace") as fh:
                text = fh.read()
        except OSError:
            # A single unreadable XML must never break an analysis run; count
            # it for a future diagnostic instead.
            self.unreadable_count += 1
            return
        for match in _PATH.finditer(text):
            # Array indexes are stripped from the whole path *before* it is
            # split, because an index body may itself contain a dot
            # (``arr[1..10].done``) and would otherwise be torn into segments.
            # ``arr[0].done`` and ``arr.done`` collapse onto the same key.
            segments = [
                part.strip() for part in _INDEX.sub("", match.group("path")).split(".")
            ]
            segments = [part for part in segments if part]
            if len(segments) < 2:
                continue
            member = segments[-1]
            # CODESYS bindings are often written relative to a program or a
            # GVL, so record both the fully qualified owner and the immediate
            # owner. Both keys are casefolded.
            index.add((".".join(segments[:-1]).casefold(), member.casefold()))
            index.add((segments[-2].casefold(), member.casefold()))
