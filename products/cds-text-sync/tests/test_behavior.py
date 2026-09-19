"""Tests for declaration-backed behavior fact extraction."""

from cds_static_analyzer import project
from cds_text_sync.docs.behavior import extract_behavior


def test_extract_behavior_returns_structured_facts_with_source_lines():
    unit = project._build_st_unit(
        "FB_Filter.st",
        "FUNCTION_BLOCK FB_Filter\n"
        "VAR_OUTPUT\n    xDone : BOOL;\nEND_VAR\n"
        "VAR\n    timer : TON;\n    retries : INT;\n    state : INT;\nEND_VAR\n"
        "IMPLEMENTATION\n"
        "IF NOT xEnable OR ERROR THEN RETURN; END_IF\n"
        "CASE state OF\n"
        "    Idle: timer(IN := TRUE);\n"
        "END_CASE\n"
        "xDone := TRUE;\n"
        "FOR retries := 0 TO 3 BY 1 DO\nEND_FOR\n"
        "RETURN;\n",
    )

    status, facts, summary = extract_behavior(unit)

    kinds = {fact["kind"] for fact in facts}
    assert status == "partial"
    assert {
        "case_state", "timer_call", "output_write", "status_write", "for_loop",
        "return", "counter", "protective_branch",
    } <= kinds
    assert all(fact["source_span"]["line"] > 0 for fact in facts)
    assert "timer_call" in summary


def test_extract_behavior_classifies_error_and_completion_flags():
    unit = project._build_st_unit(
        "FB_Status.st",
        "FUNCTION_BLOCK FB_Status\n"
        "VAR_OUTPUT\n    xDone : BOOL;\nEND_VAR\n"
        "VAR\n    xError : BOOL;\n    eStatus : INT;\nEND_VAR\n"
        "IMPLEMENTATION\n"
        "xError := FALSE;\n"
        "eStatus := 1;\n"
        "xDone := TRUE;\n",
    )

    _status, facts, _summary = extract_behavior(unit)

    status_facts = [fact for fact in facts if fact["kind"] == "status_write"]
    assert {(fact["flag"], fact["category"]) for fact in status_facts} == {
        ("xError", "error"),
        ("eStatus", "status"),
        ("xDone", "completion"),
    }
    assert all(fact["confidence"] == "medium" for fact in status_facts)
