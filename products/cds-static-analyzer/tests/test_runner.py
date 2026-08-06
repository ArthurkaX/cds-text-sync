"""Pure analyzer runner contracts over the ST fixture."""

import json
import os

from cds_static_analyzer.config import ResolvedConfig, load_config
from cds_static_analyzer.model import AnalysisResult, Diagnostic, Finding
from cds_static_analyzer.project import build_st_snapshot
from cds_static_analyzer.registry import load_builtin_rules
from cds_static_analyzer.runner import RunOptions, exit_code, filter_result, run_analysis
from cds_static_analyzer.workspace import WorkspaceResolver

from st_helpers import copy_fixture, fixture_project_view


def _run(workspace, rule_filter=None, incomplete=None):
    ws = WorkspaceResolver(workspace=workspace).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    options = RunOptions(rule_filter=rule_filter, incomplete=incomplete)
    result = run_analysis(ws, snap, config, options)
    return ws, config, result

def test_fixture_findings_are_deterministic(tmp_path):
    ws1, cfg1, r1 = _run(fixture_project_view())
    ws2, cfg2, r2 = _run(fixture_project_view())
    assert json.dumps(r1.to_dict(), sort_keys=True) == json.dumps(
        r2.to_dict(), sort_keys=True
    )

def test_run_populates_unfiltered_fingerprints_before_state_filter(tmp_path):
    _, _, result = _run(fixture_project_view(), rule_filter={"CTS0001"})
    fingerprint = result.findings[0].fingerprint
    filtered = filter_result(result, {fingerprint}, set())
    assert filtered.summary.stale_suppressions == []
    assert filtered.summary.suppressed == 1

def test_fixture_expected_findings(tmp_path):
    _, _, result = _run(fixture_project_view())
    by_rule = {}
    for f in result.findings:
        by_rule.setdefault(f.rule_id, []).append(f.anchor)
    # Main.st lines 22-23 are one commented-out block, so CTS0001 reports it
    # once, anchored on the first line; "y := y + 2;" is a merged-away member.
    assert sorted(by_rule["CTS0001"]) == ["y := x + 5;"]
    assert sorted(by_rule["CTS0002"]) == ["nTarget", "sName"]
    assert result.complete is True

