"""
runner.py - Dispatch of rules over a ProjectSnapshot.

A rule receives only ``ctx`` (an AnalysisContext): it never opens files, runs
git, or reads state. The context owns the capability providers, cached so
each view of the project is built once per run.

The runner guarantees:

* analysis never crashes on one bad object - an unavailable declared
  capability or a rule error becomes a Diagnostic, and the run is marked
  incomplete (policy-controlled);
* output is deterministic: findings are sorted by
  ``path -> position -> rule_id -> fingerprint``;
* every Finding gets a stable fingerprint before filtering;
* scope configuration is interpreted once, here: a rule receives only the
  units visible to it (global path exclusion plus rule-scope exclusion),
  whether it is a UNIT rule (dispatched per visible unit) or a PROJECT /
  PROJECT rule (reading the same filtered set through ``ctx.units``). A
  rule must not call configuration exclusion helpers itself; a rule with no
  visible units runs nothing and requests no capabilities;
* a configured severity override is applied to the run-local Finding only;
  the registry keeps the declared rule severity, so a later run in the same
  process starts from the declared value.
"""

from __future__ import annotations

from cds_text_sync.analyze import fingerprint as fp
from cds_text_sync.analyze.execution import ExecutionGraph
from cds_text_sync.analyze.capabilities import (
    Capability,
    CapabilityError,
    Scope,
)
from cds_text_sync.analyze.model import (
    AnalysisResult,
    Diagnostic,
    Location,
    severity_rank,
)
from cds_text_sync.analyze.registry import RegistryError, load_builtin_rules
from cds_text_sync.analyze.st import blocks, decl, symbols
from cds_text_sync.analyze.file_directives import is_ignored

# ---------------------------------------------------------------------------
# Analysis context
# ---------------------------------------------------------------------------


class AnalysisContext:
    """Everything a rule may read. Builds capability providers lazily.

    Scope filtering lives here, not in the rules: ``visible_units(rule)``
    (and the ``units`` property for the active rule) is the one filter both
    UNIT and PROJECT rules consume. A rule must not call
    ``config.path_excluded``/``rules_excluded_for`` itself.
    """

    def __init__(self, workspace, snapshot, config):
        self.workspace = workspace
        self.snapshot = snapshot
        self.config = config
        self.active_rule = None  # set by the runner before dispatch
        self._cache = {}
        self._visible_cache = {}

    # -- scope filtering -----------------------------------------------------

    def visible_units(self, rule=None):
        """Units visible to *rule* after global path exclusion and
        rule-scope exclusion. ``rule`` defaults to the active rule; with no
        rule set (tests/selftest) every unit is visible."""
        rule = rule or self.active_rule
        cache_key = rule.id if rule is not None else None
        if cache_key in self._visible_cache:
            return self._visible_cache[cache_key]
        if rule is None:
            visible = list(self.snapshot.units)
        else:
            visible = [
            u for u in self.snapshot.units if self._unit_visible(rule, u.source_path)
            ]
        self._visible_cache[cache_key] = visible
        return visible

    def _unit_visible(self, rule, relpath):
        if self.config.path_excluded(relpath):
            return False
        if rule.id in self.config.rules_excluded_for(relpath):
            return False
        return True

    @property
    def units(self):
        """Units visible to the active rule (see ``visible_units``)."""
        return self.visible_units()

    # -- capabilities ------------------------------------------------------

    def capability(self, cap):
        """Return the provider for *cap* or raise CapabilityError."""
        if cap not in self._cache:
            self._cache[cap] = self._build(cap)
        entry = self._cache[cap]
        if entry.error:
            raise CapabilityError(cap, entry.error)
        return entry.value

    def has_capability(self, cap):
        try:
            self.capability(cap)
            return True
        except CapabilityError:
            return False

    def _build(self, cap):
        if cap == Capability.ST_TEXT:
            return _Entry(self.snapshot, None)
        if cap == Capability.DECLARATIONS:
            error = _st_read_errors(self.snapshot)
            return _Entry(decl, error)
        if cap == Capability.BLOCK_STRUCTURE:
            error = _st_read_errors(self.snapshot)
            return _Entry(blocks, error)
        if cap == Capability.PROJECT_SYMBOLS:
            error = _st_read_errors(self.snapshot)
            return _Entry(symbols.ProjectSymbols(self.snapshot), error)
        if cap == Capability.VISU_XML:
            return _Entry(self.snapshot, None)
        if cap == Capability.TEXT_LISTS:
            return _Entry(self.snapshot, None)
        if cap == Capability.TASK_CONFIG:
            return _Entry(self.snapshot, None)
        if cap == Capability.EXECUTION_GRAPH:
            error = _st_read_errors(self.snapshot)
            return _Entry(ExecutionGraph(self.snapshot), error)
        return _Entry(None, f"unknown capability {cap}")

    # -- conveniences ------------------------------------------------------

    def option(self, name):
        """Resolve a per-rule option against the active rule.

        ``name`` must be declared by the active rule's ``RuleSpec`` or this
        raises ``KeyError`` (a rule bug; the dispatch handler converts it to
        a ``rule-error`` Diagnostic). A configured value that cannot be
        coerced to the declared type falls back to the declared default -
        the mismatch was already reported as a ``rule-option`` Diagnostic
        when the rule's options were pre-validated in ``run_analysis``.
        """
        declared = self.active_rule.options
        if name not in declared:
            raise KeyError(name)
        default = declared[name]
        configured = self.config.options_for(self.active_rule.id).get(name)
        if configured is None:
            return default
        coerced = _coerce_option(name, configured, default)
        return default if coerced is None else coerced

    def diagnostics_for(self, kind, message, location=None, rule_id=None, unit_id=None):
        return Diagnostic(
            kind, message, location=location, rule_id=rule_id, unit_id=unit_id
        )


