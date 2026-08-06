"""
rules_api.py - The contract a ``rules/*.py`` file implements.

A rule is one file: its ``check`` plus the metadata describing it. Anything
shared by several rules lives in the analyzer package (``st/``) where there
are types and tests. The rule file defines a module-level ``RULE`` object:

    from cds_static_analyzer.rules_api import RuleSpec
    from cds_static_analyzer.capabilities import Capability, Scope

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
        options={"min_tokens": 4},
    )

Options are per-rule tunables whose defaults live here and whose overrides
come from ``[rules.<id>] options.<name>`` in ``cts-analyze.toml``. Defaults
must be ``int``/``float``/``str``/``bool`` (the type is inferred from them)
and names must not collide with the reserved ``enabled``/``severity``/
``exclude`` keys. A rule reads one via ``ctx.option("name")``.

Signature by scope:

* ``Scope.UNIT``:    ``check(unit, ctx)``  -- called once per matching unit
* ``Scope.PROJECT``: ``check(ctx)``        -- called once, full snapshot

``ctx`` is an ``AnalysisContext`` (see runner.py): rules read data only
through it and never open files themselves.

Scope filtering is the runner's job, not the rule's. ``ctx.units`` (and
``ctx.visible_units(rule)``) is the single filtered unit set: global path
``enabled = false`` scopes and per-rule ``exclude`` lists are applied once
by the runner, identically for UNIT and PROJECT rules. A rule must
not call configuration exclusion helpers itself, and a fully scoped-out
rule never runs when all of its units are scoped out.

Identity is stamped by the runner, not by a rule. ``finding_in`` returns a
Finding with empty ``rule_id``/``severity``/``rule_title``; ``_collect`` in
runner.py fills them from the registry ``Rule`` so a rule can never drift
from its manifest.

Findings merge: a rule may declare a ``merge`` strategy so the runner
collapses several findings it produced into one. ``"adjacent"`` groups
findings that occupy a contiguous run of source lines; ``"identical"`` groups
findings the state layer already cannot tell apart (same anchor and
normalised context). The merged finding is its own first member widened to
cover the whole group, so its anchor/context - and therefore its fingerprint
- are exactly what that member had alone.
"""

from __future__ import annotations

import re

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.model import Finding, Location, line_col_of

# Reserved option names: they already have a meaning on the [rules.<id>] table.
_RESERVED_OPTIONS = frozenset({"enabled", "severity", "exclude"})
# The only value types a rule option may declare. Inferred from the default.
_OPTION_TYPES = (int, float, str, bool)
_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
# Allowed topics for rule taxonomy. All rules must declare one.
ALLOWED_TOPICS = frozenset({
    "Code quality",
    "Interfaces",
    "Correctness",
    "Style",
    "Dead code",
    "Data consistency",
})


class RuleSpecError(Exception):
    """A rule file declared invalid metadata."""


class RuleSpec:
    def __init__(
        self,
        id,
        title,
        severity,
        scope,
        requires,
        kinds,
        summary,
        check,
        topic,
        merge=None,
        options=None,
    ):
        self.id = str(id).strip()
        self.title = str(title).strip()
        self.severity = str(severity).strip().lower()
        self.scope = scope if isinstance(scope, Scope) else Scope(scope)
        self.requires = _normalise_capabilities(requires)
        self.kinds = kinds  # expanded by the registry
        self.summary = str(summary).strip()
        self.topic = str(topic).strip()
        self.merge = merge
        self.check = check
        self.options = {k: v for k, v in (options or {}).items()}

    def validate(self):
        if not self.id or not self.title or not self.summary:
            raise RuleSpecError(
                f"{self.id or '<no-id>'}: id/title/summary must be non-empty"
            )
        if not self.topic:
            raise RuleSpecError(f"{self.id}: topic must be non-empty")
        if self.topic not in ALLOWED_TOPICS:
            raise RuleSpecError(
                f"{self.id}: topic {self.topic!r} not in allowed set: "
                f"{', '.join(sorted(ALLOWED_TOPICS))}"
            )
        from cds_static_analyzer.model import is_valid_severity

        if not is_valid_severity(self.severity):
            raise RuleSpecError(f"{self.id}: bad severity {self.severity!r}")
        if not callable(self.check):
            raise RuleSpecError(f"{self.id}: check must be callable")
        if self.merge not in (None, "adjacent", "identical"):
            raise RuleSpecError(f"{self.id}: bad merge strategy {self.merge!r}")
        for name, default in self.options.items():
            if name in _RESERVED_OPTIONS:
                raise RuleSpecError(
                    f"{self.id}: option {name!r} collides with a reserved key"
                )
            if not _IDENT_RE.match(name):
                raise RuleSpecError(
                    f"{self.id}: option {name!r} is not a valid identifier"
                )
            if not isinstance(default, _OPTION_TYPES):
                raise RuleSpecError(
                    f"{self.id}: option {name!r} default type "
                    f"{type(default).__name__} not allowed "
                    f"(int/float/str/bool only)"
                )


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


def finding_in(message, unit, offset=None, end_offset=None, anchor=None, context=None):
    """Build a Finding located in a unit.

    Identity (rule id, title, severity) is stamped by the runner from the
    registry Rule and must not be set by a rule.
    """
    return Finding(
        rule_id="",
        severity="",
        message=message,
        location=location_in(unit, offset, end_offset),
        unit_id=unit.id,
        anchor=anchor,
        context=context,
        rule_title="",
    )