def test_fixture_block_comment_columns_are_1_to_1(tmp_path):
    """PB.st carries a block comment before a CTS0004 violation in the same
    section. Its reported columns are the real character columns: the
    blanking off-by-one used to shift every such finding one byte left per
    block comment. Merging is off here so both occurrences keep their own
    column."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    with open(os.path.join(root, "cts-analyze.toml"), "w", encoding="utf-8") as fh:
        fh.write("[rules.CTS0004]\noptions.merge = false\n")
    _, _, result = _run(root)
    pb = [f for f in result.findings if f.location.path == "POUs/PB.st"]
    assert [(f.location.line, f.location.column) for f in pb] == [(9, 27), (10, 10)]
    assert {f.rule_id for f in pb} == {"CTS0004"}

def test_rule_filter(tmp_path):
    _, _, result = _run(fixture_project_view(), rule_filter={"CTS0002"})
    assert {f.rule_id for f in result.findings} == {"CTS0002"}

def test_file_ignore_directive_suppresses_all_matching_findings(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    main = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(main, encoding="utf-8") as fh:
        original = fh.read()
    with open(main, "w", encoding="utf-8") as fh:
            fh.write("// cts:ignore-file CTS0001, CTS0002, CTS0007, CTS0008, CTS0013 -- legacy fixture\n" + original)
    _, _, result = _run(root)
    assert not any(f.location.path == "POUs/Main.st" for f in result.findings)
    # 5, not 6: the CTS0001 pair on lines 22-23 is reported as one finding.
    assert result.summary.suppressed == 5

def test_exit_codes(tmp_path):
    ws, config, result = _run(fixture_project_view())
    # Default fail_on=suspicious: danger+suspicious present -> 1.
    assert exit_code(result, config) == 1
    # fail_on=danger: only danger fails; fixture has none -> 0.
    config.fail_on = "danger"
    assert exit_code(result, config) == 0
    # fail_on=style: everything fails -> 1.
    config.fail_on = "style"
    assert exit_code(result, config) == 1

def test_filter_result_counts_and_stale(tmp_path):
    result = AnalysisResult()
    f1 = Finding("CTS0001", "suspicious", "m1")
    f2 = Finding("CTS0002", "style", "m2")
    for f, fp in ((f1, "cts1:aaa"), (f2, "cts1:bbb")):
        f.fingerprint = fp
        f.location.path = "x.st"
        result.findings.append(f)
        result.summary.add_finding(f)
    filtered = filter_result(result, {"cts1:aaa"}, {"cts1:ccc"})
    assert [f.fingerprint for f in filtered.findings] == ["cts1:bbb"]
    assert filtered.summary.suppressed == 1
    assert filtered.summary.baselined == 0
    assert "cts1:ccc" in filtered.summary.stale_baselined

def test_filter_result_uses_unfiltered_findings_for_stale_state():
    result = AnalysisResult()
    finding = Finding("CTS0001", "suspicious", "m1")
    finding.fingerprint = "cts1:gone-by-directive"
    result.findings.append(finding)
    result.summary.add_finding(finding)
    result._unfiltered_fingerprints = {finding.fingerprint}
    # Simulate the source directive stage having removed the finding.
    result.findings = []
    filtered = filter_result(result, {finding.fingerprint}, set())
    assert filtered.summary.stale_suppressions == []

def test_capability_gate_skips_rule_with_diagnostic(tmp_path):
    # An unreadable .st makes DECLARATIONS/PROJECT_SYMBOLS unavailable.
    root = str(tmp_path / "sync")
    copy_fixture(root)
    bad_dir = os.path.join(root, "project-view", "POUs")
    os.makedirs(bad_dir, exist_ok=True)
    with open(os.path.join(bad_dir, "Broken.st"), "w", encoding="utf-8") as fh:
        fh.write("PROGRAM Broken\nVAR\nEND_VAR")
    # Make the file unreadable by pointing at a directory of the same name.
    broken = os.path.join(bad_dir, "Broken.st")
    os.remove(broken)
    os.makedirs(broken)  # a directory named *.st cannot be read as a file

    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    # Simulate the read failure exactly as build_snapshot would record it.
    if not any(d.kind == "project-read" for d in snap.diagnostics):
        from cds_static_analyzer.model import Location

        snap.diagnostics.append(
            Diagnostic(
                "project-read",
                "cannot read POUs/Broken.st",
                location=Location("POUs/Broken.st"),
            )
        )
    result = run_analysis(ws, snap, config, RunOptions(rule_filter={"CTS0002"}))
    # The runner skips CTS0002 and reports the missing capability instead
    # of a false "clean".
    assert result.findings == []
    assert result.complete is False
    kinds = {d.kind for d in result.diagnostics}
    assert kinds & {"declarations", "project-symbols"}

def test_unknown_st_unit_stays_in_snapshot(tmp_path):
    """An unclassifiable .st file stays kind=UNKNOWN, it is not dropped."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    garbage = os.path.join(root, "project-view", "POUs", "Garbage.st")
    with open(garbage, "w", encoding="utf-8") as fh:
        fh.write("this is not st at all\n")
    ws = WorkspaceResolver(workspace=root).resolve()
    snap = build_st_snapshot(ws.project_view)
    unknown = [u for u in snap.units if u.kind == "unknown"]
    assert [u.id for u in unknown] == ["POUs/Garbage.st#Garbage"]
    assert snap.diagnostics == []  # readable file: not a read error

def test_unknown_unit_reported_only_by_rules_that_needed_it(tmp_path):
    """A rule that required DECLARATIONS reports the unparsed unit as a
    Diagnostic; a pure text rule does not - no false "clean" either way."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    garbage = os.path.join(root, "project-view", "POUs", "Garbage.st")
    with open(garbage, "w", encoding="utf-8") as fh:
        fh.write("this is not st at all\n")
    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)

    r1 = run_analysis(ws, snap, config, RunOptions(rule_filter={"CTS0002"}))
    assert r1.complete is False
    assert any(
        d.kind == "st-parse" and d.unit_id == "POUs/Garbage.st#Garbage"
        for d in r1.diagnostics
    )

    r2 = run_analysis(ws, snap, config, RunOptions(rule_filter={"CTS0001"}))
    assert r2.complete is True
    assert all(d.kind != "st-parse" for d in r2.diagnostics)

def test_severity_override_applies_without_mutating_registry(tmp_path):
    """A configured severity override lands on the run-local findings only:
    summary/exit policy all see it, and the registry keeps the declared
    severity so a later run starts from the declared value."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    cfg_path = os.path.join(root, "cts-analyze.toml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write('[rules.CTS0001]\nseverity = "danger"\n')

    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    result = run_analysis(ws, snap, config, RunOptions())

    danger = [f for f in result.findings if f.rule_id == "CTS0001"]
    assert danger
    assert all(f.severity == "danger" for f in danger)
    assert result.summary.by_severity["danger"] == len(danger)

    # Exit policy consumes the effective severity: fail_on=danger now fails.
    config.fail_on = "danger"
    assert exit_code(result, config) == 1

    # The registry was not mutated: the declared severity survives.
    assert load_builtin_rules()["CTS0001"].severity == "suspicious"

    # A run without the override starts from the declared rule severity.
    plain = ResolvedConfig()
    result2 = run_analysis(ws, snap, plain, RunOptions())
    restored = [f for f in result2.findings if f.rule_id == "CTS0001"]
    assert restored and all(f.severity == "suspicious" for f in restored)
    plain.fail_on = "danger"
    assert exit_code(result2, plain) == 0

