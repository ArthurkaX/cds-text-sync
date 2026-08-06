"""Contracts for numbering findings the identity tuple cannot tell apart.

Two findings of one rule can share ``(unit_id, anchor, context)`` - two
identical statements at the same block level, say - and would then share a
fingerprint, so suppressing one silently suppressed the others.  Duplicates
past the first are numbered in document order; the first keeps the identity it
had before numbering existed, which is what lets stored state survive.
"""

from cds_static_analyzer import project as pm
from cds_static_analyzer.config import ResolvedConfig
from cds_static_analyzer.fingerprint import fingerprint
from cds_static_analyzer.project import ProjectSnapshot, build_st_snapshot
from cds_static_analyzer.runner import RunOptions, run_analysis
from cds_static_analyzer.workspace import Workspace

from st_helpers import fixture_project_view, run_rule


def _st_unit(text, path="snippet.st"):
    return pm._build_st_unit(path, text)


def _duplicate_unit(path="snippet.st"):
    """A unit with the same magic literal twice, far enough apart to stay two
    findings under ``merge="adjacent"`` rules and identical under CTS0004."""
    body = ["PROGRAM P", "IMPLEMENTATION", "", "value := 4095;"]
    body += ["filler := 0;"] * 8
    body += ["other := 4095;"]
    return _st_unit("\n".join(body) + "\n", path=path)


def test_duplicates_get_distinct_fingerprints():
    findings = run_rule(
        "CTS0004", ProjectSnapshot(".", [_duplicate_unit()]), options={"merge": False}
    )
    assert [f.location.line for f in findings] == [4, 13]
    assert len({f.fingerprint for f in findings}) == 2


def test_first_occurrence_keeps_the_unnumbered_identity():
    """An existing suppression targets the first occurrence, so its fingerprint
    must be the plain one this rule would have produced all along."""
    findings = run_rule(
        "CTS0004", ProjectSnapshot(".", [_duplicate_unit()]), options={"merge": False}
    )
    first = findings[0]
    assert first.fingerprint == fingerprint(
        first.rule_id, first.unit_id, first.anchor or first.message, first.context
    )
    assert findings[1].fingerprint != first.fingerprint


def test_numbering_follows_document_order():
    """The later line is the one that gets a number, whatever order the rule
    happened to yield in."""
    findings = run_rule(
        "CTS0004", ProjectSnapshot(".", [_duplicate_unit()]), options={"merge": False}
    )
    later = findings[1]
    assert later.fingerprint == fingerprint(
        later.rule_id, later.unit_id, later.anchor or later.message,
        later.context, occurrence=1,
    )


def test_numbering_does_not_leak_across_units():
    """``unit_id`` is already part of identity, so the same statement in two
    units is not a duplicate and neither copy is numbered."""
    snapshot = ProjectSnapshot(
        ".", [_duplicate_unit(path="a.st"), _duplicate_unit(path="b.st")]
    )
    findings = run_rule("CTS0004", snapshot, options={"merge": False})
    assert len(findings) == 4
    firsts = [f for f in findings if f.location.line == 4]
    assert len(firsts) == 2
    for finding in firsts:
        assert finding.fingerprint == fingerprint(
            finding.rule_id, finding.unit_id, finding.anchor or finding.message,
            finding.context,
        )


def test_no_two_findings_in_the_fixture_share_a_fingerprint():
    view = fixture_project_view()
    result = run_analysis(
        Workspace(root=".", project_view=view, state_dir="."),
        build_st_snapshot(view),
        ResolvedConfig(),
        RunOptions(),
    )
    assert len({f.fingerprint for f in result.findings}) == len(result.findings)