class _Entry:
    def __init__(self, value, error):
        self.value = value
        self.error = error


def _coerce_option(name, value, default):
    """Coerce a configured option to the declared type, or None on mismatch.

    A scalar of the wrong type is ``RuleSpec.validate``'s contract violation
    at declaration time; here we only need the configured value to be
    assignment-compatible with the declared default.
    """
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, int) and not isinstance(default, bool):
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if isinstance(default, float):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(default, str):
        return value if isinstance(value, str) else None
    return None


def _validate_rule_options(rule, ctx, result):
    """Report per-run option problems for one rule, once.

    Runs in the pre-dispatch loop so a bad option yields exactly one
    ``rule-option`` Diagnostic per rule rather than one per unit, and so a
    typo in a config never stops the analyzer from starting. Unknown keys
    and type mismatches are reported; neither aborts the rule.
    """
    configured = ctx.config.options_for(rule.id)
    for name in sorted(configured):
        if name not in rule.options:
            result.complete = False
            result.diagnostics.append(
                Diagnostic(
                    "rule-option",
                    f"{rule.id}: unknown option {name!r} (declared: "
                    f"{', '.join(sorted(rule.options)) or 'none'})",
                    rule_id=rule.id,
                )
            )
            continue
        default = rule.options[name]
        if _coerce_option(name, configured[name], default) is None:
            result.complete = False
            result.diagnostics.append(
                Diagnostic(
                    "rule-option",
                    f"{rule.id}: option {name!r} has type "
                    f"{type(configured[name]).__name__}, expected "
                    f"{type(default).__name__}; using default "
                    f"{default!r}",
                    rule_id=rule.id,
                )
            )


def _st_read_errors(snapshot):
    """Error string if any .st file could not be read (model incomplete)."""
    bad = [
        d
        for d in snapshot.diagnostics
        if d.kind == "project-read" and d.location.path.endswith(".st")
    ]
    if bad:
        first = bad[0].location.path
        return (
            f"cannot read .st file(s) (e.g. {first}); declarations and "
            "project symbols are incomplete"
        )
    return None


# ---------------------------------------------------------------------------
# Options + main entry
# ---------------------------------------------------------------------------


class RunOptions:
    def __init__(self, rule_filter=None, incomplete=None):
        self.rule_filter = rule_filter  # set of rule ids or None
        self.incomplete = incomplete  # CLI override: warn|error|ignore


def _select_rules(registry, config, rule_filter):
    """Enabled rules, filtered by config and the --rule option."""
    if rule_filter is not None:
        unknown = sorted(set(rule_filter) - set(registry))
        if unknown:
            raise RegistryError(
                "unknown human-analysis rule(s): " + ", ".join(unknown)
            )
    rules = []
    for rule_id in sorted(registry):
        rule = registry[rule_id]
        if rule_filter is not None:
            if rule_id not in rule_filter:
                continue
            # An explicit --rule selection is an opt-in for rules which are
            # disabled by default. A project config can still disable it.
            if not config.enabled_for(rule_id, default=True):
                continue
        elif not config.enabled_for(rule_id):
            continue
        rules.append(rule)
    return rules


