"""Contracts for the finding-merge pass.

The pass collapses findings a rule declares to be one problem: a contiguous
run of lines (``merge="adjacent"``) or repeated occurrences the state layer
already cannot tell apart (``merge="identical"``). It runs before
fingerprinting, so a merged finding keeps the fingerprint its first member
had on its own.
"""

from cds_static_analyzer import project as pm
from cds_static_analyzer.config import ResolvedConfig
from cds_static_analyzer.project import ProjectSnapshot
from cds_static_analyzer.registry import load_builtin_rules

from st_helpers import run_rule


def _st_unit(text, path="snippet.st"):
    return pm._build_st_unit(path, text)


# ---------------------------------------------------------------------------
# merge="adjacent"
# ---------------------------------------------------------------------------


def test_adjacent_comment_lines_collapse_into_one_finding():
    """The reported case from the field: a block of commented-out lines is one
    decision, not one per line."""
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// auxString := ' 270 SEND:2: ';\n"
        "// auxString := CONCAT(auxString, TO_STRING(seqNumber));\n"
        "// auxString := CONCAT(auxString, ' end');\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    merged = findings[0]
    assert merged.location.line == 7
    assert merged.location.end_line == 9
    assert merged.member_count == 3
    assert merged.member_lines == [7, 8, 9]
    # The message is untouched - the count lives in member_count so it cannot
    # leak into baseline diffs or be printed twice by a renderer.
    assert "(3" not in merged.message


def test_separated_comment_blocks_stay_separate():
    """A blank or live line between comments ends the run."""
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// x := 1;\n"
        "y := 0;\n"
        "z := 0;\n"
        "// x := 2;\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
    assert [f.location.line for f in findings] == [7, 10]
    assert all(f.member_count is None for f in findings)


def test_adjacency_is_measured_from_end_line_not_line():
    """One CTS0001 comment can itself span several lines. The next finding is
    adjacent to where the previous one ends, not where it starts."""
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "(* x := 1;\n"
        "   y := 2; *)\n"
        "// z := 3;\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
    first = run_rule(
        "CTS0001", ProjectSnapshot(".", [unit]), options={"merge": False}
    )[0]
    assert first.location.end_line == 8  # the block comment covers 7-8
    assert len(findings) == 1
    assert findings[0].location.line == 7
    assert findings[0].member_lines == [7, 9]


def test_adjacent_declaration_findings_merge_but_distant_ones_do_not():
    """CTS0008 on one unit: neighbouring declarations are one alignment
    problem, a declaration four lines below is a separate one."""
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    aShort : INT;\n"
        "    bLongerName  : INT;\n"
        "    cLongerStill   : INT;\n"
        "\n"
        "    (* second group *)\n"
        "    dOne : INT;\n"
        "    eLongerName   : INT;\n"
        "END_VAR\n"
    )
    findings = run_rule("CTS0008", ProjectSnapshot(".", [unit]))
    assert [f.location.line for f in findings] == [3, 8]
    assert findings[0].member_count == 2
    assert findings[0].member_lines == [3, 4]
    assert findings[0].location.end_line == 4
    assert findings[1].member_count is None


# ---------------------------------------------------------------------------
# merge="identical"
# ---------------------------------------------------------------------------


def test_identical_occurrences_collapse_without_faking_a_line_range():
    """Two hits far apart are one identity but not one contiguous region, so
    the merged finding carries member_lines and no widened end_line."""
    body = ["PROGRAM P", "IMPLEMENTATION", "", "value := 4095;"]
    body += ["filler := 0;"] * 8
    body += ["other := 4095;"]
    unit = _st_unit("\n".join(body) + "\n")
    findings = run_rule("CTS0004", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    merged = findings[0]
    assert merged.location.line == 4
    assert merged.member_lines == [4, 13]
    # A 10-line span would be a lie: only lines 4 and 13 are affected.
    assert (merged.location.end_line or merged.location.line) == 4


def test_identical_merge_collapses_what_the_state_layer_treats_as_one():
    """Repeated literals are one decision, so they collapse into one finding.

    With merging off they stay separate and each is still addressable - the
    occurrence numbering keeps their fingerprints apart.
    """
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\nIF value > 75 THEN result := 75; END_IF;\n"
    )
    unmerged = run_rule(
        "CTS0004", ProjectSnapshot(".", [unit]), options={"merge": False}
    )
    assert len(unmerged) == 2
    assert len({f.fingerprint for f in unmerged}) == 2
    merged = run_rule("CTS0004", ProjectSnapshot(".", [unit]))
    assert len(merged) == 1
    assert len({f.fingerprint for f in merged}) == 1
    # Collapsing keeps the identity of the first occurrence, never the second.
    assert merged[0].fingerprint == unmerged[0].fingerprint


