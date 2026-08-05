"""
cli.py - ``cts analyze`` command handlers.

Subcommands:

    cts analyze [options]                          run the analysis
    cts analyze rules                              list registered rules
    cts analyze explain <CTSxxxx> [--format md]    rule documentation
    cts analyze selftest                           run rules on their own docs
    cts analyze baseline create|update|check       baseline management
    cts analyze triage --apply decisions.json      scriptable triage

Exit codes (see imp_plan.md):
    0 - quality policy passed
    1 - unsuppressed findings at or above --fail-on
    2 - configuration error or analysis cannot start
    3 - incomplete analysis with --incomplete=error
"""

from __future__ import annotations

import json
import sys
from cds_static_analyzer import state as state_mod
from cds_static_analyzer.config import ConfigError, load_config
from cds_static_analyzer.registry import RegistryError, load_builtin_rules
from cds_static_analyzer.render import json as render_json
from cds_static_analyzer.render import sarif as render_sarif
from cds_static_analyzer.render import terminal as render_terminal
from cds_static_analyzer.runner import (
    RunOptions,
    exit_code,
)
from cds_static_analyzer.model import severity_rank
from cds_static_analyzer.service import analyze_resolved
from cds_static_analyzer.state import (
    baseline_fingerprints,
    read_baseline,
    read_suppressions,
    write_baseline,
)
from cds_static_analyzer.triage import TriageError, apply_decisions, load_decisions
from cds_static_analyzer.workspace import WorkspaceError, WorkspaceResolver


def _out():
    return sys.stdout


def _err():
    return sys.stderr


def _print_error(message):
    print(f"[ERROR] {message}", file=_err())


def _print_ok(message):
    print(f"[OK] {message}", file=_err())


# ---------------------------------------------------------------------------
# Shared run
# ---------------------------------------------------------------------------


def _load_workspace(args):
    try:
        workspace = WorkspaceResolver(
            workspace=getattr(args, "workspace", ""),
            project_view=getattr(args, "project_view", ""),
        ).resolve()
    except WorkspaceError as exc:
        raise _CliExit(2, str(exc)) from exc
    try:
        config = load_config(workspace.config_path)
    except ConfigError as exc:
        raise _CliExit(2, str(exc)) from exc

    if getattr(args, "fail_on", None):
        config.fail_on = args.fail_on
    if getattr(args, "incomplete", None):
        config.incomplete = args.incomplete
    return workspace, config


class _CliExit(Exception):
    def __init__(self, code, message=""):
        super().__init__(message)
        self.code = code
        self.message = message


def _run_once(workspace, config, args, apply_state=True):
    """Run the analysis, apply suppressions/baseline, return result."""
    rule_filter = None
    if getattr(args, "rule", None):
        rule_filter = set(args.rule)

    options = RunOptions(
        rule_filter=rule_filter,
        incomplete=getattr(args, "incomplete", None),
    )
    try:
        _workspace, _config, result = analyze_resolved(
            workspace, config, options, apply_state=apply_state
        )
    except OSError as exc:
        raise _CliExit(2, f"cannot scan project-view: {exc}") from exc
    except state_mod.StateError as exc:
        raise _CliExit(2, str(exc)) from exc
    except RegistryError as exc:
        raise _CliExit(2, str(exc)) from exc
    return result


def _safe_suppressions(workspace):
    try:
        return read_suppressions(workspace.state_dir)
    except state_mod.StateError as exc:
        raise _CliExit(2, str(exc)) from exc


def _safe_baseline(workspace, validate_schema=True):
    """Read the baseline, enforcing the fingerprint-schema policy.

    ``validate_schema=False`` is only for ``baseline update``, the documented
    recovery command that deliberately rewrites an old baseline.
    """
    try:
        if validate_schema:
            state_mod.validate_baseline_schema(workspace.state_dir)
        return read_baseline(workspace.state_dir)
    except state_mod.StateError as exc:
        raise _CliExit(2, str(exc)) from exc


def _render(result, args):
    fmt = "text" if getattr(args, "pretty", False) else getattr(args, "format", "json")
    if fmt == "json":
        return render_json.render(result)
    if fmt == "sarif":
        return render_sarif.render(result)
    return render_terminal.render(result)


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def cmd_analyze(args):
    workspace, config = _load_workspace(args)
    result = _run_once(workspace, config, args)
    _out().write(_render(result, args))
    _out().flush()
    try:
        return exit_code(
            result, config, incomplete_override=getattr(args, "incomplete", None)
        )
    except _CliExit:
        return 2


# ---------------------------------------------------------------------------
# Rules / explain / selftest
# ---------------------------------------------------------------------------


