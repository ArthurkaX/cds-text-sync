"""Helpers for conservative pointer-type checks."""

from __future__ import annotations

import re

from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K


_POINTER = re.compile(r"^POINTER\s+TO\s+(?P<base>.+)$", re.IGNORECASE)


def pointer_base(type_name):
    """Return a normalized pointed-to type, or ``None`` for non-pointers."""
    match = _POINTER.fullmatch((type_name or "").strip())
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group("base").strip()).casefold()


def pointer_members(unit, ctx):
    """Return visible pointer members keyed by case-folded symbol name."""
    result = {}
    for member in decl.all_members(unit):
        name = member.get("name", "")
        base = pointer_base(member.get("type", ""))
        if name and base is not None:
            result[name.casefold()] = (name, base)

    for candidate in ctx.units:
        if candidate.kind not in (K.GVL, K.GVL_PERSISTENT):
            continue
        for member in decl.all_members(candidate):
            name = member.get("name", "")
            base = pointer_base(member.get("type", ""))
            if not name or base is None:
                continue
            key = name.casefold()
            if key not in result:
                result[key] = (name, base)
    return result
