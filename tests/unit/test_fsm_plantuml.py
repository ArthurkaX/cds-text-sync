"""Unit tests for the PlantUML FSM emitter (cts_shared.st.fsm_plantuml)."""

from cds_text_sync.engine.variable_map import ST_IMPLEMENTATION_MARKER, split_decl_impl
from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_plantuml import to_plantuml


SAMPLE_ST = (
    "PROGRAM Motor\n"
    "VAR\n"
    "  state : INT;\n"
    "  start : BOOL;\n"
    "  done : BOOL;\n"
    "END_VAR\n"
    + ST_IMPLEMENTATION_MARKER + "\n"
    "CASE state OF\n"
    "  0: IF start THEN state := 1; END_IF\n"
    "  1: IF done THEN state := 2; END_IF\n"
    "  2: state := 0;\n"
    "END_CASE\n"
)

# An assignment after END_CASE sits outside every state branch, so the
# detector records it with source is None -- the "any state" transition.
SOURCELESS_ST = (
    "PROGRAM Pump\n"
    "VAR\n"
    "  state : INT;\n"
    "END_VAR\n"
    + ST_IMPLEMENTATION_MARKER + "\n"
    "CASE state OF\n"
    "  0: state := 1;\n"
    "  1: state := 0;\n"
    "END_CASE\n"
    "state := 0;\n"
)

# next_state is the selector's twin, so these transitions are deferred.
DEFERRED_ST = (
    "PROGRAM Motor\n"
    "VAR\n"
    "  state : INT;\n"
    "  next_state : INT;\n"
    "  start : BOOL;\n"
    "END_VAR\n"
    + ST_IMPLEMENTATION_MARKER + "\n"
    "CASE state OF\n"
    "  0: IF start THEN next_state := 1; END_IF\n"
    "  1: next_state := 0;\n"
    "END_CASE\n"
)


def _body(text):
    """The section a file scan feeds to find_machines."""
    _decl, impl = split_decl_impl(text)
    return impl if impl is not None else text


def _first_machine(text):
    return next(machine for machine in find_machines(_body(text)) if machine.is_fsm)


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


def test_output_starts_with_startuml_and_ends_with_enduml():
    output = to_plantuml(_first_machine(SAMPLE_ST))
    lines = output.splitlines()
    assert lines[0] == "@startuml"
    assert lines[-1] == "@enduml"
    assert not output.endswith("\n")


def test_state_declarations_follow_machine_states_order():
    lines = to_plantuml(_first_machine(SAMPLE_ST)).splitlines()
    s0 = lines.index('state "0" as s0')
    s1 = lines.index('state "1" as s1')
    s2 = lines.index('state "2" as s2')
    assert s0 < s1 < s2


def test_transitions_emitted_in_ascending_offset_order():
    machine = _first_machine(SAMPLE_ST)
    # Put the transitions out of source order so the sort is observable.
    for transition, offset in zip(machine.transitions, (30, 20, 10)):
        transition.offset = offset
    lines = to_plantuml(machine).splitlines()
    transition_lines = [line for line in lines if "-->" in line]
    assert transition_lines == [
        "s2 --> s0",
        "s1 --> s2 : done",
        "s0 --> s1 : start",
    ]


def test_any_state_line_absent_for_machine_without_sourceless_transition():
    output = to_plantuml(_first_machine(SAMPLE_ST))
    assert 'state "(any state)" as ANY' not in output


def test_any_state_line_present_for_sourceless_transition():
    machine = _first_machine(SOURCELESS_ST)
    output = to_plantuml(machine)
    assert any(t.source is None for t in machine.transitions)
    assert 'state "(any state)" as ANY' in output
    assert "ANY --> s0" in output


def test_deferred_machine_emits_comment_line():
    machine = _first_machine(DEFERRED_ST)
    assert machine.deferred
    output = to_plantuml(machine)
    assert (
        "' transitions write the next-state variable; they take effect "
        "on the following scan" in output
    )


# ---------------------------------------------------------------------------
# guard sanitization
# ---------------------------------------------------------------------------


def test_guard_with_newline_quote_and_colon_comes_out_sanitized():
    machine = _first_machine(SAMPLE_ST)
    machine.transitions[0].guard = 'start\nx"y:z'
    output = to_plantuml(machine)
    assert "s0 --> s1 : start x y z" in output
    assert '"y"' not in output
    assert "x:z" not in output


def test_guard_longer_than_60_is_truncated_with_ellipsis():
    machine = _first_machine(SAMPLE_ST)
    machine.transitions[0].guard = "a" * 80
    output = to_plantuml(machine)
    assert "s0 --> s1 : {0}...".format("a" * 60) in output
    assert "s0 --> s1 : {0}".format("a" * 80) not in output


# ---------------------------------------------------------------------------
# title
# ---------------------------------------------------------------------------


def test_title_emits_title_line():
    output = to_plantuml(_first_machine(SAMPLE_ST), title="Motor")
    assert "title Motor" in output


def test_no_title_emits_no_title_line():
    lines = to_plantuml(_first_machine(SAMPLE_ST)).splitlines()
    assert not any(line.startswith("title ") for line in lines)