def run_analysis(workspace, snapshot, config, options):
    """Run every enabled rule over the snapshot. Returns AnalysisResult."""
    result = AnalysisResult()
    registry = load_builtin_rules()
    rules = _select_rules(registry, config, options.rule_filter)
    ctx = AnalysisContext(workspace, snapshot, config)

    result.summary.rules_run = sorted(r.id for r in rules)

    skipped = {}
    for rule in rules:
        # A rule with no visible units runs nothing: it requests no
        # capabilities (a scoped-out history rule must not start git) and
        # is not dispatched.
        if not ctx.visible_units(rule):
            continue
        ctx.active_rule = rule
        # Per-rule options are validated once here, not per unit, so a bad
        # option produces exactly one Diagnostic per rule per run.
        _validate_rule_options(rule, ctx, result)
        for cap in sorted(rule.requires, key=str):
            try:
                ctx.capability(cap)
            except CapabilityError as exc:
                skipped[rule.id] = exc
                result.complete = False
                result.diagnostics.append(
                    Diagnostic(
                        exc.capability.value,
                        exc.message,
                        rule_id=rule.id,
                    )
                )
                break

    for rule in rules:
        if rule.id in skipped:
            continue
        if not ctx.visible_units(rule):
            continue
        ctx.active_rule = rule
        _report_unparsed_units(rule, ctx, result)
        _report_visu_xml_errors(rule, ctx, result)
        if rule.scope == Scope.UNIT:
            for unit in ctx.visible_units(rule):
                if not rule.applicable_to(unit.kind):
                    continue
                _dispatch_unit(rule, unit, ctx, result)
        else:
            _dispatch_project(rule, ctx, result)

    # Fingerprints must exist before the later state filter.  File directives
    # are source-level suppression, but stale state entries must still be
    # checked against findings that were removed by that first stage.
    _fingerprint_all(result.findings)
    result._unfiltered_fingerprints = {f.fingerprint for f in result.findings}
    _apply_file_directives(result, snapshot, rules)
    result.sort()
    result.summary.diagnostics = len(result.diagnostics)
    return result


def _apply_file_directives(result, snapshot, known_rules):
    """Remove findings covered by ``cts:ignore-file`` source directives."""
    ignored_by_path = {
        path: directives.rules
        for path, directives in snapshot.file_directives.items()
        if path.lower().endswith(".st")
    }
    if not ignored_by_path:
        return
    units_by_path = {}
    for unit in snapshot.units:
        units_by_path.setdefault(unit.source_path, unit)
    for path, directives in snapshot.file_directives.items():
        if not path.lower().endswith(".st"):
            continue
        unit = units_by_path.get(path)
        unit_id = unit.id if unit else None
        for kind, detail, line in directives.issues:
            result.diagnostics.append(
                Diagnostic(
                    kind,
                    f"{detail} in cts:ignore-file directive",
                    Location(path, line, 1),
                    unit_id=unit_id,
                )
            )
        for rule_id in sorted(directives.rules - {"*"} - set(known_rules)):
            result.diagnostics.append(
                Diagnostic(
                    "directive-unknown-rule",
                    f"unknown rule {rule_id} in cts:ignore-file directive",
                    Location(path, 1, 1),
                    rule_id=rule_id,
                    unit_id=unit_id,
                )
            )
    kept = []
    ignored = 0
    for finding in result.findings:
        rules = ignored_by_path.get(finding.location.path, frozenset())
        if is_ignored(finding.rule_id, rules):
            ignored += 1
            continue
        kept.append(finding)
    if ignored:
        result.findings = kept
        result.summary.suppressed += ignored
        result.summary.suppressed_by_directive += ignored
        _recount_summary(result)


def _report_unparsed_units(rule, ctx, result):
    """A rule that needed declarations/symbols reports UNKNOWN units.

    An unclassifiable ``.st`` file stays in the snapshot as a
    ``kind=UNKNOWN`` unit. A rule that required DECLARATIONS or
    PROJECT_SYMBOLS genuinely needed its parse, so it records a Diagnostic
    instead of silently treating the object as "not applicable". Only units
    visible to the rule are reported.
    """
    from cds_text_sync.analyze.st import kinds as _K

    needed = rule.requires & {
        Capability.DECLARATIONS,
        Capability.PROJECT_SYMBOLS,
    }
    if not needed:
        return
    for unit in ctx.visible_units(rule):
        if unit.kind != _K.UNKNOWN:
            continue
        result.complete = False
        result.diagnostics.append(
            Diagnostic(
                "st-parse",
                f"cannot parse declarations of {unit.id}",
                location=Location(unit.source_path),
                rule_id=rule.id,
                unit_id=unit.id,
            )
        )


def _report_visu_xml_errors(rule, ctx, result):
    """A rule that needed VISU_XML reports unparsable visualization XML.

    A malformed visualization file is a missing piece of the model for the
    rule, so it is surfaced as a Diagnostic with a project-view-relative
    location and the rule id - one per rule/object pair (deduplicated) -
    and the run is marked incomplete. The capability itself stays
    available: the rule still analyses the objects that did parse.
    """
    if Capability.VISU_XML not in rule.requires:
        return
    seen = set()
    for record in ctx.snapshot.source_errors:
        if record.source_kind != "visualization":
            continue
        if not ctx._unit_visible(rule, record.location.path):
            continue
        key = (rule.id, record.location.path)
        if key in seen:
            continue
        seen.add(key)
        result.complete = False
        result.diagnostics.append(
            Diagnostic(
                "visu-xml",
                record.message,
                location=record.location,
                rule_id=rule.id,
                unit_id=record.unit_id,
            )
        )


