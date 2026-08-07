"""Small project-wide helpers for function-block lifecycle rules."""

from __future__ import annotations

from cds_static_analyzer.st import decl
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.st.library import is_known_function_block


def function_block_types(ctx):
    """Return normalized names of project and standard FB types."""
    names = {name.casefold() for name in (
        "TON", "TOF", "TP", "R_TRIG", "F_TRIG", "SR", "RS", "CTU", "CTD", "CTUD",
        "PID", "INTEGRAL", "DERIVATIVE",
    )}
    for unit in ctx.units:
        if unit.kind != K.FUNCTION_BLOCK:
            continue
        qualified = unit.qualified_name.casefold()
        names.add(qualified)
        names.add(qualified.rsplit(".", 1)[-1])
    return names


def is_function_block_type(type_name, names):
    """Return whether a declared type is a known FB type."""
    text = (type_name or "").strip().casefold()
    if not text:
        return False
    return (
        text in names
        or text.rsplit(".", 1)[-1] in names
        or is_known_function_block(text)
    )


def global_members(ctx):
    """Return global members keyed by case-folded symbol name.

    Ambiguous duplicate names are removed: a rule must not guess which GVL a
    bare identifier refers to.
    """
    found = {}
    ambiguous = set()
    for unit in ctx.units:
        if unit.kind not in (K.GVL, K.GVL_PERSISTENT):
            continue
        for member in decl.all_members(unit):
            name = member.get("name", "")
            if not name:
                continue
            key = name.casefold()
            if key in found and found[key][0].id != unit.id:
                ambiguous.add(key)
            else:
                found[key] = (unit, member)
    return {key: value for key, value in found.items() if key not in ambiguous}
