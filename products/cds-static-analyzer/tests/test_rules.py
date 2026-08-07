"""
test_analyze_rules.py - Unit tests for the built-in rules on small snippets.
"""

from cds_static_analyzer import project as pm
from cds_static_analyzer.project import ProjectSnapshot

from st_helpers import run_rule


def _st_unit(text):
    return pm._build_st_unit("snippet.st", text)


def _st_unit_named(path, text):
    return pm._build_st_unit(path, text)


# ---------------------------------------------------------------------------
# CTS0054 - implicit narrowing conversion
# ---------------------------------------------------------------------------


def test_cts0054_flags_known_narrowing_assignments():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " source : DINT; target : INT;\n"
        " precise : LREAL; result : REAL;\n"
        " count : INT; byte_value : BYTE;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "target := source;\n"
        "result := precise;\n"
        "byte_value := count;\n"
    )
    findings = run_rule("CTS0054", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == [
        "target := source",
        "result := precise",
        "byte_value := count",
    ]
    assert findings[0].message.startswith("implicit narrowing conversion from DINT to INT")


def test_cts0054_ignores_explicit_widening_and_same_type_assignments():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " small : INT; wide : DINT; precise : LREAL; result : REAL;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "wide := small;\n"
        "result := TO_REAL(precise);\n"
        "small := TO_INT(wide);\n"
        "result := result;\n"
    )
    assert run_rule("CTS0054", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0055 - mixed signed and unsigned comparison
# ---------------------------------------------------------------------------


def test_cts0055_flags_mixed_signed_unsigned_comparisons():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " signedValue : INT; unsignedValue : UINT;\n"
        " signedCount : DINT; unsignedCount : UDINT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "IF signedValue < unsignedValue THEN Accept(); END_IF;\n"
        "IF signedCount = unsignedCount THEN Match(); END_IF;\n"
    )
    findings = run_rule("CTS0055", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == [
        "signedValue < unsignedValue",
        "signedCount = unsignedCount",
    ]


def test_cts0055_ignores_same_signedness_and_explicit_conversions():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " signedValue : INT; otherSigned : DINT; unsignedValue : UINT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "IF signedValue < otherSigned THEN Accept(); END_IF;\n"
        "IF TO_UINT(signedValue) < unsignedValue THEN Accept(); END_IF;\n"
    )
    assert run_rule("CTS0055", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0057 - inadequate FOR counter type
# ---------------------------------------------------------------------------


def test_cts0057_flags_literal_bounds_outside_counter_type():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " byte_counter : BYTE; int_counter : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "FOR byte_counter := 0 TO 300 DO Work(); END_FOR;\n"
        "FOR int_counter := -40000 TO 10 DO Work(); END_FOR;\n"
    )
    findings = run_rule("CTS0057", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == [
        "FOR byte_counter := 0 TO 300 DO",
        "FOR int_counter := -40000 TO 10 DO",
    ]
    assert "upper bound 300 > 255" in findings[0].message
    assert "lower bound -40000 < -32768" in findings[1].message


def test_cts0057_handles_reverse_ranges_and_ignores_valid_or_dynamic_loops():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " byte_counter : BYTE; word_counter : WORD;\n"
        " first : INT; last : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "FOR byte_counter := 255 TO -1 BY -1 DO Work(); END_FOR;\n"
        "FOR word_counter := 300 TO 0 BY -1 DO Work(); END_FOR;\n"
        "FOR byte_counter := first TO last DO Work(); END_FOR;\n"
        "FOR byte_counter := 0 TO 255 DO Work(); END_FOR;\n"
    )
    findings = run_rule("CTS0057", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert "lower bound -1 < 0" in findings[0].message


# ---------------------------------------------------------------------------
# CTS0058 - TIME literal outside range
# ---------------------------------------------------------------------------


def test_cts0058_flags_overflowing_and_negative_time_literals():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " too_long : TIME := T#50d;\n"
        " negative : TIME;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "negative := T#-1ms;\n"
        "Wait(TIME#49d17h2m47s296ms);\n"
    )
    findings = run_rule("CTS0058", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == [
        "T#50d",
        "T#-1ms",
        "TIME#49d17h2m47s296ms",
    ]
    assert "outside the 32-bit TIME range" in findings[0].message


def test_cts0058_accepts_valid_composed_literals_and_ignores_ltime():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n"
        " short : TIME := T#1h30m;\n"
        " wide : LTIME := LTIME#500d;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "Wait(T#49d17h2m47s295ms);\n"
    )
    assert run_rule("CTS0058", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0053 - unresolved call
# ---------------------------------------------------------------------------


def test_cts0053_flags_unknown_bare_and_method_calls():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n device : Device;\nEND_VAR\nIMPLEMENTATION\n"
        "MissingPou();\nDevice.Start();\n"
    )
    findings = run_rule("CTS0053", ProjectSnapshot(".", [unit]))
    assert {finding.anchor for finding in findings} == {"MissingPou", "Device.Start"}
    assert all(finding.severity == "suspicious" for finding in findings)


def test_cts0053_ignores_project_and_known_library_calls():
    helper = _st_unit_named(
        "Helper.st", "FUNCTION Helper : INT\nIMPLEMENTATION\nHelper := 1;\n"
    )
    unit = _st_unit(
        "PROGRAM Main\nVAR\n timer : TON;\nEND_VAR\nIMPLEMENTATION\n"
        "value := Helper();\nvalue := ABS(value);\n"
        "value := TO_INT(value);\n"
        "timer(IN := Enable, PT := T#1s);\n"
    )
    assert run_rule("CTS0053", ProjectSnapshot(".", [helper, unit])) == []


def test_cts0053_ignores_self_method_calls_and_reports_unknown_function_block():
    unit = _st_unit(
        "METHOD Run\nIMPLEMENTATION\nTHIS.Helper();\nUnknownBlock();\n"
    )
    findings = run_rule("CTS0053", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["UnknownBlock"]


# ---------------------------------------------------------------------------
# CTS0052 - function-block output read before call
# ---------------------------------------------------------------------------


def test_cts0052_flags_timer_output_read_before_call():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n timer : TON;\nEND_VAR\nIMPLEMENTATION\n"
        "IF timer.Q THEN Done := TRUE; END_IF;\n"
        "timer(IN := Enable, PT := T#1s);\n"
    )
    findings = run_rule("CTS0052", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "timer.Q"


def test_cts0052_accepts_timer_and_edge_trigger_called_before_read():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n timer : TON;\n trig : R_TRIG;\nEND_VAR\n"
        "IMPLEMENTATION\n"
        "timer(IN := Enable, PT := T#1s);\n"
        "trig(CLK := Signal);\n"
        "IF timer.Q AND trig.Q THEN Done := TRUE; END_IF;\n"
    )
    assert run_rule("CTS0052", ProjectSnapshot(".", [unit])) == []


def test_cts0052_flags_uncalled_edge_output_and_supports_project_fb_outputs():
    fb = _st_unit_named(
        "FB.st",
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n Done : BOOL;\nEND_VAR\nIMPLEMENTATION\n",
    )
    unit = _st_unit(
        "PROGRAM Main\nVAR\n fb : FB;\n trig : F_TRIG;\nEND_VAR\nIMPLEMENTATION\n"
        "IF fb.Done OR trig.Q THEN Done := TRUE; END_IF;\n"
    )
    fb.qualified_name = "FB"
    findings = run_rule("CTS0052", ProjectSnapshot(".", [fb, unit]))
    assert {finding.anchor for finding in findings} == {"fb.Done", "trig.Q"}


def test_cts0052_ignores_non_output_fields_and_assignments():
    unit = _st_unit(
        "PROGRAM Main\nVAR\n timer : TON;\nEND_VAR\nIMPLEMENTATION\n"
        "timer.Q := FALSE;\n"
        "timer(IN := Enable, PT := timer.ET);\n"
    )
    assert run_rule("CTS0052", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0051 - escaping local address
# ---------------------------------------------------------------------------


def test_cts0051_flags_function_result_and_call_escape():
    unit = _st_unit(
        "FUNCTION Make : POINTER TO BYTE\nVAR_TEMP\n"
        " localByte : BYTE;\nEND_VAR\nIMPLEMENTATION\n"
        "Make := ADR(localByte);\n"
    )
    findings = run_rule("CTS0051", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "ADR(localByte)"


def test_cts0051_flags_address_passed_to_call():
    unit = _st_unit(
        "FUNCTION Store : BOOL\nVAR_TEMP\n"
        " localByte : BYTE;\nEND_VAR\nIMPLEMENTATION\n"
        "Store := StoreForLater(ADR(localByte));\n"
    )
    findings = run_rule("CTS0051", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert "passed out" in findings[0].message


def test_cts0051_flags_retain_and_external_destinations():
    unit = _st_unit(
        "FUNCTION Save : BOOL\nVAR RETAIN\n"
        " retainedPointer : POINTER TO BYTE;\nEND_VAR\n"
        "VAR_EXTERNAL\n externalPointer : POINTER TO BYTE;\nEND_VAR\n"
        "VAR_TEMP\n localByte : BYTE;\nEND_VAR\n"
        "IMPLEMENTATION\nretainedPointer := ADR(localByte);\n"
        "externalPointer := ADR(localByte);\n"
    )
    findings = run_rule("CTS0051", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert all("escapes" in finding.message for finding in findings)


def test_cts0051_ignores_local_address_use_and_nonlocal_values():
    unit = _st_unit(
        "FUNCTION Use : BOOL\nVAR\n"
        " localByte : BYTE;\n localPointer : POINTER TO BYTE;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "localPointer := ADR(localByte);\n"
        "Use := ReadNow(localPointer);\n"
        "ADR(globalByte);\n"
    )
    assert run_rule("CTS0051", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0050 - possible zero divisor
# ---------------------------------------------------------------------------


def test_cts0050_flags_variable_division_without_a_guard():
    unit = _st_unit(
        "FUNCTION Calc : REAL\nVAR_INPUT\n"
        "    divisor : REAL;\nEND_VAR\nIMPLEMENTATION\n"
        "Calc := value / divisor;\n"
    )
    findings = run_rule("CTS0050", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0050"
    assert findings[0].severity == "danger"
    assert findings[0].anchor == "divisor"


def test_cts0050_accepts_simple_nonzero_if_and_else_guards():
    unit = _st_unit(
        "FUNCTION Calc : REAL\nIMPLEMENTATION\n"
        "IF divisor <> 0 THEN\n"
        "    Calc := value / divisor;\n"
        "END_IF;\n"
        "IF divisor = 0 THEN\n"
        "    Calc := 0;\n"
        "ELSE\n"
        "    Calc := value / divisor;\n"
        "END_IF;\n"
    )
    assert run_rule("CTS0050", ProjectSnapshot(".", [unit])) == []


def test_cts0050_flags_branch_where_divisor_is_zero():
    unit = _st_unit(
        "FUNCTION Calc : REAL\nIMPLEMENTATION\n"
        "IF divisor = 0 THEN\n"
        "    Calc := value / divisor;\n"
        "END_IF;\n"
    )
    findings = run_rule("CTS0050", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert "proven to be zero" in findings[0].message


def test_cts0050_accepts_guard_clause_and_skips_literal_divisors():
    unit = _st_unit(
        "FUNCTION Calc : REAL\nIMPLEMENTATION\n"
        "IF divisor = 0 THEN RETURN; END_IF;\n"
        "Calc := value / divisor;\n"
        "Calc := 10 / 10;\n"
        "Calc := 10 / DINT#0;\n"
    )
    assert run_rule("CTS0050", ProjectSnapshot(".", [unit])) == []


def test_cts0050_does_not_assume_complex_guard_is_sufficient():
    unit = _st_unit(
        "FUNCTION Calc : REAL\nIMPLEMENTATION\n"
        "IF divisor <> 0 AND enabled THEN\n"
        "    Calc := value / divisor;\n"
        "END_IF;\n"
    )
    findings = run_rule("CTS0050", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# CTS0049 - constant arithmetic overflow
# ---------------------------------------------------------------------------


def test_cts0049_flags_overflow_in_constant_initializer():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    nValue : INT := 30000 + 10000;\n"
        "END_VAR\nIMPLEMENTATION\nEND_PROGRAM\n"
    )
    findings = run_rule("CTS0049", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0049"
    assert findings[0].severity == "danger"
    assert findings[0].anchor == "nValue"
    assert "40000" in findings[0].message
    assert "INT" in findings[0].message


def test_cts0049_flags_overflow_in_direct_assignment():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    nValue : BYTE;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "nValue := 200 + 100;\n"
    )
    findings = run_rule("CTS0049", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "nValue"


def test_cts0049_accepts_in_range_values_and_skips_nonconstant_expressions():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    intValue : INT := 30000 + 1000;\n"
        "    wideValue : DINT;\n"
        "    inputValue : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "wideValue := 30000 + 10000;\n"
        "intValue := inputValue + 1;\n"
    )
    assert run_rule("CTS0049", ProjectSnapshot(".", [unit])) == []


def test_cts0049_ignores_comments_strings_and_non_integer_targets():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    realValue : REAL;\n"
        "    intValue : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "realValue := 30000 + 10000;\n"
        "message := 'intValue := 30000 + 10000';\n"
        "// intValue := 30000 + 10000;\n"
    )
    assert run_rule("CTS0049", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0048 - constant control-flow expression
# ---------------------------------------------------------------------------


def test_cts0048_flags_constant_numeric_and_boolean_expressions():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF 10 < 20 THEN Work(); END_IF;\n"
        "IF (2 + 3) = 5 AND TRUE THEN Log(); END_IF;\n"
    )
    findings = run_rule("CTS0048", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert "always true" in findings[0].message
    assert "always true" in findings[1].message


def test_cts0048_supports_constant_false_and_while_conditions():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "WHILE 4 * 2 <> 8 DO Work(); END_WHILE;\n"
    )
    findings = run_rule("CTS0048", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert "always false" in findings[0].message


def test_cts0048_leaves_literal_conditions_and_nonconstant_expressions_to_other_rules():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF TRUE THEN Work(); END_IF;\n"
        "IF value = value THEN Work(); END_IF;\n"
        "IF limit < 20 THEN Work(); END_IF;\n"
        "message := 'IF 10 < 20 THEN';\n"
    )
    assert run_rule("CTS0048", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0047 - self-comparison
# ---------------------------------------------------------------------------


def test_cts0047_flags_tautological_and_contradictory_comparisons():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF value = value THEN Work(); END_IF;\n"
        "IF status <> status THEN Reject(); END_IF;\n"
    )
    findings = run_rule("CTS0047", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert "always true" in findings[0].message
    assert "always false" in findings[1].message


def test_cts0047_handles_qualified_names_and_relational_operators():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF GVL.State >= GVL.State THEN Work(); END_IF;\n"
        "IF count < count THEN Stop(); END_IF;\n"
    )
    findings = run_rule("CTS0047", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert findings[0].anchor == "GVL.State >= GVL.State"
    assert findings[1].anchor == "count < count"


def test_cts0047_ignores_different_or_complex_operands():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF value = other THEN Work(); END_IF;\n"
        "IF ReadValue() = ReadValue() THEN Work(); END_IF;\n"
        "IF data[index] = data[index] THEN Work(); END_IF;\n"
        "message := 'value = value';\n"
    )
    assert run_rule("CTS0047", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0046 - REPEAT condition not changed
# ---------------------------------------------------------------------------


def test_cts0046_flags_condition_not_changed_in_repeat_body():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "REPEAT\n"
        "    Work();\n"
        "UNTIL ready\n"
        "END_REPEAT;\n"
    )
    findings = run_rule("CTS0046", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0046"
    assert findings[0].severity == "danger"
    assert findings[0].anchor == "ready"


def test_cts0046_accepts_direct_assignment_to_condition_variable():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "REPEAT\n"
        "    ready := CheckReady();\n"
        "UNTIL ready\n"
        "END_REPEAT;\n"
    )
    assert run_rule("CTS0046", ProjectSnapshot(".", [unit])) == []


def test_cts0046_uses_outer_until_for_nested_repeat():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "REPEAT\n"
        "    REPEAT\n"
        "        inner_done := TRUE;\n"
        "    UNTIL inner_done\n"
        "    END_REPEAT;\n"
        "UNTIL outer_done\n"
        "END_REPEAT;\n"
    )
    findings = run_rule("CTS0046", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "outer_done"


def test_cts0046_skips_complex_or_alternate_termination_paths():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "REPEAT\n"
        "    IF StopNow THEN EXIT; END_IF;\n"
        "UNTIL IsReady()\n"
        "END_REPEAT;\n"
    )
    assert run_rule("CTS0046", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0045 - unreachable POU
# ---------------------------------------------------------------------------


def test_cts0045_flags_pou_reachable_only_from_unreachable_pou():
    main = _st_unit_named(
        "Main.st", "PROGRAM Main\nIMPLEMENTATION\nEND_PROGRAM\n"
    )
    orphan = _st_unit_named(
        "Orphan.st", "FUNCTION Orphan\nIMPLEMENTATION\nLeaf();\nEND_FUNCTION\n"
    )
    leaf = _st_unit_named(
        "Leaf.st", "FUNCTION Leaf\nIMPLEMENTATION\nEND_FUNCTION\n"
    )
    snapshot = ProjectSnapshot(".", [main, orphan, leaf, _task_unit("Fast", "Main")])
    findings = run_rule("CTS0045", snapshot)
    assert {finding.anchor for finding in findings} == {"Orphan", "Leaf"}
    leaf_finding = next(finding for finding in findings if finding.anchor == "Leaf")
    assert "orphan" in leaf_finding.message.casefold()


def test_cts0045_accepts_pou_reachable_from_a_task():
    main = _st_unit_named(
        "Main.st", "PROGRAM Main\nIMPLEMENTATION\nHelper();\nEND_PROGRAM\n"
    )
    helper = _st_unit_named(
        "Helper.st", "FUNCTION Helper\nIMPLEMENTATION\nEND_FUNCTION\n"
    )
    snapshot = ProjectSnapshot(".", [main, helper, _task_unit("Fast", "Main")])
    assert run_rule("CTS0045", snapshot) == []


def test_cts0045_skips_when_task_roots_are_unavailable():
    unit = _st_unit_named(
        "Unused.st", "FUNCTION Unused\nIMPLEMENTATION\nEND_FUNCTION\n"
    )
    assert run_rule("CTS0045", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0044 - overlapping CASE ranges
# ---------------------------------------------------------------------------


def test_cts0044_flags_overlapping_numeric_ranges():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "CASE state OF\n"
        "  1..5: state := 1;\n"
        "  5..10: state := 2;\n"
        "END_CASE;\n"
    )
    findings = run_rule("CTS0044", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0044"
    assert findings[0].severity == "danger"
    assert findings[0].location.line == 6
    assert findings[0].anchor == "5..10"


def test_cts0044_treats_single_label_as_a_one_value_range():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "CASE state OF\n"
        "  1..5: state := 1;\n"
        "  4, 8..10: state := 2;\n"
        "END_CASE;\n"
    )
    findings = run_rule("CTS0044", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "4"


def test_cts0044_ignores_exact_duplicates_and_symbolic_labels():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "CASE state OF\n"
        "  1..5: state := 1;\n"
        "  1..5: state := 2;\n"
        "  StateIdle..StateRun: state := 3;\n"
        "END_CASE;\n"
    )
    assert run_rule("CTS0044", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0001 - commented-out code
# ---------------------------------------------------------------------------


def test_cts0001_flags_assignment_in_comment():
    unit = _st_unit(
        "PROGRAM P\nVAR\n x : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n// x := 1;\nx := 2;\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0001"
    assert findings[0].location.line == 8


def test_cts0001_flags_call_in_comment():
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n(* MyFunc(a, b); *)\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1


def test_cts0001_ignores_prose_comments():
    unit = _st_unit(
        "PROGRAM P\nVAR\n x : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// disabled for TICKET-482\n(* this input is never read *)\n"
        "x := 1;\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
    assert findings == []


def test_cts0001_ignores_parenthetical_documentation():
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "// Sensor service (debounce, edge, logging)\n"
        "// Cycle period (100ms)\n"
    )
    assert run_rule("CTS0001", ProjectSnapshot(".", [unit])) == []


def test_cts0001_ignores_documentation_examples():
    unit = _st_unit(
        "PROGRAM P\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "(* Example: Component:=Component.user_action *)\n"
    )
    assert run_rule("CTS0001", ProjectSnapshot(".", [unit])) == []


def test_cts0001_does_not_see_comment_markers_in_strings():
    unit = _st_unit(
        "PROGRAM P\nVAR\n s : STRING;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "s := '// not a comment';\n"
    )
    findings = run_rule("CTS0001", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0002", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0002", snap)
    assert findings == []  # speed is read by the owned method


def test_cts0002_qualified_access_counts_as_read():
    unit = _st_unit(
        "METHOD M\nVAR_INPUT\n a : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "THIS.a := THIS.a + 1;\n"
    )
    findings = run_rule("CTS0002", ProjectSnapshot(".", [unit]))
    assert findings == []


def test_cts0002_super_access_counts_as_read():
    unit = _st_unit(
        "METHOD M\nVAR_INPUT\n a : INT;\nEND_VAR\n\nIMPLEMENTATION\n\nSUPER^.a := 0;\n"
    )
    findings = run_rule("CTS0002", ProjectSnapshot(".", [unit]))
    assert findings == []


def test_cts0002_no_findings_without_inputs():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR\n x : INT;\nEND_VAR\n\nIMPLEMENTATION\n\nF := x;\n"
    )
    findings = run_rule("CTS0002", ProjectSnapshot(".", [unit]))
    assert findings == []


def test_cts0002_location_points_at_member_line():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_INPUT\n a : INT;\n b : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n out : BOOL;\nEND_VAR\n\nIMPLEMENTATION\n\nout := a > 0;\n"
    )
    findings = run_rule("CTS0002", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0003", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0003"
    assert findings[0].severity == "suspicious"
    assert findings[0].location.line == 8


def test_cts0003_accepts_case_with_else():
    unit = _st_unit(
        "PROGRAM P\nVAR\n state : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "CASE state OF\n  1: state := 2;\nELSE\n  state := 0;\nEND_CASE;\n"
    )
    assert run_rule("CTS0003", ProjectSnapshot(".", [unit])) == []


def test_cts0003_does_not_count_nested_if_else_for_case():
    unit = _st_unit(
        "PROGRAM P\nVAR\n state : INT;\nEND_VAR\n\nIMPLEMENTATION\n\n"
        "CASE state OF\n  1: IF state > 0 THEN state := 2; ELSE state := 0; END_IF;\n"
        "END_CASE;\n"
    )
    findings = run_rule("CTS0003", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# CTS0004 - magic numeric literal
# ---------------------------------------------------------------------------


def test_cts0004_flags_repeated_nontrivial_numbers():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "IF value > 75 THEN result := 75; END_IF;\n"
    )
    findings = run_rule("CTS0004", ProjectSnapshot(".", [unit]))
    # Both 75 literals share one anchor and context, so they are already one
    # identity for the state layer; the merge pass reports them as one finding.
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0004"
    assert findings[0].severity == "style"
    assert findings[0].location.line == 4
    assert findings[0].member_count == 2
    assert findings[0].member_lines == [4, 4]


def test_cts0004_ignores_trivial_numbers_comments_and_strings():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "value := 0; other := 1; third := -1; small := 2;\n"
        "(* 75 75 *) value := '75 75';\n"
    )
    assert run_rule("CTS0004", ProjectSnapshot(".", [unit])) == []


def test_cts0004_ignores_array_indexes_and_bit_selectors():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "data[25] := 1; data[25] := 2; flags[25].3 := TRUE; flags[25].3 := FALSE;\n"
    )
    assert run_rule("CTS0004", ProjectSnapshot(".", [unit])) == []


def test_cts0004_does_not_flag_single_occurrence():
    unit = _st_unit("PROGRAM P\nIMPLEMENTATION\n\nvalue := 75;\n")
    assert run_rule("CTS0004", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0006 - array index outside bounds
# ---------------------------------------------------------------------------


def test_cts0006_flags_constant_indexes_outside_declared_bounds():
    unit = _st_unit(
        "PROGRAM P\nVAR\n values : ARRAY[1..10] OF INT;\nEND_VAR\n\n"
        "IMPLEMENTATION\n\nvalues[0] := 1; values[11] := 2;\n"
    )
    findings = run_rule("CTS0006", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert all(f.rule_id == "CTS0006" for f in findings)
    assert all(f.severity == "danger" for f in findings)
    assert [f.location.line for f in findings] == [8, 8]


def test_cts0006_accepts_nonzero_lower_bound_and_valid_indexes():
    unit = _st_unit(
        "PROGRAM P\nVAR\n values : ARRAY[-2..5] OF INT;\nEND_VAR\n\n"
        "IMPLEMENTATION\n\nvalues[-2] := 1; values[5] := 2;\n"
    )
    assert run_rule("CTS0006", ProjectSnapshot(".", [unit])) == []


def test_cts0006_does_not_judge_variable_or_multidimensional_indexes():
    unit = _st_unit(
        "PROGRAM P\nVAR\n values : ARRAY[1..10] OF INT;\n grid : ARRAY[1..2, 1..2] OF INT;\n i : INT;\nEND_VAR\n\n"
        "IMPLEMENTATION\n\nvalues[i] := 1; grid[3, 3] := 2;\n"
    )
    assert run_rule("CTS0006", ProjectSnapshot(".", [unit])) == []


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
    findings = run_rule("CTS0007", ProjectSnapshot(".", [unit]))
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
        "END_IF;\n\n"
        "Logger(\n"
        "    inputValue\n"
        "    , path := 'logs/'\n"
        "    , enabled := TRUE\n"
        "    );\n"
    )
    assert run_rule("CTS0007", ProjectSnapshot(".", [unit])) == []


def test_cts0007_fix_reindents_only_reported_lines():
    text = (
        "PROGRAM P\nIMPLEMENTATION\n\n"
        "IF ready THEN\n"
        "\tFOR i := 1 TO 10 DO\n"
        "\t\tvalue := i;\n"
        "\t\t\ttotal := total + value;\n"
        "\tEND_FOR\n"
        "END_IF;\n"
    )
    unit = _st_unit(text)
    findings = run_rule("CTS0007", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1

    from cds_static_analyzer.rules.CTS0007_indentation import fix

    fixed = fix(text, findings[0].to_dict())
    assert "\t\ttotal := total + value;\n" in fixed
    assert "\t\t\ttotal := total + value;\n" not in fixed
    assert fixed.count("\t\tvalue := i;\n") == 1


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
    findings = run_rule("CTS0008", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0008", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1


def test_cts0008_fix_aligns_only_the_affected_group():
    from cds_static_analyzer.rules.CTS0008_variable_alignment import fix

    text = (
        "PROGRAM P\nVAR\n"
        "    short_name : INT;\n"
        "    much_longer_name: BOOL;\n\n"
        "    isolated : BYTE;\n"
        "END_VAR\nIMPLEMENTATION\nEND_PROGRAM\n"
    )
    fixed = fix(text, {"location": {"line": 4}})
    fixed_lines = fixed.splitlines()
    assert fixed_lines[2].index(":") == fixed_lines[3].index(":")
    assert "    isolated : BYTE;\n" in fixed


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
    findings = run_rule("CTS0009", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0009", ProjectSnapshot(".", [fb, method]))
    assert findings == []


def test_cts0009_ignores_comments_and_strings():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n"
        "    ready : BOOL;\nEND_VAR\nIMPLEMENTATION\n"
        "// ready := TRUE;\nmessage := 'ready := TRUE;';\n"
    )
    findings = run_rule("CTS0009", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0010", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0010"
    assert "CanStart := (AutoMode AND NOT ErrorActive) OR ForceStart;" in findings[0].message


def test_cts0010_handles_reversed_values_and_multiline_condition():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF A AND\n    (B OR C) THEN\n"
        "    Result := FALSE;\nELSE\n    Result := TRUE;\nEND_IF;\n"
    )
    findings = run_rule("CTS0010", ProjectSnapshot(".", [unit]))
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
    findings = run_rule("CTS0010", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# CTS0011 - assigned local not read
# ---------------------------------------------------------------------------


def test_cts0011_flags_assigned_local_that_is_never_read():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    calculated : INT;\n"
        "END_VAR\nVAR_OUTPUT\n"
        "    used_value : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "calculated := input + 1;\n"
        "used_value := input;\n"
    )
    findings = run_rule("CTS0011", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0011"
    assert findings[0].anchor == "calculated"


def test_cts0011_accepts_reads_and_ignores_interfaces_comments_strings_and_fields():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR\n"
        "    temp : INT;\n"
        "END_VAR\nVAR_OUTPUT\n"
        "    output : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "temp := input;\noutput := temp;\n"
        "// temp := 99;\nmessage := 'temp := 100;';\nobj.temp := 1;\n"
    )
    assert run_rule("CTS0011", ProjectSnapshot(".", [unit])) == []


def test_cts0011_checks_only_local_variable_scopes():
    unit = _st_unit(
        "PROGRAM P\nVAR_INPUT\n    incoming : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n    outgoing : INT;\nEND_VAR\n"
        "VAR_TEMP\n    scratch : INT;\nEND_VAR\nIMPLEMENTATION\n"
        "incoming := 1;\noutgoing := incoming;\nscratch := 2;\n"
    )
    findings = run_rule("CTS0011", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["scratch"]


# ---------------------------------------------------------------------------
# CTS0012 - overwrite without read
# ---------------------------------------------------------------------------


def test_cts0012_flags_sequential_overwrite():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "value := CalculateA();\nvalue := CalculateB();\n"
    )
    findings = run_rule("CTS0012", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].rule_id == "CTS0012"
    assert findings[0].anchor == "value"


def test_cts0012_ignores_reads_and_control_flow_boundaries():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "value := CalculateA();\nUse(value);\nvalue := CalculateB();\n"
        "IF condition THEN\n    value := CalculateC();\nEND_IF;\n"
        "value := CalculateD();\n"
    )
    assert run_rule("CTS0012", ProjectSnapshot(".", [unit])) == []


def test_cts0012_accepts_accumulation_in_the_next_expression():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "text := StartText();\ntext := CONCAT(text, suffix);\n"
    )
    assert run_rule("CTS0012", ProjectSnapshot(".", [unit])) == []


def test_cts0012_accepts_arithmetic_self_updates():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "counter := counter + 1;\n"
        "counter := counter - step;\n"
    )
    assert run_rule("CTS0012", ProjectSnapshot(".", [unit])) == []


def test_cts0012_does_not_treat_arbitrary_self_read_as_accumulation():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "value := CalculateA();\nvalue := Normalize(value);\n"
    )
    findings = run_rule("CTS0012", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1


def test_cts0012_ignores_self_updates_inside_control_flow():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF condition THEN\n"
        "    counter := counter + 1;\n"
        "ELSE\n"
        "    counter := counter - 1;\n"
        "END_IF;\n"
        "FOR index := 1 TO 3 DO\n"
        "    total := total + value;\n"
        "END_FOR;\n"
    )
    assert run_rule("CTS0012", ProjectSnapshot(".", [unit])) == []


def test_cts0012_ignores_comments_strings_and_qualified_fields():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "obj.value := CalculateA();\n"
        "// value := CalculateB();\nmessage := 'value := CalculateC();';\n"
        "value := CalculateD();\n"
    )
    assert run_rule("CTS0012", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0013 - declared symbol not referenced
# ---------------------------------------------------------------------------


def test_cts0013_flags_unreferenced_local_and_ignores_placeholders():
    unit = _st_unit(
        "PROGRAM P\nVAR\n"
        "    forgotten : INT;\n"
        "    spare_1 : INT;\n"
        "    used_value : INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "used_value := 1;\n"
    )
    findings = run_rule("CTS0013", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["forgotten"]


def test_cts0013_finds_global_used_by_another_unit():
    gvl = _st_unit_named(
        "GVL.st",
        "VAR_GLOBAL\n    global_value : INT;\n    forgotten_global : INT;\nEND_VAR\n",
    )
    program = _st_unit_named(
        "P.st",
        "PROGRAM P\nIMPLEMENTATION\n"
        "global_value := 1;\n",
    )
    findings = run_rule("CTS0013", ProjectSnapshot(".", [gvl, program]))
    assert [finding.anchor for finding in findings] == ["forgotten_global"]


def test_cts0013_counts_references_from_owned_methods():
    owner = _st_unit_named(
        "FB.st",
        "FUNCTION_BLOCK FB\nVAR\n    field_value : INT;\nEND_VAR\n"
        "IMPLEMENTATION\n",
    )
    method = _st_unit_named(
        "FB.Update.st",
        "METHOD Update\nIMPLEMENTATION\nfield_value := 1;\n",
    )
    findings = run_rule("CTS0013", ProjectSnapshot(".", [owner, method]))
    assert findings == []


def test_cts0013_does_not_count_comments_or_strings_as_references():
    unit = _st_unit(
        "PROGRAM P\nVAR\n    forgotten : INT;\nEND_VAR\nIMPLEMENTATION\n"
        "// forgotten\nmessage := 'forgotten';\n"
    )
    findings = run_rule("CTS0013", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["forgotten"]


# ---------------------------------------------------------------------------
# CTS0016-CTS0019 - control-flow and initialization checks
# ---------------------------------------------------------------------------


def test_cts0016_flags_code_after_return_but_not_block_boundary():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF Ready THEN\n"
        "    RETURN;\n"
        "    DoWork();\n"
        "END_IF;\n"
    )
    findings = run_rule("CTS0016", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["DoWork"]


def test_cts0017_flags_literal_stub_conditions_and_ignores_prose():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "IF FALSE THEN\n"
        "    DoWork();\n"
        "END_IF;\n"
        "// IF TRUE THEN is only documentation\n"
    )
    findings = run_rule("CTS0017", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["FALSE"]


def test_cts0018_flags_read_before_assignment_and_accepts_initial_value():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR\n"
        "    temp : INT;\n"
        "    ready : BOOL := TRUE;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "F := temp + 1;\n"
        "ready := FALSE;\n"
    )
    findings = run_rule("CTS0018", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["temp"]


def test_cts0018_accepts_assignment_before_read():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR\n    temp : INT;\nEND_VAR\nIMPLEMENTATION\n"
        "temp := 0;\n"
        "F := temp + 1;\n"
    )
    assert run_rule("CTS0018", ProjectSnapshot(".", [unit])) == []


def test_cts0018_accepts_output_arguments_and_field_writes():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR\n"
        "    result : INT;\n"
        "    packet : Packet;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "MakePacket(value => result);\n"
        "packet.value := result;\n"
        "F := packet.value;\n"
    )
    assert run_rule("CTS0018", ProjectSnapshot(".", [unit])) == []


def test_cts0018_accepts_address_outputs_and_bit_writes():
    unit = _st_unit(
        "FUNCTION F : BOOL\nVAR\n"
        "    reply : DINT;\n"
        "    buffer : ARRAY[0..3] OF BYTE;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "SysCall(pReply := ADR(reply));\n"
        "buffer[0].0 := TRUE;\n"
        "F := reply <> 0;\n"
    )
    assert run_rule("CTS0018", ProjectSnapshot(".", [unit])) == []


def test_cts0019_requires_output_assignment_on_each_if_branch():
    partial = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Ready THEN\n    Done := TRUE;\nEND_IF;\n"
    )
    complete = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Ready THEN\n    Done := TRUE;\n"
        "ELSE\n    Done := FALSE;\nEND_IF;\n"
    )
    assert len(run_rule("CTS0019", ProjectSnapshot(".", [partial]))) == 1
    assert run_rule("CTS0019", ProjectSnapshot(".", [complete])) == []


def test_cts0019_ignores_stateful_function_block_outputs():
    unit = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Ready THEN\n    Done := TRUE;\nEND_IF;\n"
    )
    assert run_rule("CTS0019", ProjectSnapshot(".", [unit])) == []


def test_cts0019_accepts_default_before_case():
    unit = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nDone := FALSE;\nCASE State OF\n"
        "    1: Done := TRUE;\n"
        "END_CASE;\n"
    )
    assert run_rule("CTS0019", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0020 - write to VAR_INPUT
# ---------------------------------------------------------------------------


def test_cts0020_flags_writes_to_input_and_its_fields():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR_INPUT\n"
        "    Value : INT;\n    Packet : Packet;\nEND_VAR\n"
        "IMPLEMENTATION\nValue := 0;\nPacket.Value := Value;\nF := Value;\n"
    )
    findings = run_rule("CTS0020", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["Value", "Packet"]


def test_cts0020_ignores_locals_in_out_and_output_arguments():
    unit = _st_unit(
        "FUNCTION F : INT\nVAR_INPUT\n    Value : INT;\nEND_VAR\n"
        "VAR_IN_OUT\n    Shared : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n    Result : INT;\nEND_VAR\n"
        "VAR\n    Local : INT;\nEND_VAR\nIMPLEMENTATION\n"
        "Shared := Value;\nLocal := Value;\nResult := Value;\n"
        "Use(Value => Result);\nF := Result;\n"
    )
    assert run_rule("CTS0020", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0021 - self-assignment
# ---------------------------------------------------------------------------


def test_cts0021_flags_simple_self_assignment_case_insensitively():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "Value := Value;\nvalue := VALUE;\nother := Value;\n"
    )
    findings = run_rule("CTS0021", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["Value", "value"]


def test_cts0021_ignores_fields_expressions_and_comments():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "Packet.Value := Packet.Value;\n"
        "Value := Value + 0;\n"
        "// Value := Value;\n"
    )
    assert run_rule("CTS0021", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0022 - output read before assignment
# ---------------------------------------------------------------------------


def test_cts0022_flags_output_read_before_write():
    unit = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Done THEN\n    F := TRUE;\nEND_IF;\nDone := TRUE;\n"
    )
    findings = run_rule("CTS0022", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["Done"]


def test_cts0022_accepts_default_and_ignores_fb_and_output_arguments():
    function = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nDone := FALSE;\nIF Done THEN F := TRUE; END_IF;\n"
    )
    fb = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Done THEN Done := FALSE; END_IF;\n"
    )
    argument = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nUse(Done => Done);\nF := TRUE;\n"
    )
    snapshot = ProjectSnapshot(".", [function, fb, argument])
    assert run_rule("CTS0022", snapshot) == []