def _dispatch_unit(rule, unit, ctx, result):
    try:
        found = rule.check(unit, ctx) or []
    except CapabilityError as exc:
        result.complete = False
        result.diagnostics.append(
            Diagnostic(
                exc.capability.value, exc.message, rule_id=rule.id, unit_id=unit.id
            )
        )
        return
    except Exception as exc:  # a rule must never crash a run
        result.complete = False
        result.diagnostics.append(
            Diagnostic(
                "rule-error",
                f"{rule.id} failed on {unit.id}: {exc}",
                location=Location(unit.source_path),
                rule_id=rule.id,
                unit_id=unit.id,
            )
        )
        return
    _collect(rule, found, result, ctx.config)


def _dispatch_project(rule, ctx, result):
    try:
        found = rule.check(ctx) or []
    except CapabilityError as exc:
        result.complete = False
        result.diagnostics.append(
            Diagnostic(exc.capability.value, exc.message, rule_id=rule.id)
        )
        return
    except Exception as exc:
        result.complete = False
        result.diagnostics.append(
            Diagnostic(
                "rule-error",
                f"{rule.id} failed: {exc}",
                rule_id=rule.id,
            )
        )
        return
    _collect(rule, found, result, ctx.config)


def _collect(rule, found, result, config):
    """The single collection point for rule output.

    Identity (id, title, severity) is stamped here from the registry Rule;
    a rule impl must not carry it. The declared severity feeds the config
    override and is stored on the run-local Finding only: the registry
    keeps the declared rule severity, so a later run in the same process
    starts from the declared value. Fingerprint inputs never include
    severity, so the identity of the underlying violation is unchanged by
    policy.
    """
    for item in found or []:
        if isinstance(item, Diagnostic):
            result.diagnostics.append(item)
            result.complete = False
        elif item is not None:
            item.rule_id = rule.id
            item.rule_title = rule.title
            item.severity = config.severity_for(rule.id, rule.severity)
            result.findings.append(item)
            result.summary.add_finding(item)


def _fingerprint_all(findings):
    for f in findings:
        if f.fingerprint:
            continue
        f.fingerprint = fp.fingerprint(
            f.rule_id, f.unit_id, f.anchor or f.message, f.context
        )


# ---------------------------------------------------------------------------
# Filtering: suppressions + baseline
# ---------------------------------------------------------------------------


def _recount_summary(result):
    """Rebuild finding counts after a filtering stage changes the list."""
    result.summary.total = len(result.findings)
    result.summary.by_severity = dict.fromkeys(("danger", "suspicious", "style"), 0)
    result.summary.by_rule = {}
    for finding in result.findings:
        result.summary.by_severity[finding.severity] += 1
        result.summary.by_rule[finding.rule_id] = (
            result.summary.by_rule.get(finding.rule_id, 0) + 1
        )


def filter_result(result, suppressed_fingerprints, baselined_fingerprints):
    """Remove suppressed/baselined findings and count them.

    Returns (new_result, stale_suppressions) where stale_suppressions are
    suppression/baseline entries that no longer match any finding.
    """
    current = getattr(result, "_unfiltered_fingerprints", None)
    if current is None:
        current = {f.fingerprint for f in result.findings}

    stale_suppressed = sorted({s for s in suppressed_fingerprints if s not in current})
    stale_baselined = sorted({b for b in baselined_fingerprints if b not in current})

    kept = []
    suppressed = 0
    baselined = 0
    for f in result.findings:
        if f.fingerprint in suppressed_fingerprints:
            suppressed += 1
            continue
        if f.fingerprint in baselined_fingerprints:
            baselined += 1
            continue
        kept.append(f)

    result.findings = kept
    result.summary.suppressed = result.summary.suppressed_by_directive + suppressed
    result.summary.baselined = baselined
    result.summary.stale_suppressions = stale_suppressed
    result.summary.stale_baselined = stale_baselined
    _recount_summary(result)
    result.sort()
    return result


def exit_code(result, config, incomplete_override=None):
    """Exit policy: 0 clean, 1 violations >= fail_on, 3 incomplete."""
    incomplete = incomplete_override or config.incomplete
    if incomplete == "error" and not result.complete:
        return 3
    threshold = severity_rank(config.fail_on)
    for f in result.findings:
        if severity_rank(f.severity) <= threshold:
            return 1
    return 0
