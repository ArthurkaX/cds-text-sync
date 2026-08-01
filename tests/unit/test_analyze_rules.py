"""
test_analyze_rules.py - Unit tests for the built-in rules on small snippets.
"""

from cds_text_sync.analyze import project as pm
from cds_text_sync.analyze.config import ResolvedConfig
from cds_text_sync.analyze.project import ProjectSnapshot
from cds_text_sync.analyze.rules.impl.commented_code import check as cts0001
from cds_text_sync.analyze.rules.impl.unused_input import check as cts0002
from cds_text_sync.analyze.runner import AnalysisContext
from cds_text_sync.analyze.workspace import Workspace


def _ctx(snapshot):
    workspace = Workspace(root=".", project_view=".", state_dir=".")
    return AnalysisContext(workspace, snapshot, ResolvedConfig())


def _st_unit(text):
    return pm._build_st_unit("snippet.st", text)


# ---------------------------------------------------------------------------
# CTS0001 - commented-out code
# ---------------------------------------------------------------------------


def test_cts0001_flags_assignment_in_comment():
    unit = _st_unit(
        "PROGRAM P\nVAR\n x : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n// x := 1;\nx := 2;\n"
    )
    findings = list(cts0001(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0001"
    assert findings[0].location.line == 8


def test_cts0001_flags_call_in_comment():
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n(* MyFunc(a, b); *)\n"
    )
    findings = list(cts0001(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1


def test_cts0001_ignores_prose_comments():
    unit = _st_unit(
        "PROGRAM P\nVAR\n x : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// disabled for TICKET-482\n(* this input is never read *)\n"
        "x := 1;\n"
    )
    findings = list(cts0001(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert findings == []


def test_cts0001_does_not_see_comment_markers_in_strings():
    unit = _st_unit(
        "PROGRAM P\nVAR\n s : STRING;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "s := '// not a comment';\n"
    )
    findings = list(cts0001(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert findings == []


# ---------------------------------------------------------------------------
# CTS0002 - unused input
# ---------------------------------------------------------------------------


def test_cts0002_flags_unused_input():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_INPUT\n used : INT;\n dead : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n out : BOOL;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "out := used > 0;\n"
    )
    findings = list(cts0002(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert [f.anchor for f in findings] == ["dead"]


def test_cts0002_reads_via_owned_units():
    fb = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_INPUT\n speed : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n out : BOOL;\nEND_VAR\n\nIMPLEMENTATION\n\nout := 0;\n"
    )
    method = _st_unit(
        "METHOD Run\nVAR_INPUT\n n : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "THIS.speed := n;\n"
    )
    assert fb is not None and method is not None
    # Unit identity follows the file stem; pin it for the snippet.
    fb.qualified_name = "FB"
    method.owner_name = "FB"
    snap = ProjectSnapshot(".", [fb, method])
    findings = list(cts0002(fb, _ctx(snap)))
    assert findings == []  # speed is read by the owned method


def test_cts0002_qualified_access_counts_as_read():
    unit = _st_unit(
        "METHOD M\nVAR_INPUT\n a : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "THIS.a := THIS.a + 1;\n"
    )
    findings = list(cts0002(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert findings == []


def test_cts0002_super_access_counts_as_read():
    unit = _st_unit(
        "METHOD M\nVAR_INPUT\n a : INT;\nEND_VAR\n\nIMPLEMENTATION\n\nSUPER^.a := 0;\n"
    )
    findings = list(cts0002(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert findings == []


def test_cts0002_no_findings_without_inputs():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR\n x : INT;\nEND_VAR\n\nIMPLEMENTATION\n\nF := x;\n"
    )
    findings = list(cts0002(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert findings == []


def test_cts0002_location_points_at_member_line():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_INPUT\n a : INT;\n b : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n out : BOOL;\nEND_VAR\n\nIMPLEMENTATION\n\nout := a > 0;\n"
    )
    findings = list(cts0002(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].location.line == 4  # the 'b' member line
    assert findings[0].anchor == "b"
