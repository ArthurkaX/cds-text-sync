"""
CTS0002 - VAR_INPUT members never read by their owner.

Semantics (fixed before code, per the implementation plan):

* scope: inputs of CALLABLE owners (program, function block, function,
  method, action);
* a use is any identifier occurrence of the member name in the owner's
  implementation text *plus* the implementations of every unit owned by the
  owner (methods/actions of a function block) - qualified access ``THIS.x``
  and ``SUPER^.x`` counts as a use of ``x``;
* comments and string literals are blanked before tokenising;
* unparseable bodies are handled upstream: if the DECLARATIONS or
  PROJECT_SYMBOLS capability is unavailable the runner skips this rule and
  records a Diagnostic instead of a false "clean".

Limitations (documented, accepted for v1): a bare ``x`` that is shadowed by a
local of the same name in a method still counts as a read; write-only
occurrences also count as reads (read/write separation is a later,
statement-aware rule).
"""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def _read_tokens(snapshot, unit):
    """Lowercased identifier set read by *unit* and everything it owns."""
    candidates = [unit] + list(snapshot.units_owned_by(unit.qualified_name))
    tokens = set()
    for candidate in candidates:
        if not candidate.implementation:
            continue
        clean = body(candidate).text
        # Qualified access: THIS.x / SUPER^.x read x.
        clean = re.sub(r"\bTHIS\s*\.", " ", clean)
        clean = re.sub(r"\bSUPER\s*\^", " ", clean)
        for m in _IDENT_RE.finditer(clean):
            tokens.add(m.group(0).lower())
    return tokens


def _member_offset(unit, member):
    """Offset of the member name inside the unit's declaration text."""
    line = member.get("line")
    if not line:
        return None
    decl_lines = (unit.declaration or "").split("\n")
    idx = line - 1
    if not (0 <= idx < len(decl_lines)):
        return None
    line_text = decl_lines[idx]
    pos = line_text.find(member["name"])
    if pos < 0:
        return None
    line_start = 0
    for k in range(idx):
        line_start += len(decl_lines[k]) + 1
    return line_start + pos


def check(unit, ctx):
    """Flag unused VAR_INPUT members of CALLABLE units."""
    declarations = ctx.capability(Capability.DECLARATIONS)
    inputs = declarations.input_members(unit)
    if not inputs:
        return
    read = _read_tokens(ctx.snapshot, unit)
    for member in inputs:
        name = member["name"]
        if name.lower() in read:
            continue
        typ = member.get("type", "")
        offset = _member_offset(unit, member)
        yield finding_in(
            message=(
                f"input '{name}' is never read by {unit.qualified_name} "
                f"or its methods/actions"
            ),
            unit=unit,
            offset=offset,
            anchor=name,
            context=f"{name} : {typ}",
        )


RULE = RuleSpec(
    id="CTS0002",
    title="Unused input",
    severity="suspicious",
    scope=Scope.UNIT,
    requires={Capability.DECLARATIONS},
    kinds="CALLABLE",
    summary="VAR_INPUT members never read by their owner.",
    topic="Interfaces",
    check=check,
)
