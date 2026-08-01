"""
persistent_order.py - CTS0004: PERSISTENT member order changed vs git base.

History rule (GIT_BASE capability). Semantics (fixed before code):

* applies to ``gvl_persistent`` units (``VAR_GLOBAL PERSISTENT [RETAIN]``);
* the base version is read at an explicit git base (CLI ``--base`` > config
  ``[analyze] base`` > ``HEAD``) - never an implicit "previous commit";
* variables are matched between the two versions by name (case-insensitive);
  renames therefore appear as remove+add and are out of scope for v1;
* a finding is reported for a member that appears earlier than its immediate
  base predecessor (its relative order changed);
* a file absent from the base (newly added) is not a finding;
* no git repository / unresolvable base -> the runner records a
  policy-controlled Diagnostic instead of a silent pass.
"""

from __future__ import annotations

import re

from cds_text_sync.analyze.capabilities import Capability
from cds_text_sync.analyze.rules_api import finding_in
from cds_text_sync.analyze.st import decl
from cds_text_sync.analyze.st import kinds as K

RULE_ID = "CTS0004"
SEVERITY = "danger"

_HEADER_RE = re.compile(r"^\s*VAR_GLOBAL\b", re.IGNORECASE)


def _persistent_member_names(decl_text):
    """Ordered names of members in the first VAR_GLOBAL block."""
    names = []
    for block in decl.parse_var_blocks_text(decl_text):
        if block["scope"] == "VAR_GLOBAL":
            for member in block["members"]:
                names.append(member["name"])
            break
    return names


def order_changes(base_names, current_names):
    """Members whose position moved earlier than their base predecessor.

    Returns a list of (member, base_predecessor).
    """
    current_index = {n.lower(): i for i, n in enumerate(current_names)}
    changes = []
    for i in range(1, len(base_names)):
        prev, member = base_names[i - 1], base_names[i]
        ci = current_index.get(member.lower())
        cpi = current_index.get(prev.lower())
        if ci is None or cpi is None:
            continue  # renamed/removed on either side: out of scope
        if ci < cpi:
            changes.append((member, prev))
    return changes


def check(ctx):
    """Compare PERSISTENT GVL member order against the git base.

    ``ctx.units`` is the runner-scoped unit set (global path exclusion and
    rule-scope exclusion applied once, centrally); the rule never consults
    configuration exclusion helpers itself.
    """
    git = ctx.capability(Capability.GIT_BASE)
    for unit in ctx.units:
        if unit.kind != K.GVL_PERSISTENT:
            continue
        base_text = git.read(unit.source_path)
        if base_text is None:
            # File absent at the base: nothing to compare against.
            continue
        base_names = _persistent_member_names(base_text)
        current_names = _persistent_member_names(unit.declaration or "")
        if not base_names or not current_names:
            continue
        for member, prev in order_changes(base_names, current_names):
            offset = _member_offset(unit, member)
            yield finding_in(
                rule_id=RULE_ID,
                severity=SEVERITY,
                message=(
                    f"PERSISTENT member '{member}' moved before '{prev}'; "
                    "changing the order of persistent variables can shift "
                    "their addresses across a download"
                ),
                unit=unit,
                offset=offset,
                anchor=member,
                context=f"{member} : {prev}",
                rule_title="PERSISTENT order changed",
            )


def _member_offset(unit, member):
    decl_lines = (unit.declaration or "").split("\n")
    for idx, raw in enumerate(decl_lines):
        m = re.search(r"\b" + re.escape(member) + r"\b", raw)
        if m:
            line_start = sum(len(decl_lines[k]) + 1 for k in range(idx))
            return line_start + m.start()
    return None
