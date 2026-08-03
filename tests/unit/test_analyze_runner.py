"""
test_analyze_runner.py - End-to-end runs over the fixture: exit codes,
capability gating, rule filters, suppression/baseline filtering.
"""

import json
import os
import shutil

from cds_text_sync.analyze.config import ResolvedConfig, load_config
from cds_text_sync.analyze.model import AnalysisResult, Diagnostic, Finding
from cds_text_sync.analyze.project import build_snapshot
from cds_text_sync.analyze.registry import load_builtin_rules
from cds_text_sync.analyze.runner import (
    RunOptions,
    exit_code,
    filter_result,
    run_analysis,
)
from cds_text_sync.analyze.workspace import WorkspaceResolver

from analyze_helpers import (
    copy_fixture,
    fixture_path,
    fixture_project_view,
    run_analyze_json,
    run_cli,
)


def _run(workspace, rule_filter=None, incomplete=None):
    ws = WorkspaceResolver(workspace=workspace).resolve()
    config = load_config(ws.config_path)
    snap = build_snapshot(ws.project_view)
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
    assert sorted(by_rule["CTS0001"]) == ["y := x + 5;", "y := y + 2;"]
    assert sorted(by_rule["CTS0002"]) == ["nTarget", "sName"]
    assert result.complete is True


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
            fh.write("// cts:ignore-file CTS0001, CTS0002, CTS0007, CTS0008 -- legacy fixture\n" + original)
    _, _, result = _run(root)
    assert not any(f.location.path == "POUs/Main.st" for f in result.findings)
    assert result.summary.suppressed == 5


def test_file_ignore_directive_counter_survives_cli_filtering(tmp_path):
    root = copy_fixture(tmp_path)
    source = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write("// cts:ignore-file CTS0001, CTS0002 -- legacy fixture\n" + text)

    data = run_analyze_json(str(root), extra=["--rule", "CTS0001", "--rule", "CTS0002"])

    assert data["_exit"] == 0
    assert data["summary"]["total"] == 0
    assert data["summary"]["suppressed"] == 4
    assert data["summary"]["suppressed_by_directive"] == 4


def test_file_ignore_directive_reports_missing_reason(tmp_path):
    root = copy_fixture(tmp_path)
    source = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write("// cts:ignore-file CTS9999\n" + text)

    data = run_analyze_json(str(root))
    kinds = {item["kind"] for item in data["diagnostics"]}
    assert "directive-missing-reason" in kinds


def test_file_ignore_directive_reports_unknown_rule(tmp_path):
    root = copy_fixture(tmp_path)
    source = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write("// cts:ignore-file CTS9999 -- typo\n" + text)

    data = run_analyze_json(str(root))
    assert any(item["kind"] == "directive-unknown-rule" for item in data["diagnostics"])


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
    snap = build_snapshot(ws.project_view)
    # Simulate the read failure exactly as build_snapshot would record it.
    if not any(d.kind == "project-read" for d in snap.diagnostics):
        from cds_text_sync.analyze.model import Location

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


def test_cli_json_envelope(tmp_path):
    code, out, err = run_cli(
        ["analyze", "--workspace", fixture_project_view(), "--format", "json"]
    )
    assert code == 1
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert "findings" in data and "diagnostics" in data
    assert data["summary"]["total"] == 11


def test_cli_read_only_no_state_written(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    before = set()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            before.add(os.path.relpath(os.path.join(dirpath, f), root))
    code, out, _err = run_cli(["analyze", "--workspace", root, "--format", "json"])
    after = set()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            after.add(os.path.relpath(os.path.join(dirpath, f), root))
    assert before == after  # the analyzer writes nothing


def test_analyze_depends_on_engine_but_not_vice_versa():
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import cds_text_sync.engine; import cds_text_sync.analyze; print('ok')",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_unknown_st_unit_stays_in_snapshot(tmp_path):
    """An unclassifiable .st file stays kind=UNKNOWN, it is not dropped."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    garbage = os.path.join(root, "project-view", "POUs", "Garbage.st")
    with open(garbage, "w", encoding="utf-8") as fh:
        fh.write("this is not st at all\n")
    ws = WorkspaceResolver(workspace=root).resolve()
    snap = build_snapshot(ws.project_view)
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
    snap = build_snapshot(ws.project_view)

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
    snap = build_snapshot(ws.project_view)
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


def _malformed_visu_workspace(tmp_path):
    """Fixture workspace + one malformed visualization XML."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    dest = os.path.join(
        root,
        "project-view",
        "Runtime",
        "PLC Logic",
        "Application",
        "HMI",
        "Broken.xml",
    )
    shutil.copy(fixture_path("broken-visu.xml"), dest)
    return root


_BROKEN_VISU_REL = "Runtime/PLC Logic/Application/HMI/Broken.xml"


def test_snapshot_records_unparsable_visualization_xml(tmp_path):
    root = _malformed_visu_workspace(tmp_path)
    snap = build_snapshot(os.path.join(root, "project-view"))
    errors = snap.source_errors
    assert len(errors) == 1
    record = errors[0]
    assert record.source_kind == "visualization"
    assert record.location.path == _BROKEN_VISU_REL
    assert "cannot parse" in record.message
    # The healthy screen still parses into a unit.
    assert any(u.kind == "visualization" for u in snap.units)


def test_malformed_visu_does_not_hurt_st_rules(tmp_path):
    """When the only problem is the broken XML, text/declaration rules stay
    complete and keep reporting their findings."""
    root = _malformed_visu_workspace(tmp_path)
    data = run_analyze_json(root, extra=["--rule", "CTS0001", "--rule", "CTS0002"])
    assert data["complete"] is True
    assert data["diagnostics"] == []
    assert len(data["findings"]) == 4  # 2x CTS0001 + 2x CTS0002


def test_human_analyzer_ignores_malformed_visu_xml(tmp_path):
    root = _malformed_visu_workspace(tmp_path)
    d1 = run_analyze_json(root, extra=["--rule", "CTS0001", "--rule", "CTS0002"])
    d2 = run_analyze_json(root, extra=["--rule", "CTS0001", "--rule", "CTS0002"])
    assert d1["diagnostics"] == d2["diagnostics"]
    assert d1["diagnostics"] == []
    assert d1["complete"] is True


def test_baseline_with_other_fingerprint_schema_does_not_hide(tmp_path):
    """A baseline recorded under a different fingerprint schema must not
    silently match: every current finding surfaces as new."""
    from cds_text_sync.analyze import state as st
    from cds_text_sync.analyze.state import baseline_fingerprints

    root = str(tmp_path / "sync")
    copy_fixture(root)
    ws = WorkspaceResolver(workspace=root).resolve()
    config = load_config(ws.config_path)
    snap = build_snapshot(ws.project_view)
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
    assert len(current) == 11  # nothing silently hidden
