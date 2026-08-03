"""
test_analyze_rules.py - Unit tests for the built-in rules on small snippets.
"""

from cds_text_sync.analyze import project as pm
from cds_text_sync.analyze.config import ResolvedConfig
from cds_text_sync.analyze.project import ProjectSnapshot
from cds_text_sync.analyze.rules.impl.commented_code import check as cts0001
from cds_text_sync.analyze.rules.impl.unused_input import check as cts0002
from cds_text_sync.analyze.rules.impl.magic_number import check as cts0004
from cds_text_sync.analyze.rules.impl.case_without_else import check as cts0003
from cds_text_sync.analyze.rules.impl.array_bounds import check as cts0006
from cds_text_sync.analyze.rules.impl.indentation import check as cts0007
from cds_text_sync.analyze.rules.impl.variable_alignment import check as cts0008
from cds_text_sync.analyze.rules.impl.output_not_assigned import check as cts0009
from cds_text_sync.analyze.rules.impl.redundant_boolean_if import check as cts0010
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


# ---------------------------------------------------------------------------
# CTS0003 - CASE without ELSE
# ---------------------------------------------------------------------------


def test_cts0003_flags_case_without_else():
    unit = _st_unit(
        "PROGRAM P\nVAR\n state : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "CASE state OF\n  1: state := 2;\nEND_CASE;\n"
    )
    findings = list(cts0003(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0003"
    assert findings[0].severity == "suspicious"
    assert findings[0].location.line == 8


def test_cts0003_accepts_case_with_else():
    unit = _st_unit(
        "PROGRAM P\nVAR\n state : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "CASE state OF\n  1: state := 2;\nELSE\n  state := 0;\nEND_CASE;\n"
    )
    assert list(cts0003(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


def test_cts0003_does_not_count_nested_if_else_for_case():
    unit = _st_unit(
        "PROGRAM P\nVAR\n state : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "CASE state OF\n  1: IF state > 0 THEN state := 2; ELSE state := 0; END_IF;\n"
        "END_CASE;\n"
    )
    findings = list(cts0003(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# CTS0004 - magic numeric literal
# ---------------------------------------------------------------------------


def test_cts0004_flags_repeated_nontrivial_numbers():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "IF value > 75 THEN result := 75; END_IF;\n"
    )
    findings = list(cts0004(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 2
    assert all(f.rule_id == "CTS0004" for f in findings)
    assert all(f.severity == "style" for f in findings)
    assert [f.location.line for f in findings] == [4, 4]


def test_cts0004_ignores_trivial_numbers_comments_and_strings():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "value := 0; other := 1; third := -1; small := 2;\n"
        "(* 75 75 *) value := '75 75';\n"
    )
    assert list(cts0004(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


def test_cts0004_ignores_array_indexes_and_bit_selectors():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "data[25] := 1; data[25] := 2; flags[25].3 := TRUE; flags[25].3 := FALSE;\n"
    )
    assert list(cts0004(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


def test_cts0004_does_not_flag_single_occurrence():
    unit = _st_unit("PROGRAM P\nIMPLEMENTATION\n\nvalue := 75;\n")
    assert list(cts0004(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


# ---------------------------------------------------------------------------
# CTS0006 - array index outside bounds
# ---------------------------------------------------------------------------


def test_cts0006_flags_constant_indexes_outside_declared_bounds():
    unit = _st_unit(
        "PROGRAM P\nVAR\n values : ARRAY[1..10] OF INT;\nEND_VAR\n\n"
        "IMPLEMENTATION\n\nvalues[0] := 1; values[11] := 2;\n"
    )
    findings = list(cts0006(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 2
    assert all(f.rule_id == "CTS0006" for f in findings)
    assert all(f.severity == "danger" for f in findings)
    assert [f.location.line for f in findings] == [8, 8]


def test_cts0006_accepts_nonzero_lower_bound_and_valid_indexes():
    unit = _st_unit(
        "PROGRAM P\nVAR\n values : ARRAY[-2..5] OF INT;\nEND_VAR\n\n"
        "IMPLEMENTATION\n\nvalues[-2] := 1; values[5] := 2;\n"
    )
    assert list(cts0006(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


def test_cts0006_does_not_judge_variable_or_multidimensional_indexes():
    unit = _st_unit(
        "PROGRAM P\nVAR\n values : ARRAY[1..10] OF INT;\n grid : ARRAY[1..2, 1..2] OF INT;\n i : INT;\nEND_VAR\n\n"
        "IMPLEMENTATION\n\nvalues[i] := 1; grid[3, 3] := 2;\n"
    )
    assert list(cts0006(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


# ---------------------------------------------------------------------------
# CTS0007 - structural indentation
# ---------------------------------------------------------------------------


def test_cts0007_flags_indentation_that_is_deeper_than_the_real_nesting():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "IF ready THEN\n"
        "\tFOR i := 1 TO 10 DO\n"
        "\t\tvalue := i;\n"
        "\t\t\ttotal := total + value;\n"
        "\tEND_FOR\n"
        "END_IF;\n"
    )
    findings = list(cts0007(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0007"
    assert findings[0].severity == "style"
    assert findings[0].location.line == 7


def test_cts0007_ignores_declaration_table_and_continuation_alignment():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "\tshort : INT;\n"
        "\tlong_name : BOOL;\n"
        "END_VAR\n\nIMPLEMENTATION\n\n"
        "IF a OR\n"
        "\t b THEN\n"
        "\tx := 1;\n"
        "END_IF;\n"
    )
    assert list(cts0007(unit, _ctx(ProjectSnapshot(".", [unit])))) == []


# ---------------------------------------------------------------------------
# CTS0008 - variable declaration alignment
# ---------------------------------------------------------------------------


def test_cts0008_flags_misaligned_declaration_colons():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    short_name : INT;\n"
        "    much_longer_name: BOOL;\n"
        "END_VAR\nIMPLEMENTATION\nEND_PROGRAM\n"
    )
    findings = list(cts0008(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0008"
    assert findings[0].location.line == 3


def test_cts0008_allows_separate_groups_and_preserves_comments():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    first : INT; // first\n"
        "    second : BOOL; // second\n\n"
        "    isolated : BYTE;\n"
        "END_VAR\nIMPLEMENTATION\nEND_PROGRAM\n"
    )
    findings = list(cts0008(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# CTS0009 - output not assigned
# ---------------------------------------------------------------------------


def test_cts0009_flags_output_that_is_never_assigned():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n"
        "    ready : BOOL;\n"
        "    value : INT;\n"
        "END_VAR\nIMPLEMENTATION\nready := TRUE;\nEND_FUNCTION_BLOCK\n"
    )
    findings = list(cts0009(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0009"
    assert findings[0].severity == "suspicious"
    assert findings[0].anchor == "value"
    assert findings[0].location.line == 4


def test_cts0009_accepts_qualified_and_owned_method_assignments():
    fb = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n"
        "    ready : BOOL;\nEND_VAR\nIMPLEMENTATION\nEND_FUNCTION_BLOCK\n"
    )
    method = _st_unit("METHOD Update\nIMPLEMENTATION\nTHIS.ready := TRUE;\n")
    fb.qualified_name = "FB"
    method.owner_name = "FB"
    findings = list(cts0009(fb, _ctx(ProjectSnapshot(".", [fb, method]))))
    assert findings == []


def test_cts0009_ignores_comments_and_strings():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n"
        "    ready : BOOL;\nEND_VAR\nIMPLEMENTATION\n"
        "// ready := TRUE;\nmessage := 'ready := TRUE;';\n"
    )
    findings = list(cts0009(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# CTS0010 - redundant boolean IF
# ---------------------------------------------------------------------------


def test_cts0010_flags_complex_boolean_assignment():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF (AutoMode AND NOT ErrorActive) OR ForceStart THEN\n"
        "    CanStart := TRUE;\n"
        "ELSE\n"
        "    CanStart := FALSE;\n"
        "END_IF;\n"
    )
    findings = list(cts0010(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0010"
    assert "CanStart := (AutoMode AND NOT ErrorActive) OR ForceStart;" in findings[0].message


def test_cts0010_handles_reversed_values_and_multiline_condition():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF A AND\n    (B OR C) THEN\n"
        "    Result := FALSE;\nELSE\n    Result := TRUE;\nEND_IF;\n"
    )
    findings = list(cts0010(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
    assert "Result := NOT (A AND (B OR C));" in findings[0].message


def test_cts0010_ignores_elsif_nested_and_extra_statements():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF A THEN Result := TRUE; ELSE Result := FALSE; END_IF;\n"
        "IF B THEN Result := TRUE; ELSE Result := FALSE; Other := 1; END_IF;\n"
        "IF C THEN Result := TRUE; ELSIF D THEN Result := FALSE; ELSE Result := TRUE; END_IF;\n"
        "IF E THEN IF F THEN Result := TRUE; ELSE Result := FALSE; END_IF;"
        " ELSE Result := FALSE; END_IF;\n"
    )
    findings = list(cts0010(unit, _ctx(ProjectSnapshot(".", [unit]))))
    assert len(findings) == 1