# ---------------------------------------------------------------------------
# CTS0023 - empty statement
# ---------------------------------------------------------------------------


def test_cts0023_flags_standalone_and_duplicate_semicolons():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        ";\nDoWork();;\nIF Ready THEN\n;\nEND_IF;\n"
    )
    findings = run_rule("CTS0023", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert any(finding.member_lines == [3, 6] for finding in findings)
    assert all(finding.anchor == ";" for finding in findings)


def test_cts0023_ignores_normal_statement_terminators_and_comments():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "DoWork();\nIF Ready THEN\n    DoWork();\nEND_IF;\n"
        "// ;\n"
    )
    assert run_rule("CTS0023", ProjectSnapshot(".", [unit])) == []


def test_cts0023_ignores_terminator_on_line_after_multiline_call():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "Logger(\n"
        "    inputValue\n"
        "    , path := 'logs/'\n"
        ")\n"
        ";\n"
    )
    assert run_rule("CTS0023", ProjectSnapshot(".", [unit])) == []


def test_cts0023_ignores_explicitly_documented_empty_statement():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "; // Intentionally empty branch for compatibility\n"
        "; (* Reserved for the vendor hook. *)\n"
    )
    assert run_rule("CTS0023", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0024 - multiple output writes
# ---------------------------------------------------------------------------


def test_cts0024_flags_sequential_output_writes():
    unit = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nDone := FALSE;\nDone := TRUE;\n"
    )
    findings = run_rule("CTS0024", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["Done"]


def test_cts0024_ignores_mutually_exclusive_arms_and_function_blocks():
    function = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Ready THEN\n    Done := TRUE;\n"
        "ELSE\n    Done := FALSE;\nEND_IF;\n"
    )
    fb = _st_unit(
        "FUNCTION_BLOCK FB\nVAR_OUTPUT\n    Done : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nDone := FALSE;\nDone := TRUE;\n"
    )
    assert run_rule("CTS0024", ProjectSnapshot(".", [function, fb])) == []


