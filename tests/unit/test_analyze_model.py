"""
test_analyze_model.py - Result model: finding/diagnostic separation,
deterministic sorting, severity ranks, envelope.
"""

from cds_static_analyzer.model import (
    AnalysisResult,
    Diagnostic,
    Finding,
    Location,
    normalize_context,
    severity_rank,
)


def _finding(rule_id, path, line, message="m", fingerprint=None):
    f = Finding(
        rule_id=rule_id,
        severity="suspicious",
        message=message,
        location=Location(path, line, 1),
    )
    f.fingerprint = fingerprint
    return f


def test_severity_ranks():
    assert severity_rank("danger") < severity_rank("suspicious")
    assert severity_rank("suspicious") < severity_rank("style")
    assert severity_rank("bogus") > severity_rank("style")


def test_finding_vs_diagnostic_distinction():
    f = Finding("CTS0001", "suspicious", "problem", Location("a.st", 1))
    d = Diagnostic("git-base", "no git", Location(""))
    assert f.rule_id == "CTS0001"
    assert d.kind == "git-base"
    assert d.rule_id is None


def test_deterministic_sort_order():
    result = AnalysisResult()
    result.findings = [
        _finding("CTS0002", "POUs/B.st", 1, fingerprint="b"),
        _finding("CTS0001", "POUs/A.st", 9, fingerprint="a"),
        _finding("CTS0002", "POUs/A.st", 1, fingerprint="c"),
    ]
    result.sort()
    keys = [
        (f.location.path, f.location.line, f.rule_id, f.fingerprint)
        for f in result.findings
    ]
    assert keys == sorted(keys)


def test_envelope_fields():
    result = AnalysisResult()
    result.findings = [_finding("CTS0001", "a.st", 1)]
    result.diagnostics = [Diagnostic("read-error", "cannot read", Location("x.st"))]
    result.summary.add_finding(result.findings[0])
    doc = result.to_dict()
    assert doc["schema_version"] == 1
    assert doc["complete"] is True
    assert len(doc["findings"]) == 1
    assert len(doc["diagnostics"]) == 1
    assert doc["summary"]["total"] == 1


def test_normalize_context():
    assert normalize_context("  x := 5 ; ") == "x := 5 ;"
    assert normalize_context("X := 5;") == "x := 5;"
    assert normalize_context("") == ""
