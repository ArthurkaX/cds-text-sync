"""
rules_api.py - The contract a ``.ctsrule`` file implements.

A rule file is deliberately thin: metadata plus one ``check``. All real
logic lives in the analyzer package (``st/``, ``rules/impl/``) where there
are types and tests. The rule module defines a module-level ``RULE`` object:

    from cds_text_sync.analyze.rules_api import RuleSpec
    from cds_text_sync.analyze.capabilities import Capability, Scope

    def check(unit, ctx):        # Scope.UNIT
        ...

    RULE = RuleSpec(
        id="CTS0001",
        title="...",
        severity="suspicious",
        scope=Scope.UNIT,
        requires={Capability.ST_TEXT},
        kinds="CALLABLE",
        summary="...",
        check=check,
    )

Signature by scope:

* ``Scope.UNIT``:    ``check(unit, ctx)``  -- called once per matching unit
* ``Scope.PROJECT``: ``check(ctx)``        -- called once, full snapshot
* ``Scope.HISTORY``: ``check(ctx)``        -- called once, git available

``ctx`` is an ``AnalysisContext`` (see runner.py): rules read data only
through it and never open files themselves.

Scope filtering is the runner's job, not the rule's. ``ctx.units`` (and
``ctx.visible_units(rule)``) is the single filtered unit set: global path
``enabled = false`` scopes and per-rule ``exclude`` lists are applied once
by the runner, identically for UNIT and PROJECT/HISTORY rules. A rule must
not call configuration exclusion helpers itself, and a fully scoped-out
rule never runs (it requests no capabilities, so a scoped-out HISTORY rule
never starts git).
"""

from __future__ import annotations

from cds_text_sync.analyze.capabilities import Capability, Scope
from cds_text_sync.analyze.model import Finding, Location, line_col_of


class RuleSpecError(Exception):
    """A rule file declared invalid metadata."""


class RuleSpec:
    def __init__(self, id, title, severity, scope, requires, kinds, summary, check):
        self.id = str(id).strip()
        self.title = str(title).strip()
        self.severity = str(severity).strip().lower()
        self.scope = scope if isinstance(scope, Scope) else Scope(scope)
        self.requires = _normalise_capabilities(requires)
        self.kinds = kinds  # expanded by the registry
        self.summary = str(summary).strip()
        self.check = check

    def validate(self):
        if not self.id or not self.title or not self.summary:
            raise RuleSpecError(
                f"{self.id or '<no-id>'}: id/title/summary must be non-empty"
            )
        from cds_text_sync.analyze.model import is_valid_severity

        if not is_valid_severity(self.severity):
            raise RuleSpecError(f"{self.id}: bad severity {self.severity!r}")
        if not callable(self.check):
            raise RuleSpecError(f"{self.id}: check must be callable")


def _normalise_capabilities(requires):
    out = set()
    for item in requires or ():
        if isinstance(item, Capability):
            out.add(item)
        else:
            out.add(Capability(str(item)))
    return out


def location_in(unit, offset=None, end_offset=None):
    """Location for a byte range inside a unit's own text."""
    line, col = line_col_of(unit.text, offset)
    if end_offset is None:
        end_line, end_col = None, None
    else:
        end_line, end_col = line_col_of(unit.text, end_offset)
    return Location(
        unit.source_path,
        line,
        col,
        end_line,
        end_col,
        offset=offset,
        end_offset=end_offset,
    )


def finding_in(
    rule_id,
    severity,
    message,
    unit,
    offset=None,
    end_offset=None,
    anchor=None,
    context=None,
    rule_title="",
):
    """Build a Finding located in a unit."""
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        location=location_in(unit, offset, end_offset),
        unit_id=unit.id,
        anchor=anchor,
        context=context,
        rule_title=rule_title,
    )
