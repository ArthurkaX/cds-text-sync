"""Golden pinning test for ``cts_shared.st.fsm_layout.build_layout``.

The neighbour tests (``test_codesys_fsm.py``, ``test_fsm_core.py``,
``test_fsm_render.py``) check the *structure* of the layout - one property at a
time ("the rail is a single line", "the chips stand side by side").  None of
them pins the whole geometry, so a refactor could move every coordinate a few
pixels and stay green.  This module captures the complete result of
``build_layout`` - every step, chip and link (points, bars, guard/note
positions, arrows) plus the page extent - as one JSON bundle and compares it
byte-for-byte, which is the safety net the decomposition of ``build_layout``
needs.

The reference lives next to this file in ``golden/fsm_layout.json``.  Refresh
it after a *deliberate* change to the output with::

    UPDATE_FSM_LAYOUT_GOLDEN=1 .venv/bin/python -m pytest \
        tests/unit/test_fsm_layout_golden.py -q

The fixtures are built here (no binary blobs): most from small ST state-machine
sources parsed through ``find_machines``, two hand-built machines for the
degenerate cases ST cannot express (no states at all; a transition to a label
outside the CASE).

IronPython note: this file is CPython test code, but it imports a module that
still runs on IronPython 2.7 in CODESYS, so it keeps to the same surface - no
assumptions about anything beyond what ``build_layout`` returns.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "src"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from cts_shared.st.fsm import Machine, State, Transition, find_machines  # noqa: E402
from cts_shared.st.fsm_layout import (  # noqa: E402
    ALWAYS,
    BOTTOM_MARGIN,
    LEFT_MARGIN,
    TOP_MARGIN,
    build_layout,
)


GOLDEN = Path(__file__).parent / "golden" / "fsm_layout.json"


# ---------------------------------------------------------------------------
# Fixtures: small ST state machines, one per branch family of build_layout.
# ---------------------------------------------------------------------------

_LINEAR = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "  B:\n    IF g2 THEN state := C; END_IF\n"
    "  C:\n    state := A;\n"
    "END_CASE\n"
)

_SELF = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "    IF g2 THEN state := A; END_IF\n"
    "  B:\n    IF g3 THEN state := C; END_IF\n"
    "  C:\n    IF g4 THEN state := A; END_IF\n"
    "END_CASE\n"
)

_SKIPS = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "    IF g2 THEN state := D; END_IF\n"
    "  B:\n    IF g3 THEN state := C; END_IF\n"
    "    IF g4 THEN state := E; END_IF\n"
    "  C:\n    IF g5 THEN state := D; END_IF\n"
    "  D:\n    IF g6 THEN state := E; END_IF\n"
    "  E:\n    IF g7 THEN state := A; END_IF\n"
    "END_CASE\n"
)

_ROUTING = (
    "CASE state OF\n"
    "  IDLE:\n    IF xStart THEN state := EXIT; END_IF\n"
    "  EXIT:\n"
    "    IF xLeft THEN state := LEFT;\n"
    "    ELSIF xForward THEN state := FWD;\n"
    "    ELSIF xRight THEN state := RIGHT; END_IF\n"
    "  LEFT:\n    IF xDone THEN state := DONE; END_IF\n"
    "  FWD:\n    IF xDone THEN state := DONE; END_IF\n"
    "  RIGHT:\n    IF xDone THEN state := DONE; END_IF\n"
    "  DONE:\n    IF xReset THEN state := IDLE; END_IF\n"
    "END_CASE\n"
)

_BRANCHING = (
    "CASE state OF\n"
    "  OFF:\n    IF xRun THEN state := RED; END_IF\n"
    "  RED:\n"
    "    IF NOT xRun THEN state := OFF;\n"
    "    ELSIF xNight THEN state := FLASH;\n"
    "    ELSIF xTimer THEN state := REDY; END_IF\n"
    "  FLASH:\n"
    "    IF NOT xRun THEN state := OFF;\n"
    "    ELSIF NOT xNight THEN state := RED; END_IF\n"
    "  REDY:\n    IF xTimer THEN state := GREEN; END_IF\n"
    "  GREEN:\n"
    "    IF NOT xRun THEN state := OFF;\n"
    "    ELSIF xNight THEN state := FLASH;\n"
    "    ELSIF xTimer THEN state := YELLOW; END_IF\n"
    "  YELLOW:\n    IF xTimer THEN state := RED; END_IF\n"
    "END_CASE\n"
)

# A dotted selector plus priority transitions written outside the CASE: the
# shared enum prefix is stripped, an "any" box is drawn and each priority
# target gets a chip.
_PREFIXED = (
    "IF stop THEN\n    state := ENUM_S.E_STOPPED;\nEND_IF\n"
    "IF alarm THEN\n    state := ENUM_S.WARN;\nEND_IF\n"
    "CASE state OF\n"
    "  ENUM_S.OFF:\n    IF start THEN state := ENUM_S.WARN; END_IF\n"
    "  ENUM_S.WARN:\n    IF timer THEN state := ENUM_S.RUN; END_IF\n"
    "  ENUM_S.RUN:\n"
    "    IF fault THEN state := ENUM_S.SAVE; END_IF\n"
    "    IF done THEN state := ENUM_S.CALL; END_IF\n"
    "  ENUM_S.SAVE:\n    IF reset THEN state := ENUM_S.OFF; END_IF\n"
    "  ENUM_S.CALL:\n    IF ack THEN state := ENUM_S.RUN; END_IF\n"
    "  ENUM_S.E_STOPPED:\n    IF release THEN state := ENUM_S.OFF; END_IF\n"
    "END_CASE\n"
)

# The last step of a one-column chain whose only two ways out are backward
# hops - both become connectors, so the fan is nothing but jumps and the first
# of them has to draw the shared trunk.
_FAN_JUMPS = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "  B:\n    IF g2 THEN state := C; END_IF\n"
    "  C:\n"
    "    IF g3 THEN state := A; END_IF\n"
    "    IF g4 THEN state := B; END_IF\n"
    "END_CASE\n"
)

# A guard longer than GUARD_CHARS (40), so clip_guard truncates it, and a
# short one so both the "=1" and the verbatim forms are pinned.
_LONG_GUARD = (
    "CASE state OF\n"
    "  A:\n"
    "    IF this_guard_name_is_far_longer_than_the_limit THEN"
    " state := B; END_IF\n"
    "  B:\n    IF g2 THEN state := A; END_IF\n"
    "END_CASE\n"
)

# Two columns where only the first carries a forward skip: the side-link loop
# has to walk the column with no sides too.
_SIDES_MULTICOL = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "    IF g2 THEN state := P; END_IF\n"
    "  B:\n    IF g3 THEN state := C; END_IF\n"
    "    IF g4 THEN state := D; END_IF\n"
    "  C:\n    IF g5 THEN state := D; END_IF\n"
    "  D:\n    IF g6 THEN state := A; END_IF\n"
    "  P:\n    IF g7 THEN state := A; END_IF\n"
    "END_CASE\n"
)

# Two routes rejoining at T: B arrives off its own divergence (so its merge
# link is slotted onto a fan branch), P arrives on the column axis.
_MERGE_FAN = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "    IF g2 THEN state := P; END_IF\n"
    "  B:\n    IF g3 THEN state := T; END_IF\n"
    "    IF g4 THEN state := Q; END_IF\n"
    "  P:\n    IF g5 THEN state := T; END_IF\n"
    "  T:\n    IF g6 THEN state := A; END_IF\n"
    "  Q:\n    IF g7 THEN state := A; END_IF\n"
    "END_CASE\n"
)

# Three routes into T but from only two columns, one of them twice (IF/ELSIF to
# the same target): the branches do not stand on their own x, so the group is
# NOT a convergence and the routes stay ordinary links.
_MERGE_REJECT = (
    "CASE state OF\n"
    "  A:\n    IF g1 THEN state := B; END_IF\n"
    "    IF g2 THEN state := P; END_IF\n"
    "  B:\n    IF a THEN state := T;\n    ELSIF b THEN state := T; END_IF\n"
    "  P:\n    IF c THEN state := T; END_IF\n"
    "  T:\n    IF d THEN state := A; END_IF\n"
    "END_CASE\n"
)


def _machine(source):
    machines = [m for m in find_machines(source) if m.is_fsm]
    assert len(machines) == 1, "fixture must yield exactly one FSM"
    return machines[0]


def _empty_machine():
    """No states at all: ST cannot express this, build_layout must bail out."""
    return Machine("state", 0, 0, 0)


def _outside_target_machine():
    """A transition to a label that is not a CASE branch: it is counted as
    *dropped* rather than drawn.  ``find_machines`` never produces this, so it
    is hand-built."""
    machine = Machine("state", 0, 0, 0)
    machine.states = [State("A", ["A"], 0, 1, 0), State("B", ["B"], 1, 2, 1)]
    machine.transitions = [
        Transition("A", "B", "g1", 0, "state", False, 0, 1),
        Transition("A", "GONE", "g2", 1, "state", False, 1, 2),
    ]
    return machine


_FIXTURES = {
    "empty": _empty_machine,
    "linear": lambda: _machine(_LINEAR),
    "self": lambda: _machine(_SELF),
    "skips": lambda: _machine(_SKIPS),
    "routing": lambda: _machine(_ROUTING),
    "branching": lambda: _machine(_BRANCHING),
    "prefixed": lambda: _machine(_PREFIXED),
    "fan_jumps": lambda: _machine(_FAN_JUMPS),
    "long_guard": lambda: _machine(_LONG_GUARD),
    "sides_multicol": lambda: _machine(_SIDES_MULTICOL),
    "merge_fan": lambda: _machine(_MERGE_FAN),
    "merge_reject": lambda: _machine(_MERGE_REJECT),
    "dropped": _outside_target_machine,
}


# ---------------------------------------------------------------------------
# Deterministic serialization of the whole Layout.
# ---------------------------------------------------------------------------


def _transition(t):
    if t is None:
        return None
    return {
        "source": t.source,
        "target": t.target,
        "guard": t.guard,
        "offset": t.offset,
    }


def _step(step):
    return {
        "number": step.number,
        "label": step.label,
        "full_label": step.full_label,
        "x": step.x,
        "y": step.y,
        "w": step.w,
        "h": step.h,
        "initial": step.initial,
        "priority": step.priority,
        "col": step.col,
        "row": step.row,
        "inbound": list(step.inbound),
        "inbound_x": step.inbound_x,
    }


def _chip(chip):
    return {
        "number": chip.number,
        "label": chip.label,
        "x": chip.x,
        "y": chip.y,
        "w": chip.w,
        "h": chip.h,
    }


def _link(link):
    return {
        "kind": link.kind,
        "transition": _transition(link.transition),
        "points": [list(point) for point in link.points],
        "bar": list(link.bar) if link.bar is not None else None,
        "guard_text": link.guard_text,
        "guard_at": list(link.guard_at) if link.guard_at is not None else None,
        "guard_w": link.guard_w,
        "arrow": list(link.arrow) if link.arrow is not None else None,
        "note_text": link.note_text,
        "note_at": list(link.note_at) if link.note_at is not None else None,
        "note_w": link.note_w,
    }


def _serialize(layout):
    """Render a Layout as plain JSON types, in a fixed key order."""
    return {
        "columns": layout.columns,
        "width": layout.width,
        "height": layout.height,
        "prefix": layout.prefix,
        "dropped": layout.dropped,
        "any_box": list(layout.any_box) if layout.any_box is not None else None,
        "chips": [_chip(chip) for chip in layout.chips],
        "steps": [_step(step) for step in layout.steps],
        "links": [_link(link) for link in layout.links],
    }


def _collect():
    return dict(
        (name, _serialize(build_layout(builder())))
        for name, builder in _FIXTURES.items()
    )


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The golden itself.
# ---------------------------------------------------------------------------


def test_build_layout_matches_the_golden_bundle():
    actual = _collect()
    if os.environ.get("UPDATE_FSM_LAYOUT_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps({"fixtures": actual}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pytest.skip("golden refreshed; re-run without UPDATE_FSM_LAYOUT_GOLDEN")
    expected = _load_golden()["fixtures"]
    assert set(actual) == set(expected), "fixture set changed"
    for name in sorted(expected):
        assert actual[name] == expected[name], name


def test_the_golden_covers_every_link_kind_and_marker():
    """Guard against a fixture silently losing a branch family."""
    golden = _load_golden()["fixtures"]
    kinds = set()
    for bundle in golden.values():
        for link in bundle["links"]:
            kinds.add(link["kind"])
    assert kinds == {"chain", "fork", "self", "side", "jump", "merge", "global"}

    prefixed = golden["prefixed"]
    assert prefixed["any_box"] is not None
    assert [chip["label"] for chip in prefixed["chips"]] == ["E_STOPPED", "WARN"]
    assert prefixed["prefix"] == "ENUM_S."

    assert golden["dropped"]["dropped"] == 1
    empty = golden["empty"]
    assert empty["steps"] == [] and empty["links"] == []
    assert empty["width"] == LEFT_MARGIN * 2
    assert empty["height"] == TOP_MARGIN + BOTTOM_MARGIN

    # The long guard is truncated to the limit and the empty one becomes "=1".
    long_guards = [link["guard_text"] for link in golden["long_guard"]["links"]]
    assert any(text.endswith("...") for text in long_guards)
    linear = golden["linear"]
    assert any(link["guard_text"] == ALWAYS for link in linear["links"])


def test_build_layout_is_deterministic():
    """Two runs over fresh machines serialise identically."""
    first = _collect()
    second = _collect()
    assert first == second
    # And the serialised form survives a json round-trip.
    assert json.loads(json.dumps(first)) == first


def test_layout_helpers_agree_with_the_serialised_steps():
    layout = build_layout(_machine(_PREFIXED))
    bundle = _serialize(layout)
    by_id = dict((step["full_label"], step) for step in bundle["steps"])
    for full_label, step in by_id.items():
        found = layout.step_for(full_label)
        assert found is not None
        assert _step(found) == step
        assert layout.step_at(found.x + 1, found.y + 1) is found
        assert layout.step_at(found.x - 1, found.y - 1) is None
    assert layout.has_any is True


def test_explicit_measure_callables_are_used():
    """A caller-supplied measure/guard_measure overrides the defaults."""
    called = {"measure": 0, "guard": 0}

    def measure(text):
        called["measure"] += 1
        return len(text) * 7

    def guard_measure(text):
        called["guard"] += 1
        return len(text) * 5

    build_layout(_machine(_LINEAR), measure=measure, guard_measure=guard_measure)
    assert called["measure"] > 0
    assert called["guard"] > 0
    # Passing only measure makes it the guard measure too (documented default).
    only_measure = {"n": 0}

    def measure2(text):
        only_measure["n"] += 1
        return len(text) * 7

    build_layout(_machine(_LINEAR), measure=measure2)
    assert only_measure["n"] > 1


def test_a_too_wide_step_widens_the_page_not_the_other_columns():
    """step_w follows the widest stripped label, and the page grows with it."""
    narrow = build_layout(_machine(_LINEAR))
    wide_source = (
        "CASE state OF\n"
        "  A_VERY_LONG_STATE_NAME_THAT_EXCEEDS_THE_MINIMUM_WIDTH:\n"
        "    IF g1 THEN state := B; END_IF\n"
        "  B:\n    IF g2 THEN state := A_VERY_LONG_STATE_NAME_THAT_EXCEEDS_THE_MINIMUM_WIDTH; END_IF\n"
        "END_CASE\n"
    )
    wide = build_layout(_machine(wide_source))
    assert wide.steps[0].w > narrow.steps[0].w
    assert wide.width > narrow.width
