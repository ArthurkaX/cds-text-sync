"""Shared project-global read/write discovery.

The analyzer and documentation generator must agree about what a global access
means.  This module deliberately returns source-backed occurrences rather than
diagnostic messages, so consumers can attach their own task or rule context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.body import body
from cds_static_analyzer.model import line_col_of


_PATH = re.compile(
    r"\b(?P<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\b"
)


@dataclass(frozen=True)
class GlobalAccess:
    unit: object
    global_unit: object
    member: dict
    target: str
    write: bool
    offset: int
    end_offset: int
    line: int | None
    column: int | None
    # Qualified GVL paths are source-explicit; bare names are resolved by
    # project-wide uniqueness and therefore remain heuristic.
    confidence: str = "high"


class GlobalAccessIndex:
    """Resolve qualified and unqualified project-global occurrences."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self._qualified = {}
        self._bare = {}
        self._ambiguous = set()
        self._build_globals()

    def _build_globals(self):
        for unit in self.snapshot.units:
            if unit.kind not in (K.GVL, K.GVL_PERSISTENT):
                continue
            for member in decl.all_members(unit):
                name = str(member.get("name") or "")
                if not name:
                    continue
                key = f"{unit.qualified_name}.{name}".casefold()
                self._qualified[key] = (unit, member)
                bare = name.casefold()
                if bare in self._bare and self._bare[bare][0].id != unit.id:
                    self._ambiguous.add(bare)
                else:
                    self._bare[bare] = (unit, member)

    def _resolve(self, parts, local_names):
        if not parts:
            return None
        if len(parts) == 1:
            bare = parts[0].casefold()
            if bare in local_names or bare in self._ambiguous:
                return None
            return self._bare.get(bare)
        first = parts[0].casefold()
        if first in local_names:
            return None
        for index in range(len(parts), 1, -1):
            candidate = ".".join(parts[:index]).casefold()
            found = self._qualified.get(candidate)
            if found is not None:
                return found
        return None

    def accesses_for(self, unit):
        """Yield resolved global accesses in implementation order."""
        if unit.kind not in K.CALLABLE:
            return ()
        section = body(unit)
        if not section:
            return ()
        local_names = {
            str(member.get("name") or "").casefold()
            for member in decl.all_members(unit)
            if member.get("name")
        }
        found = []
        for match in _PATH.finditer(section.text):
            raw = match.group("path")
            parts = [part.strip() for part in raw.split(".")]
            resolved = self._resolve(parts, local_names)
            if resolved is None:
                continue
            global_unit, member = resolved
            absolute = section.at(match.start())
            end_offset = section.at(match.end())
            line, column = line_col_of(unit.text, absolute)
            write = bool(re.match(r"\s*:=", section.text[match.end() :]))
            found.append(GlobalAccess(
                unit=unit,
                global_unit=global_unit,
                member=member,
                target=".".join(parts),
                write=write,
                offset=absolute,
                end_offset=end_offset,
                line=line,
                column=column,
                confidence="high" if len(parts) > 1 else "medium",
            ))
        return tuple(found)

    def all_accesses(self):
        for unit in self.snapshot.units:
            yield from self.accesses_for(unit)


def global_access_index(ctx):
    """Return one cached index for an analyzer context."""
    cached = getattr(ctx, "_cts_global_access_index", None)
    if cached is None:
        cached = GlobalAccessIndex(ctx.snapshot)
        ctx._cts_global_access_index = cached
    return cached


__all__ = ["GlobalAccess", "GlobalAccessIndex", "global_access_index"]