def test_cts0024_ignores_output_fields_and_elements():
    unit = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n"
        "    Packet : Packet;\n    Items : ARRAY[0..2] OF INT;\n"
        "END_VAR\nIMPLEMENTATION\n"
        "Packet.Value := 1;\nPacket.Value := 2;\n"
        "Items[0] := 1;\nItems[1] := 2;\nF := TRUE;\n"
    )
    assert run_rule("CTS0024", ProjectSnapshot(".", [unit])) == []


def test_cts0024_ignores_accumulator_writes_that_read_the_output():
    unit = _st_unit(
        "FUNCTION F : BOOL\nVAR_OUTPUT\n    Text : STRING;\nEND_VAR\n"
        "IMPLEMENTATION\nText := 'a';\n"
        "Text := CONCAT(Text, 'b');\nText := CONCAT(Text, 'c');\n"
        "F := TRUE;\n"
    )
    assert run_rule("CTS0024", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0025 - concurrent writes to shared data
# ---------------------------------------------------------------------------


def _task_unit(name, pou):
    xml = (
        '<Single><List Name="PouList"><Single>'
        f'<Single Name="Name">{pou}</Single>'
        "</Single></List></Single>"
    )
    return pm.Unit(
        f"{name}.xml#{name}", "task_config", name, f"{name}.xml", xml
    )


def test_cts0025_flags_shared_gvl_write_from_two_contexts():
    gvl = _st_unit_named(
        "GVL.st", "VAR_GLOBAL\n    Shared : INT;\nEND_VAR\n"
    )
    program = _st_unit_named(
        "Main.st",
        "PROGRAM Main\nIMPLEMENTATION\nGVL.Shared := 1; // cts:here\nEND_PROGRAM\n",
    )
    snapshot = ProjectSnapshot(
        ".", [gvl, program, _task_unit("Fast", "Main"), _task_unit("Slow", "Main")]
    )
    findings = run_rule("CTS0025", snapshot)
    assert [finding.anchor for finding in findings] == ["GVL.Shared"]


def test_cts0025_ignores_local_and_single_context_writes():
    gvl = _st_unit_named(
        "GVL.st", "VAR_GLOBAL\n    Shared : INT;\nEND_VAR\n"
    )
    program = _st_unit_named(
        "Main.st",
        "PROGRAM Main\nVAR\n    Local : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nLocal := 1;\nGVL.Shared := 1;\nEND_PROGRAM\n",
    )
    snapshot = ProjectSnapshot(".", [gvl, program, _task_unit("Fast", "Main")])
    assert run_rule("CTS0025", snapshot) == []


def test_cts0025_follows_calls_into_functions():
    gvl = _st_unit_named(
        "GVL.st", "VAR_GLOBAL\n    Shared : INT;\nEND_VAR\n"
    )
    main = _st_unit_named(
        "Main.st", "PROGRAM Main\nIMPLEMENTATION\nWriteShared();\nEND_PROGRAM\n"
    )
    helper = _st_unit_named(
        "WriteShared.st",
        "FUNCTION WriteShared\nIMPLEMENTATION\nGVL.Shared := 1;\nEND_FUNCTION\n",
    )
    snapshot = ProjectSnapshot(
        ".",
        [
            gvl,
            main,
            helper,
            _task_unit("Fast", "Main"),
            _task_unit("Slow", "Main"),
        ],
    )
    findings = run_rule("CTS0025", snapshot)
    assert len(findings) == 1
    assert findings[0].anchor == "GVL.Shared"
    assert findings[0].location.path == "WriteShared.st"


def test_cts0025_flags_read_write_between_tasks():
    gvl = _st_unit_named(
        "GVL.st", "VAR_GLOBAL\n    Shared : INT;\nEND_VAR\n"
    )
    writer = _st_unit_named(
        "Writer.st",
        "PROGRAM Writer\nIMPLEMENTATION\nGVL.Shared := 1;\nEND_PROGRAM\n",
    )
    reader = _st_unit_named(
        "Reader.st",
        "PROGRAM Reader\nIMPLEMENTATION\nIF GVL.Shared > 0 THEN\nEND_IF;\nEND_PROGRAM\n",
    )
    snapshot = ProjectSnapshot(
        ".",
        [gvl, writer, reader, _task_unit("Fast", "Writer"), _task_unit("Slow", "Reader")],
    )
    findings = run_rule("CTS0025", snapshot)
    assert len(findings) == 1
    assert "written in task 'Fast' and read in task 'Slow'" in findings[0].message


# ---------------------------------------------------------------------------
# CTS0026 - overlapping AT memory areas
# ---------------------------------------------------------------------------


def test_cts0026_flags_overlapping_byte_and_dword_addresses():
    unit = _st_unit_named(
        "GVL.st",
        "VAR_GLOBAL\n"
        "    Status AT %QB21 : BYTE;\n"
        "    Count AT %QD5 : DWORD;\n"
        "END_VAR\n",
    )
    findings = run_rule("CTS0026", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["Count"]


def test_cts0026_handles_bits_and_ignores_unknown_or_nonoverlapping_types():
    unit = _st_unit_named(
        "GVL.st",
        "VAR_GLOBAL\n"
        "    Ready AT %IX0.6 : BOOL;\n"
        "    Other AT %IX0.7 : BOOL;\n"
        "    WordValue AT %IW2 : WORD;\n"
        "    StructValue AT %IB3 : MyStruct;\n"
        "END_VAR\n",
    )
    assert run_rule("CTS0026", ProjectSnapshot(".", [unit])) == []


def test_cts0026_treats_input_bytes_as_eight_bits():
    unit = _st_unit_named(
        "Inputs.st",
        "VAR_GLOBAL\n"
        "    LastBit AT %IX0.7 : BOOL;\n"
        "    NextByte AT %IX1.0 : BOOL;\n"
        "END_VAR\n",
    )
    assert run_rule("CTS0026", ProjectSnapshot(".", [unit])) == []


def test_cts0026_reports_overlap_across_units_and_separates_memory_areas():
    first = _st_unit_named(
        "First.st", "VAR_GLOBAL\n    A AT %MB10 : WORD;\nEND_VAR\n"
    )
    second = _st_unit_named(
        "Second.st", "VAR_GLOBAL\n    B AT %MB11 : BYTE;\nEND_VAR\n"
    )
    output = _st_unit_named(
        "Output.st", "VAR_GLOBAL\n    Q AT %QB10 : WORD;\nEND_VAR\n"
    )
    findings = run_rule("CTS0026", ProjectSnapshot(".", [first, second, output]))
    assert [(f.anchor, f.unit_id) for f in findings] == [("B", "Second.st#Second")]


# ---------------------------------------------------------------------------
# CTS0027 - temporary function-block instance
# ---------------------------------------------------------------------------


def test_cts0027_flags_local_function_block_in_function_and_method():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    function = _st_unit_named(
        "Calculate.st",
        "FUNCTION Calculate : BOOL\nVAR\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nCalculate := Timer.Q;\n",
    )
    method = _st_unit_named(
        "Controller.Step.st",
        "METHOD Step : BOOL\nVAR_TEMP\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nStep := Timer.Q;\n",
    )
    findings = run_rule("CTS0027", ProjectSnapshot(".", [fb, function, method]))
    assert [(f.anchor, f.unit_id) for f in findings] == [
        ("Timer", "Calculate.st#Calculate"),
        ("Timer", "Controller.Step.st#Controller.Step"),
    ]


def test_cts0027_ignores_persistent_instances_and_unknown_types():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    program = _st_unit_named(
        "Main.st",
        "PROGRAM Main\nVAR\n    Timer : TON;\n    Custom : UnknownFB;\nEND_VAR\n"
        "IMPLEMENTATION\n",
    )
    function = _st_unit_named(
        "F.st",
        "FUNCTION F : BOOL\nVAR_STAT\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\n",
    )
    assert run_rule("CTS0027", ProjectSnapshot(".", [fb, program, function])) == []


# ---------------------------------------------------------------------------
# CTS0028 - suspicious STRING operation
# ---------------------------------------------------------------------------


def test_cts0028_flags_index_address_and_non_ascii_literal():
    unit = _st_unit(
        "FUNCTION Inspect : BOOL\nVAR\n"
        "    Text : STRING(80);\n    Code : BYTE;\nEND_VAR\n"
        "IMPLEMENTATION\nCode := Text[2];\nADR(Text);\nText := 'Ä';\n"
        "Inspect := TRUE;\n"
    )
    findings = run_rule("CTS0028", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["Text", "Text", "Text"]


def test_cts0028_ignores_normal_string_use_other_types_and_ascii():
    unit = _st_unit(
        "FUNCTION Build : STRING\nVAR_INPUT\n    Part : STRING;\nEND_VAR\n"
        "VAR\n    Bytes : ARRAY[0..3] OF BYTE;\nEND_VAR\nIMPLEMENTATION\n"
        "Build := CONCAT('A', Part);\nPart := 'ABC';\nBytes[2] := 1;\n"
    )
    assert run_rule("CTS0028", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0029 - multiple calls to one function-block instance
# ---------------------------------------------------------------------------


def test_cts0029_flags_repeated_instance_call_on_one_path():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    function = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nVAR\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nTimer(IN := TRUE);\nTimer(IN := FALSE);\n"
        "Run := Timer.Q;\n",
    )
    findings = run_rule("CTS0029", ProjectSnapshot(".", [fb, function]))
    assert [finding.anchor for finding in findings] == ["Timer"]


def test_cts0029_separates_exclusive_branches_and_instances():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    function = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nVAR\n    First : TON;\n    Second : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Enabled THEN\n    First();\nELSE\n    First();\nEND_IF;\nSecond();\nRun := TRUE;\n",
    )
    assert run_rule("CTS0029", ProjectSnapshot(".", [fb, function])) == []


# ---------------------------------------------------------------------------
# CTS0030 - FOR counter modified inside the loop
# ---------------------------------------------------------------------------


def test_cts0030_flags_direct_for_counter_assignment():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "FOR i := 0 TO 10 DO\n"
        "    IF Values[i] = 0 THEN\n"
        "        i := i + 1;\n"
        "    END_IF;\n"
        "END_FOR;\n"
    )
    findings = run_rule("CTS0030", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].message == "FOR loop control variable 'i' is modified inside the loop"


def test_cts0030_ignores_reads_and_named_call_arguments():
    unit = _st_unit(
        "PROGRAM P\nIMPLEMENTATION\n"
        "FOR i := 0 TO 10 DO\n"
        "    Values[i] := i;\n"
        "    Timer(IN := TRUE);\n"
        "END_FOR;\n"
    )
    assert run_rule("CTS0030", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0031 - conditional function-block call
# ---------------------------------------------------------------------------


def test_cts0031_flags_stateful_fb_call_inside_if():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    function = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nVAR\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Enabled THEN\n    Timer(IN := TRUE);\nEND_IF;\n",
    )
    findings = run_rule("CTS0031", ProjectSnapshot(".", [fb, function]))
    assert [finding.anchor for finding in findings] == ["Timer"]


def test_cts0031_flags_stateful_fb_call_inside_case():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    function = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nVAR\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nCASE State OF\n1: Timer(IN := TRUE);\nEND_CASE;\n",
    )
    findings = run_rule("CTS0031", ProjectSnapshot(".", [fb, function]))
    assert [finding.anchor for finding in findings] == ["Timer"]