def cmd_rules(args, out=None):
    out = out or _out()
    try:
        registry = load_builtin_rules()
    except RegistryError as exc:
        raise _CliExit(2, str(exc)) from exc
    fmt = getattr(args, "format", "json")
    rows = []
    for rule_id in sorted(registry):
        rule = registry[rule_id]
        rows.append(
            {
                "id": rule.id,
                "title": rule.title,
                "severity": rule.severity,
                "scope": rule.scope.value,
                "kinds": sorted(rule.kinds),
                "requires": sorted(str(c) for c in rule.requires),
                "summary": rule.summary,
                "doc": rule.doc_path,
            }
        )
    if fmt == "json":
        out.write(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    else:
        for row in rows:
            out.write(
                f"{row['id']} [{row['severity']}] {row['title']}\n"
                f"  scope={row['scope']} kinds={','.join(row['kinds'])}\n"
                f"  {row['summary']}\n"
            )


def cmd_explain(args, out=None):
    out = out or _out()
    rule_id = (getattr(args, "rule_id", "") or "").strip().upper()
    if not rule_id:
        raise _CliExit(2, "explain needs a rule id: cts analyze explain CTS0001")
    try:
        registry = load_builtin_rules()
    except RegistryError as exc:
        raise _CliExit(2, str(exc)) from exc
    rule = registry.get(rule_id)
    if rule is None:
        raise _CliExit(
            2,
            f"unknown rule {rule_id}; known: " + ", ".join(sorted(registry)),
        )
    with open(rule.doc_path, encoding="utf-8") as fh:
        doc = fh.read()
    fmt = getattr(args, "format", "text")
    if fmt == "md":
        out.write(doc)
        return
    out.write(_doc_to_terminal(rule, doc))


def _doc_to_terminal(rule, doc):
    lines = []
    lines.append(f"{rule.id} - {rule.title}")
    lines.append(f"severity: {rule.severity}  scope: {rule.scope.value}")
    lines.append(f"applies to: {', '.join(sorted(rule.kinds))}")
    lines.append(f"requires: {', '.join(sorted(str(c) for c in rule.requires))}")
    lines.append("")
    lines.append(doc)
    return "\n".join(lines) + "\n"


def cmd_selftest(args, out=None):
    from cds_static_analyzer.selftest import run
    return run(out or _out())


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def cmd_baseline(args):
    action = getattr(args, "baseline_action", "") or ""
    if action not in ("create", "update", "check"):
        raise _CliExit(2, "baseline needs an action: create|update|check")

    workspace, config = _load_workspace(args)
    try:
        _workspace, _config, result = analyze_resolved(
            workspace,
            config,
            RunOptions(
                rule_filter=set(args.rule) if getattr(args, "rule", None) else None,
                incomplete=getattr(args, "incomplete", None),
            ),
            apply_state=False,
        )
    except RegistryError as exc:
        raise _CliExit(2, str(exc)) from exc

    existing_entries, _ = _safe_baseline(
        workspace, validate_schema=(action != "update")
    )
    existing = baseline_fingerprints(existing_entries)

    if action == "create":
        if existing_entries:
            raise _CliExit(
                2,
                "baseline already exists; use 'baseline update' to rewrite it",
            )
        entries = [
            {
                "fingerprint": f.fingerprint,
                "rule_id": f.rule_id,
                "unit_id": f.unit_id or "",
                "message": f.message,
            }
            for f in result.findings
        ]
        write_baseline(workspace.state_dir, entries)
        _print_ok(f"baseline created with {len(entries)} finding(s)")
        return 0

    if action == "update":
        entries = [
            {
                "fingerprint": f.fingerprint,
                "rule_id": f.rule_id,
                "unit_id": f.unit_id or "",
                "message": f.message,
            }
            for f in result.findings
        ]
        write_baseline(
            workspace.state_dir,
            entries,
            created=(existing_entries[0].get("created") if existing_entries else None),
        )
        _print_ok(f"baseline updated: {len(entries)} finding(s)")
        return 0

    # check
    current = {f.fingerprint for f in result.findings}
    new_findings = [f for f in result.findings if f.fingerprint not in existing]
    stale = sorted(existing - current)
    if getattr(args, "format", "json") == "json":
        report = {
            "total": len(result.findings),
            "baselined": len(existing),
            "new": len(new_findings),
            "stale": len(stale),
            "new_findings": [f.to_dict() for f in new_findings],
            "stale_entries": stale,
        }
        _out().write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        _out().write(
            f"baseline check: {len(result.findings)} findings, "
            f"{len(existing)} baselined, {len(new_findings)} new, "
            f"{len(stale)} stale\n"
        )
        for f in new_findings:
            _out().write(
                f"  NEW {f.rule_id} {f.location.path}:{f.location.line} {f.message}\n"
            )
        for fp in stale:
            _out().write(f"  STALE {fp}\n")
    # New findings at/above fail-on make the check fail (nothing silent).
    threshold = severity_rank(config.fail_on)
    bad = [f for f in new_findings if severity_rank(f.severity) <= threshold]
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


def cmd_triage(args):
    workspace, config = _load_workspace(args)
    result = _run_once(workspace, config, args, apply_state=False)
    decisions_path = getattr(args, "apply", "") or ""
    try:
        state_mod.validate_baseline_schema(workspace.state_dir)
        decisions = load_decisions(decisions_path)
        summary = apply_decisions(workspace, result, decisions)
    except (TriageError, state_mod.StateError) as exc:
        raise _CliExit(2, str(exc)) from exc
    out = {
        "applied": len(decisions),
        "summary": summary,
    }
    if getattr(args, "format", "json") == "json":
        _out().write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    else:
        _out().write(
            f"triage applied {len(decisions)} decision(s): "
            f"{summary['suppressed']} suppressed, "
            f"{summary['baselined']} baselined, "
            f"{summary['fix_later']} fix-later\n"
        )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def dispatch_analyze(args):
    """Route the parsed ``analyze`` subcommand."""
    action = getattr(args, "analyze_action", "") or ""
    try:
        if action == "":
            return cmd_analyze(args)
        if action == "run":
            return cmd_analyze(args)
        if action == "rules":
            cmd_rules(args)
            return 0
        if action == "explain":
            cmd_explain(args)
            return 0
        if action == "selftest":
            return cmd_selftest(args)
        if action == "baseline":
            return cmd_baseline(args)
        if action == "triage":
            return cmd_triage(args)
    except _CliExit as exc:
        if exc.message:
            _print_error(exc.message)
        return exc.code
    _print_error(
        f"unknown analyze action: {action}; available actions: "
        "rules, explain, selftest, baseline, triage (or omit the action to analyze)"
    )
    return 2