def test_rule_option_reaches_rule_and_changes_output(tmp_path):
    """A configured option reaches the rule and changes its output.

    CTS0004 min_occurrences defaults to 2. PB.st has two 4095 literals at
    (9,27) and (10,10) - they occur exactly twice. With min_occurrences=3
    both should disappear (not enough occurrences).
    """
    root = str(tmp_path / "sync")
    copy_fixture(root)
    cfg_path = os.path.join(root, "cts-analyze.toml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write('[rules.CTS0004]\noptions.min_occurrences = 3\n')

    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    result = run_analysis(ws, snap, config, RunOptions(rule_filter={"CTS0004"}))

    pb = [f for f in result.findings if f.location.path == "POUs/PB.st"]
    # Both 4095 findings should be gone (they occur exactly twice)
    assert pb == []
    # Verify the default config would find them: one merged finding standing
    # for both occurrences (CTS0004 merges by identity).
    default_result = run_analysis(ws, snap, ResolvedConfig(), RunOptions(rule_filter={"CTS0004"}))
    pb_default = [f for f in default_result.findings if f.location.path == "POUs/PB.st"]
    assert len(pb_default) == 1
    assert pb_default[0].member_lines == [9, 10]

def test_undeclared_option_key_yields_one_diagnostic(tmp_path):
    """An unknown option key yields exactly one ``rule-option`` Diagnostic
    per rule per run, not one per unit."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    cfg_path = os.path.join(root, "cts-analyze.toml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write('[rules.CTS0001]\noptions.typo_min_tokens = 6\n')

    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    result = run_analysis(ws, snap, config, RunOptions(rule_filter={"CTS0001"}))

    # One and only one ``rule-option`` Diagnostic for the typo.
    diags = [d for d in result.diagnostics if d.kind == "rule-option"]
    assert len(diags) == 1
    assert "typo_min_tokens" in diags[0].message
    assert result.complete is False
    # The rule still ran and found its findings (fallback to defaults).
    assert len(result.findings) > 0

def test_type_mismatched_option_falls_back_to_default(tmp_path):
    """A configured option with the wrong type falls back to the declared
    default and yields one ``rule-option`` Diagnostic."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    cfg_path = os.path.join(root, "cts-analyze.toml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        # min_tokens should be an int, not a string
        fh.write('[rules.CTS0001]\noptions.min_tokens = "not_a_number"\n')

    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    result = run_analysis(ws, snap, config, RunOptions(rule_filter={"CTS0001"}))

    # One ``rule-option`` Diagnostic for the type mismatch.
    diags = [d for d in result.diagnostics if d.kind == "rule-option"]
    assert len(diags) == 1
    assert "str" in diags[0].message and "int" in diags[0].message
    assert result.complete is False
    # The rule still ran with the default (min_tokens=4), finding the comment.
    assert len(result.findings) > 0

def test_baseline_with_other_fingerprint_schema_does_not_hide(tmp_path):
    """A baseline recorded under a different fingerprint schema must not
    silently match: every current finding surfaces as new."""
    from cds_static_analyzer import state as st
    from cds_static_analyzer.state import baseline_fingerprints

    root = str(tmp_path / "sync")
    copy_fixture(root)
    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_st_snapshot(ws.project_view)
    result = run_analysis(ws, snap, config, RunOptions())

    # Simulate a baseline written under fingerprint schema 2: its entries
    # carry cts2: fingerprints that can never match current cts1: ones.
    st.write_baseline(
        ws.state_dir,
        [
            {
                "fingerprint": "cts2:" + f.fingerprint[5:],
                "rule_id": f.rule_id,
                "unit_id": f.unit_id or "",
                "message": f.message,
            }
            for f in result.findings
        ],
    )
    entries, schema = st.read_baseline(ws.state_dir)
    assert schema == 1

    current = {f.fingerprint for f in result.findings}
    assert current.isdisjoint(baseline_fingerprints(entries))
    # 19 findings, all distinct: merging removed the pair of same-value
    # CTS0004 hits on PB.st that used to share one fingerprint.
    assert len(current) == 19  # nothing silently hidden
    assert len(result.findings) == 19
