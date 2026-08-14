# -*- coding: utf-8 -*-
"""
test_fsm_extract.py -- FSM extraction from Structured Text.

Covers the five real dialects and the two negative cases from the validated
corpus, plus cross-contamination, global transitions, guard extraction, named
call arguments, and commented-out transitions.
"""

from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_rules import normalize, same_family


def _machines(text):
    return find_machines(text, base=0)


def _one(text):
    machines = _machines(text)
    assert len(machines) == 1, "expected exactly one machine, got %d" % len(machines)
    return machines[0]


# ---------------------------------------------------------------------------
# normalize / same_family (the validated rule, imported not re-typed)
# ---------------------------------------------------------------------------


def test_normalize_folds_next_new():
    assert normalize("P.next_state") == normalize("P.state")
    assert normalize("NEXT_STATE") == normalize("STATE")
    assert normalize("_nextFsmState") == normalize("_fsmState")
    assert normalize("initStep") == normalize("initStep")


def test_same_family_positive():
    assert same_family("P.next_state", "P.state")
    assert same_family("NEXT_STATE", "STATE")
    assert same_family("_nextFsmState", "_fsmState")
    assert same_family("initStep", "initStep")


def test_same_family_negative():
    assert not same_family("STATE_BF2", "STATE_BF1")
    assert not same_family("_InitialStatus", "i_InitialStatus")


def test_normalize_folds_the_current_half_of_an_act_next_pair():
    assert normalize("act_step") == normalize("next_step")
    assert normalize("actStep") == normalize("nextStep")
    assert normalize("ACT_STEP") == normalize("NEXT_STEP")
    assert normalize("cur_state") == normalize("state")
    assert normalize("ACTUAL_STATE") == normalize("STATE")
    assert normalize("step_act") == normalize("step")


def test_normalize_leaves_a_phase_token_inside_a_word_alone():
    # The fold is boundary-aware, so a phase token inside a word survives.
    assert normalize("impact") == "IMPACT"
    assert normalize("reactor") == "REACTOR"
    assert normalize("fact") == "FACT"
    assert normalize("act") == "ACT"


def test_same_family_pairs_a_swapped_act_next_selector():
    assert same_family("p.next_step", "p.act_step")
    assert not same_family("p.next_step", "q.act_step")


# ---------------------------------------------------------------------------
# POSITIVE: the five real dialects
# ---------------------------------------------------------------------------