# ---------------------------------------------------------------------------
# Fingerprint stability and the project switch
# ---------------------------------------------------------------------------


def test_merged_fingerprint_equals_the_first_members_own_fingerprint():
    """Merging must not invalidate stored state: an existing suppression that
    pointed at the first line of a block keeps matching."""
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// x := 1;\n"
        "// y := 2;\n"
    )
    snapshot = ProjectSnapshot(".", [unit])
    unmerged = run_rule("CTS0001", snapshot, options={"merge": False})
    merged = run_rule("CTS0001", snapshot)
    assert len(unmerged) == 2
    assert len(merged) == 1
    assert merged[0].fingerprint == unmerged[0].fingerprint


def test_merge_option_false_restores_per_line_findings():
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// x := 1;\n"
        "// y := 2;\n"
        "// z := 3;\n"
    )
    snapshot = ProjectSnapshot(".", [unit])
    assert len(run_rule("CTS0001", snapshot)) == 1
    off = run_rule("CTS0001", snapshot, options={"merge": False})
    assert [f.location.line for f in off] == [7, 8, 9]
    assert all(f.member_count is None for f in off)


def test_malformed_merge_option_falls_back_to_the_declared_default():
    """A wrong-typed option is a reported rule-option Diagnostic, not a silent
    behaviour change: merging stays on."""
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n// x := 1;\n// y := 2;\n"
    )
    findings = run_rule(
        "CTS0001", ProjectSnapshot(".", [unit]), options={"merge": "no"}
    )
    assert len(findings) == 1
    assert findings[0].member_count == 2


def test_merging_rules_declare_the_merge_option():
    """Every rule with a merge strategy must expose the project switch, or
    ``options.merge = false`` would be reported as an unknown key."""
    for rule in load_builtin_rules().values():
        if getattr(rule, "merge", None):
            assert rule.options.get("merge") is True, rule.id


def test_rulespec_rejects_an_unknown_merge_strategy():
    import pytest

    from cds_static_analyzer.rules_api import Capability, RuleSpec, RuleSpecError, Scope

    def dummy_check(unit, ctx):
        pass

    def _spec(merge):
        return RuleSpec(
            id="CTS9999",
            title="test",
            severity="style",
            scope=Scope.UNIT,
            requires={Capability.ST_TEXT},
            kinds="CALLABLE",
            summary="test",
            check=dummy_check,
            topic="Code quality",
            merge=merge,
        )

    with pytest.raises(RuleSpecError):
        _spec("nearby").validate()
    for strategy in (None, "adjacent", "identical"):
        _spec(strategy).validate()  # should not raise


# ---------------------------------------------------------------------------
# Summary and serialization
# ---------------------------------------------------------------------------


def test_summary_counts_merged_findings():
    """The counter answers "how many decisions", so a block counts once."""
    from cds_static_analyzer.project import build_st_snapshot
    from cds_static_analyzer.runner import RunOptions, run_analysis
    from cds_static_analyzer.workspace import Workspace

    from st_helpers import fixture_project_view

    view = fixture_project_view()
    result = run_analysis(
        Workspace(root=".", project_view=view, state_dir="."),
        build_st_snapshot(view),
        ResolvedConfig(),
        RunOptions(),
    )
    assert result.summary.total == len(result.findings)
    assert sum(result.summary.by_rule.values()) == len(result.findings)
    assert sum(result.summary.by_severity.values()) == len(result.findings)


def test_to_dict_carries_the_merge_fields_only_when_merged():
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n// x := 1;\n// y := 2;\n"
    )
    snapshot = ProjectSnapshot(".", [unit])
    merged = run_rule("CTS0001", snapshot)[0].to_dict()
    assert merged["member_count"] == 2
    assert merged["member_lines"] == [7, 8]
    assert merged["location"]["end_line"] == 8

    single = run_rule("CTS0001", snapshot, options={"merge": False})[0].to_dict()
    assert "member_count" not in single
    assert "member_lines" not in single