def test_cts0031_ignores_unconditional_call():
    fb = _st_unit_named("TON.st", "FUNCTION_BLOCK TON\nEND_FUNCTION_BLOCK\n")
    function = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nVAR\n    Timer : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nTimer(IN := Enabled);\n",
    )
    assert run_rule("CTS0031", ProjectSnapshot(".", [fb, function])) == []


# ---------------------------------------------------------------------------
# CTS0032 - stateless function block
# ---------------------------------------------------------------------------


def test_cts0032_flags_stateless_function_block():
    fb = _st_unit_named(
        "Calculate.st",
        "FUNCTION_BLOCK Calculate\nVAR_INPUT\n    Value : INT;\nEND_VAR\n"
        "VAR_OUTPUT\n    Result : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nResult := Value + 1;\nEND_FUNCTION_BLOCK\n",
    )
    findings = run_rule("CTS0032", ProjectSnapshot(".", [fb]))
    assert [finding.anchor for finding in findings] == ["Calculate"]
    assert findings[0].severity == "style"


def test_cts0032_ignores_function_block_with_state():
    fb = _st_unit_named(
        "Controller.st",
        "FUNCTION_BLOCK Controller\nVAR\n    Count : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nCount := Count + 1;\nEND_FUNCTION_BLOCK\n",
    )
    assert run_rule("CTS0032", ProjectSnapshot(".", [fb])) == []