def test_struct_with_external_commit():
    text = (
        "CASE P.state OF\n"
        "ENUM_X.A:\n"
        "  IF c THEN\n"
        "    P.next_state := ENUM_X.B;\n"
        "  END_IF\n"
        "ENUM_X.B:\n"
        "  P.next_state := ENUM_X.A;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert len(m.transitions) == 2
    t = [t for t in m.transitions if t.source == "ENUM_X.A"][0]
    assert t.target == "ENUM_X.B"
    assert t.deferred
    assert m.deferred


def test_two_plain_vars_with_inline_commit():
    text = (
        "IF STATE <> NEXT_STATE THEN\n"
        "  STATE := NEXT_STATE;\n"
        "END_IF\n"
        "CASE STATE OF\n"
        "DOOR_STATE.INIT:\n"
        "  NEXT_STATE := DOOR_STATE.LOCKED;\n"
        "DOOR_STATE.LOCKED:\n"
        "  NEXT_STATE := DOOR_STATE.INIT;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert m.commit_offset is not None
    # The inline commit must NOT be an edge.
    assert len(m.transitions) == 2
    t = [t for t in m.transitions if t.source == "DOOR_STATE.INIT"][0]
    assert t.target == "DOOR_STATE.LOCKED"
    # NEXT_STATE is the next-twin of STATE, so the transition is deferred.
    assert t.deferred


def test_camelcase_twin_numeric_labels():
    text = (
        "CASE _fsmState OF\n"
        "0:\n"
        "  _nextFsmState := 10;\n"
        "10:\n"
        "  _nextFsmState := 20;\n"
        "20:\n"
        "  _nextFsmState := 0;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert m.numeric
    assert len(m.states) == 3
    assert len(m.transitions) == 3
    assert all(t.deferred for t in m.transitions)
    assert m.deferred


def test_no_twin_enum_labels():
    text = (
        "CASE STATE_BF1 OF\n"
        "BF_STATE.IDLE:\n"
        "  STATE_BF1 := BF_STATE.RUN;\n"
        "BF_STATE.RUN:\n"
        "  STATE_BF1 := BF_STATE.IDLE;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert len(m.transitions) == 2
    t = [t for t in m.transitions if t.source == "BF_STATE.IDLE"][0]
    assert t.target == "BF_STATE.RUN"
    assert not t.deferred


def test_no_twin_numeric_labels():
    text = (
        "CASE initStep OF\n"
        "0:\n"
        "  initStep := 1;\n"
        "1:\n"
        "  initStep := 0;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert m.numeric
    assert len(m.transitions) == 2
    t = [t for t in m.transitions if t.source == "0"][0]
    assert t.target == "1"


# ---------------------------------------------------------------------------
# NEGATIVE: must not be classified as FSM
# ---------------------------------------------------------------------------


def test_lookup_table_not_fsm():
    text = (
        "CASE i_InitialStatus OF\n"
        "Carrier_status.NONE:\n"
        "  _InitialStatus := 'NONE';\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert not m.is_fsm
    assert m.transitions == []


def test_command_dispatch_not_fsm():
    text = (
        "CASE CMD OF\n"
        "SCN_CMD.CHECK:\n"
        "  messageLength := 10;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert not m.is_fsm
    assert m.transitions == []


# ---------------------------------------------------------------------------
# Cross-contamination: two CASEs sharing an enum must not leak edges
# ---------------------------------------------------------------------------


def test_cross_contamination_two_machines():
    text = (
        "CASE STATE_BF1 OF\n"
        "BF_STATE.IDLE:\n"
        "  STATE_BF1 := BF_STATE.RUN;\n"
        "BF_STATE.RUN:\n"
        "  STATE_BF1 := BF_STATE.IDLE;\n"
        "END_CASE\n"
        "CASE STATE_BF2 OF\n"
        "BF_STATE.IDLE:\n"
        "  STATE_BF2 := BF_STATE.RUN;\n"
        "BF_STATE.RUN:\n"
        "  STATE_BF2 := BF_STATE.IDLE;\n"
        "END_CASE\n"
    )
    machines = _machines(text)
    assert len(machines) == 2
    m1, m2 = machines
    assert m1.selector == "STATE_BF1"
    assert m2.selector == "STATE_BF2"
    assert len(m1.transitions) == 2
    assert len(m2.transitions) == 2
    assert all(t.lhs == "STATE_BF1" for t in m1.transitions)
    assert all(t.lhs == "STATE_BF2" for t in m2.transitions)


# ---------------------------------------------------------------------------
# Global transition, guard extraction, call args, comments
# ---------------------------------------------------------------------------


def test_global_transition_outside_case():
    text = (
        "P.next_state := ENUM_X.B;\n"
        "CASE P.state OF\n"
        "ENUM_X.A:\n"
        "  P.next_state := ENUM_X.C;\n"
        "ENUM_X.B:\n"
        "  P.next_state := ENUM_X.A;\n"
        "ENUM_X.C:\n"
        "  P.next_state := ENUM_X.A;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert len(m.transitions) == 4
    global_t = [t for t in m.transitions if t.source is None]
    assert len(global_t) == 1
    assert global_t[0].target == "ENUM_X.B"


def test_guard_extraction_two_ifs_deep():
    text = (
        "CASE P.state OF\n"
        "ENUM_X.A:\n"
        "  IF a THEN\n"
        "    IF b THEN\n"
        "      P.next_state := ENUM_X.B;\n"
        "    END_IF\n"
        "  END_IF\n"
        "ENUM_X.B:\n"
        "  P.next_state := ENUM_X.A;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    t = [t for t in m.transitions if t.source == "ENUM_X.A"][0]
    guard = t.guard
    assert "a" in guard and "b" in guard
    assert " AND " in guard


def test_named_call_arguments_not_assignments():
    text = (
        "CASE P.state OF\n"
        "ENUM_X.A:\n"
        "  f(CMD := SCN_CMD.READ, Get_Info := GetInfo.x);\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert not m.is_fsm
    assert m.transitions == []


def test_commented_out_transition_ignored():
    text = (
        "CASE P.state OF\n"
        "ENUM_X.A:\n"
        "  // P.next_state := ENUM_X.B;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert not m.is_fsm
    assert m.transitions == []


def test_inline_comment_in_assignment_does_not_hide_the_target():
    """``:= ST.B (* go *);`` is an edge, not an unknown-value warning.

    The right-hand side must be matched against the blanked text; slicing it
    from the raw text drags the comment into the comparison and loses the
    edge.
    """
    text = (
        "CASE P.state OF\n"
        "ST.A:\n"
        "  P.next_state := ST.B (* go now *);\n"
        "ST.B:\n"
        "  P.next_state := ST.A;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert m.is_fsm
    assert len(m.transitions) == 2
    assert sorted(t.target for t in m.transitions) == ["ST.A", "ST.B"]
    assert m.warnings == []


def test_dispatch_case_reports_no_warnings():
    """A lookup/dispatch CASE is not an FSM, so it gets no diagnostics.

    Otherwise every branch trivially reports "no outgoing transition" and one
    non-FSM CASE emits a warning per branch, burying the real findings.
    """
    text = (
        "CASE cmd OF\n"
        "CMD.READ:\n"
        "  len := 10;\n"
        "CMD.WRITE:\n"
        "  len := 20;\n"
        "CMD.PING:\n"
        "  len := 2;\n"
        "END_CASE\n"
    )
    m = _one(text)
    assert not m.is_fsm
    assert m.warnings == []


def test_a_numeric_act_next_step_machine_is_detected():
    source = (
        "IF p.act_step <> p.next_step THEN\n"
        "    p.act_step := p.next_step;\n"
        "END_IF\n"
        "IF DB_CONTROLS.STOP THEN\n"
        "    p.next_step := 0;\n"
        "END_IF\n"
        "CASE p.act_step OF\n"
        "  0:\n"
        "    IF start THEN p.next_step := 10; END_IF\n"
        "  10:\n"
        "    IF ready THEN p.next_step := 15; END_IF\n"
        "  15:\n"
        "    IF pause THEN p.next_step := 20; END_IF\n"
        "  20:\n"
        "    IF resume THEN p.next_step := 15; END_IF\n"
        "END_CASE\n"
    )
    machines = _machines(source)
    assert len(machines) == 1
    m = machines[0]
    assert m.is_fsm
    assert m.selector == "p.act_step"
    assert [s.label for s in m.states] == ["0", "10", "15", "20"]
    assert m.numeric
    assert len(m.transitions) == 5
    global_t = [t for t in m.transitions if t.source is None]
    assert len(global_t) == 1
    assert global_t[0].target == "0"
    assert m.commit_offset is not None
    assert not any("next_step" in w[1] for w in m.warnings)


# ---------------------------------------------------------------------------
# Cost: the body is walked once, not once per CASE site
# ---------------------------------------------------------------------------


def _many_case_bodies(count):
    """A body with *count* independent CASE machines, each with its own name."""
    parts = []
    for index in range(count):
        parts.append(
            "CASE state_{0} OF\n"
            " 0: IF go THEN state_{0} := 10; END_IF\n"
            " 10: IF done THEN state_{0} := 0; END_IF\n"
            "END_CASE\n"
            "other_{0} := 1;\n".format(index)
        )
    return "".join(parts)


def test_the_body_is_scanned_for_assignments_once_per_call():
    """Guards the fix for the quadratic scan that hung the picker.

    ``_build_machine`` used to walk every statement in the file, so a block
    with N CASE sites paid N full passes and a large function block sat in
    "analyzing" for a minute. The index is built once and shared.
    """
    import cts_shared.st.fsm as fsm

    calls = []
    real = fsm.statements

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    fsm.statements = counting
    try:
        machines = fsm.find_machines(_many_case_bodies(5))
    finally:
        fsm.statements = real
    assert len(machines) == 5
    assert all(m.is_fsm for m in machines)
    assert len(calls) == 1


def test_each_case_site_still_sees_only_its_own_family():
    machines = _machines(_many_case_bodies(3))
    assert [m.selector for m in machines] == ["state_0", "state_1", "state_2"]
    for m in machines:
        assert len(m.transitions) == 2
        assert all(t.lhs == m.selector for t in m.transitions)
        assert m.warnings == []
