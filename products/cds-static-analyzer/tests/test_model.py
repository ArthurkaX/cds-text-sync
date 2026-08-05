"""Result model: finding/diagnostic separation and deterministic ordering."""

from cds_static_analyzer.model import AnalysisResult, Diagnostic, Finding, Location, normalize_context, severity_rank


def _finding(rule_id, path, line, message="m", fingerprint=None):
    finding = Finding(rule_id=rule_id, severity="suspicious", message=message, location=Location(path, line, 1))
    finding.fingerprint = fingerprint
    return finding


def test_severity_ranks():
    assert severity_rank("danger") < severity_rank("suspicious")
    assert severity_rank("suspicious") < severity_rank("style")
    assert severity_rank("bogus") > severity_rank("style")


def test_finding_vs_diagnostic_distinction():
    finding = Finding("CTS0001", "suspicious", "problem", Location("a.st", 1))
    diagnostic = Diagnostic("git-base", "no git", Location(""))
    assert finding.rule_id == "CTS0001"
    assert diagnostic.kind == "git-base"
    assert diagnostic.rule_id is None


def test_deterministic_sort_order():
    result = AnalysisResult()
    result.findings = [
        _finding("CTS0002", "POUs/B.st", 1, fingerprint="b"),
        _finding("CTS0001", "POUs/A.st", 9, fingerprint="a"),
        _finding("CTS0002", "POUs/A.st", 1, fingerprint="c"),
    ]
    result.sort()
    keys = [(item.location.path, item.location.line, item.rule_id, item.fingerprint) for item in result.findings]
    assert keys == sorted(keys)


def test_envelope_fields():
    result = AnalysisResult()
    result.findings = [_finding("CTS0001", "a.st", 1)]
    result.diagnostics = [Diagnostic("read-error", "cannot read", Location("x.st"))]
    result.summary.add_finding(result.findings[0])
    document = result.to_dict()
    assert document["schema_version"] == 1
    assert document["complete"] is True
    assert len(document["findings"]) == 1
    assert len(document["diagnostics"]) == 1
    assert document["summary"]["total"] == 1


def test_normalize_context():
    assert normalize_context("  x := 5 ; ") == "x := 5 ;"
    assert normalize_context("X := 5;") == "x := 5;"
    assert normalize_context("") == ""