# ---------------------------------------------------------------------------
# CTS0033 - variable could be declared CONSTANT
# ---------------------------------------------------------------------------


def test_cts0033_flags_constant_initialized_local_variable():
    unit = _st_unit(
        "FUNCTION Calculate : INT\nVAR\n"
        "    MaxRetries : INT := 3;\n    Result : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nResult := MaxRetries + 1;\nCalculate := Result;\n"
    )
    findings = run_rule("CTS0033", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["MaxRetries"]
    assert findings[0].severity == "style"


def test_cts0033_ignores_mutations_aliases_and_nonconstant_initializers():
    unit = _st_unit(
        "FUNCTION Calculate : INT\nVAR\n"
        "    Changed : INT := 3;\n    Passed : INT := 4;\n"
        "    Dynamic : INT := InputValue;\n    Data : ARRAY[0..2] OF INT := [1, 2, 3];\n"
        "END_VAR\nIMPLEMENTATION\n"
        "Changed := Changed + 1;\nConsume(Passed);\nCalculate := Dynamic + Data[0];\n"
    )
    assert run_rule("CTS0033", ProjectSnapshot(".", [unit])) == []


def test_cts0033_ignores_existing_constant_and_at_declarations():
    unit = _st_unit(
        "FUNCTION Calculate : INT\nVAR CONSTANT\n    Limit : INT := 3;\nEND_VAR\n"
        "VAR\n    Addressed AT %MW0 : INT := 4;\nEND_VAR\nIMPLEMENTATION\n"
        "Calculate := Limit + Addressed;\n"
    )
    assert run_rule("CTS0033", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0034 - ignored function return value
# ---------------------------------------------------------------------------


def test_cts0034_flags_standalone_project_function_call():
    function = _st_unit_named(
        "Check.st",
        "FUNCTION Check : BOOL\nVAR_INPUT\n    Value : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nCheck := Value > 0;\n",
    )
    caller = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nIMPLEMENTATION\nCheck(10);\nRun := TRUE;\n",
    )
    findings = run_rule("CTS0034", ProjectSnapshot(".", [function, caller]))
    assert [finding.anchor for finding in findings] == ["Check"]


def test_cts0034_ignores_used_returns_unknown_calls_and_fb_calls():
    function = _st_unit_named(
        "Check.st",
        "FUNCTION Check : BOOL\nIMPLEMENTATION\nCheck := TRUE;\n",
    )
    fb = _st_unit_named("Timer.st", "FUNCTION_BLOCK Timer\nEND_FUNCTION_BLOCK\n")
    caller = _st_unit_named(
        "Run.st",
        "FUNCTION Run : BOOL\nVAR\n    T : Timer;\n    Ok : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nOk := Check();\nUnknown();\nT();\nRun := Ok;\n",
    )
    assert run_rule("CTS0034", ProjectSnapshot(".", [function, fb, caller])) == []


# ---------------------------------------------------------------------------
# CTS0035 - division by literal zero
# ---------------------------------------------------------------------------


def test_cts0035_flags_integer_real_and_typed_zero_divisors():
    unit = _st_unit(
        "FUNCTION Calc : LREAL\nIMPLEMENTATION\n"
        "Calc := 10 / 0 + 1.0 / 0.0 + 2 / DINT#0;\n"
    )
    findings = run_rule("CTS0035", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["0", "0.0", "DINT#0"]
    assert all(f.rule_id == "CTS0035" for f in findings)


def test_cts0035_ignores_nonzero_and_variable_divisors():
    unit = _st_unit(
        "FUNCTION Calc : REAL\nVAR_INPUT\n"
        "    Divisor : REAL;\nEND_VAR\nIMPLEMENTATION\n"
        "Calc := 10 / 10 + 10 / Divisor;\n"
    )
    assert run_rule("CTS0035", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0036 - duplicate IF condition
# ---------------------------------------------------------------------------


def test_cts0036_flags_repeated_condition_in_one_chain():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR_INPUT\n Ready : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Ready THEN\n Start();\n"
        "ELSIF  Ready  THEN\n Retry();\nEND_IF;\nRun := Ready;\n"
    )
    findings = run_rule("CTS0036", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "Ready"
    assert findings[0].rule_id == "CTS0036"


def test_cts0036_ignores_different_chains_and_conditions():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nIMPLEMENTATION\n"
        "IF Ready THEN\n Start();\nELSIF Fault THEN\n Stop();\nEND_IF;\n"
        "IF Ready THEN\n Start();\nEND_IF;\nRun := TRUE;\n"
    )
    assert run_rule("CTS0036", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0037 - no-op control-flow branch
# ---------------------------------------------------------------------------


def test_cts0037_flags_noop_else_and_case_branches():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR_INPUT\n State : INT;\n Ready : BOOL;\nEND_VAR\n"
        "IMPLEMENTATION\nIF Ready THEN\n Start();\nELSE\n;\nEND_IF;\n"
        "CASE State OF\n 1: Start();\nELSE\n ;\nEND_CASE;\nRun := TRUE;\n"
    )
    findings = run_rule("CTS0037", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert all(f.anchor == ";" for f in findings)


def test_cts0037_ignores_real_branch_body_and_standalone_statement():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nIMPLEMENTATION\n"
        "IF Ready THEN\n;\nDoWork();\nELSE\nDoOtherWork();\nEND_IF;\n"
        ";\nRun := TRUE;\n"
    )
    assert run_rule("CTS0037", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0038 - invalid FOR loop step
# ---------------------------------------------------------------------------


def test_cts0038_flags_zero_and_wrong_direction_steps():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR i : INT; END_VAR\nIMPLEMENTATION\n"
        "FOR i := 0 TO 10 BY 0 DO Work(); END_FOR;\n"
        "FOR i := 0 TO 10 BY -1 DO Work(); END_FOR;\n"
        "FOR i := 10 TO 0 BY 1 DO Work(); END_FOR;\nRun := TRUE;\n"
    )
    findings = run_rule("CTS0038", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["0", "-1", "1"]


def test_cts0038_ignores_valid_or_variable_steps():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR i, first, last, step : INT; END_VAR\n"
        "IMPLEMENTATION\nFOR i := 0 TO 10 BY 1 DO Work(); END_FOR;\n"
        "FOR i := 10 TO 0 BY -1 DO Work(); END_FOR;\n"
        "FOR i := first TO last BY step DO Work(); END_FOR;\nRun := TRUE;\n"
    )
    assert run_rule("CTS0038", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0039 - FOR range exceeds array bounds
# ---------------------------------------------------------------------------


def test_cts0039_flags_counter_access_outside_array_range():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n"
        " Values : ARRAY[0..9] OF INT;\n i : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nFOR i := 0 TO 10 DO Values[i] := 0; END_FOR;\n"
        "Run := TRUE;\n"
    )
    findings = run_rule("CTS0039", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "Values[i]"


def test_cts0039_ignores_fitting_range_and_non_counter_access():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n"
        " Values : ARRAY[0..9] OF INT;\n i, j : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nFOR i := 0 TO 9 DO Values[i] := 0; Values[j] := 1; END_FOR;\n"
        "Run := TRUE;\n"
    )
    assert run_rule("CTS0039", ProjectSnapshot(".", [unit])) == []


def test_cts0039_checks_nested_for_counters_against_multidimensional_bounds():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n"
        " Grid : ARRAY[0..2, 10..12] OF INT;\n"
        " i, j : INT;\nEND_VAR\n"
        "IMPLEMENTATION\n"
        "FOR i := 0 TO 2 DO\n"
        "    FOR j := 10 TO 13 DO Grid[i, j] := 0; END_FOR;\n"
        "END_FOR;\n"
        "Run := TRUE;\n"
    )
    findings = run_rule("CTS0039", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "Grid[i, j]"
    assert "dimension 2" in findings[0].message


def test_cts0039_ignores_fitting_multidimensional_nested_for():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n"
        " Grid : ARRAY[-1..2, 10..12] OF INT;\n"
        " i, j : INT;\nEND_VAR\n"
        "IMPLEMENTATION\n"
        "FOR i := -1 TO 2 DO\n"
        "    FOR j := 10 TO 12 DO Grid[i, j] := 0; END_FOR;\n"
        "END_FOR;\n"
        "Run := TRUE;\n"
    )
    assert run_rule("CTS0039", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0040 - shift amount outside operand width
# ---------------------------------------------------------------------------


def test_cts0040_flags_shift_at_or_above_operand_width():
    unit = _st_unit(
        "FUNCTION Run : BYTE\nVAR\n b : BYTE;\n w : WORD;\nEND_VAR\n"
        "IMPLEMENTATION\nRun := SHL(b, 8); w := SHR(w, 16);\n"
        "Run := SHL(b, 7);\n"
    )
    findings = run_rule("CTS0040", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["8", "16"]


def test_cts0040_ignores_unknown_type_and_variable_amount():
    unit = _st_unit(
        "FUNCTION Run : BYTE\nVAR\n b : BYTE;\n amount : INT;\nEND_VAR\n"
        "IMPLEMENTATION\nRun := SHL(b, amount);\n"
    )
    assert run_rule("CTS0040", ProjectSnapshot(".", [unit])) == []


# ---------------------------------------------------------------------------
# CTS0041 - bit index outside type width
# ---------------------------------------------------------------------------


def test_cts0041_flags_bit_index_at_or_above_type_width():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n b : BYTE;\n w : WORD;\nEND_VAR\n"
        "IMPLEMENTATION\nb.8 := TRUE; w.16 := FALSE; b.7 := TRUE;\n"
        "Run := b.7;\n"
    )
    findings = run_rule("CTS0041", ProjectSnapshot(".", [unit]))
    assert [finding.anchor for finding in findings] == ["b.8", "w.16"]


# ---------------------------------------------------------------------------
# CTS0042 - zero timer preset time
# ---------------------------------------------------------------------------


def test_cts0042_flags_zero_timer_pt():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n T : TON;\nEND_VAR\n"
        "IMPLEMENTATION\nT(PT := T#0s); T(PT := T#100ms); Run := T.Q;\n"
    )
    findings = run_rule("CTS0042", ProjectSnapshot(".", [unit]))
    assert len(findings) == 1
    assert findings[0].anchor == "T#0s"


# ---------------------------------------------------------------------------
# CTS0043 - comparison outside type range
# ---------------------------------------------------------------------------


def test_cts0043_flags_always_true_and_false_type_comparisons():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n u : UINT;\n b : BYTE;\nEND_VAR\n"
        "IMPLEMENTATION\nIF u >= 0 THEN Run := TRUE; END_IF;\n"
        "IF b > 300 THEN Run := FALSE; END_IF;\n"
    )
    findings = run_rule("CTS0043", ProjectSnapshot(".", [unit]))
    assert len(findings) == 2
    assert "always true" in findings[0].message
    assert "always false" in findings[1].message


def test_cts0043_does_not_flag_in_range_equality_or_inequality():
    unit = _st_unit(
        "FUNCTION Run : BOOL\nVAR\n u : UINT;\nEND_VAR\n"
        "IMPLEMENTATION\n"
        "IF u = 24 THEN Run := TRUE; END_IF;\n"
        "IF u <> 24 THEN Run := TRUE; END_IF;\n"
    )
    findings = run_rule("CTS0043", ProjectSnapshot(".", [unit]))
    assert findings == []
