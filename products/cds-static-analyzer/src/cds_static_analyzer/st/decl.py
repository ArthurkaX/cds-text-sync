"""Declaration layer for the analyzer (DECLARATIONS capability)."""

from __future__ import annotations

from cds_static_analyzer.st.declarations import parse_dut, parse_var_blocks

PERSISTENT_SCOPES = ("VAR_GLOBAL",)


def var_blocks(unit):
    """VAR_* blocks of a unit's declaration, in order.

    Returns [] for units without a declaration (actions, XML units) or whose
    declaration does not parse.
    """
    decl = unit.declaration
    cached = getattr(unit, "_cts_var_blocks_cache", None)
    if cached is not None and cached[0] is decl:
        return cached[1]
    parsed = parse_var_blocks_text(decl)
    # A Unit is immutable for the lifetime of a snapshot.  Keep the parsed
    # declaration on that Unit so rules do not re-parse the same VAR blocks
    # dozens of times (project rules can otherwise turn this into O(files²)).
    unit._cts_var_blocks_cache = (decl, parsed)
    return parsed


def parse_var_blocks_text(text):
    """parse_var_blocks over a raw declaration text (never raises)."""
    if not text:
        return []
    try:
        return parse_var_blocks(text)
    except Exception:
        return []


def members_in_scope(unit, scopes):
    """Members declared in the given VAR_* scopes of *unit*.

    Each member is a dict from ``parse_var_blocks``: {name, type, scope,
    line, initial}.
    """
    out = []
    for block in var_blocks(unit):
        if block["scope"] in scopes:
            out.extend(block["members"])
    return out


def input_members(unit):
    return members_in_scope(unit, ("VAR_INPUT",))


def output_members(unit):
    return members_in_scope(unit, ("VAR_OUTPUT",))


def all_members(unit):
    out = []
    for block in var_blocks(unit):
        out.extend(block["members"])
    return out


def dut_info(unit):
    """parse_dut() result for a TYPE unit, or None."""
    if not unit.declaration:
        return None
    try:
        return parse_dut(unit.declaration)
    except Exception:
        return None


def is_persistent_gvl(unit):
    """True for units whose first VAR_GLOBAL block carries PERSISTENT."""
    return unit.kind == "gvl_persistent"
