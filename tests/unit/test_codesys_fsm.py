"""Regression tests for the shared FSM layout and picker helpers.

The old IronPython/WinForms ``codesys_fsm_*`` host modules are gone (spec.md
section 12).  What survives here tests the shared ``cts_shared.st.fsm_layout``
geometry - the same module the CPython ``cds_text_sync.fsm.render`` consumes -
and the ``ide_picker_common`` helper that the fmt picker still uses.  Anything
that exercised the deleted operation/picker/UI modules was removed with them.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "src"
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
for path in (str(SHARED), str(BRIDGE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import ide_picker_common as picker_common  # noqa: E402
from cts_shared.st import fsm_layout  # noqa: E402


def _sample_machine():
    from cts_shared.st.fsm import find_machines

    source = (
        "CASE state OF\n"
        "  IDLE:\n"
        "    next_state := RUN;\n"
        "  RUN:\n"
        "    next_state := DONE;\n"
        "  DONE:\n"
        "    next_state := IDLE;\n"
        "END_CASE;\n"
    )
    machines = [m for m in find_machines(source) if m.is_fsm]
    assert len(machines) == 1
    return machines[0]


def _prefixed_machine():
    """A machine shaped like real CODESYS code: a dotted enum selector, a
    priority transition written outside the CASE, and a return link that
    jumps back up the page."""
    from cts_shared.st.fsm import find_machines

    source = (
        "IF stop THEN\n"
        "    state := ENUM_SORTER_STATES.E_STOPPED;\n"
        "END_IF\n"
        "IF alarm THEN\n"
        "    state := ENUM_SORTER_STATES.WARNING_SIGNAL;\n"
        "END_IF\n"
        "CASE state OF\n"
        "  ENUM_SORTER_STATES.TURNED_OFF:\n"
        "    IF start THEN state := ENUM_SORTER_STATES.WARNING_SIGNAL; END_IF\n"
        "  ENUM_SORTER_STATES.WARNING_SIGNAL:\n"
        "    IF timer.Q AND NOT blocked_by_operator_panel THEN"
        " state := ENUM_SORTER_STATES.RUN; END_IF\n"
        "  ENUM_SORTER_STATES.RUN:\n"
        "    IF fault THEN state := ENUM_SORTER_STATES.E_SAVING; END_IF\n"
        "    IF done THEN state := ENUM_SORTER_STATES.CALL; END_IF\n"
        "  ENUM_SORTER_STATES.E_SAVING:\n"
        "    IF reset THEN state := ENUM_SORTER_STATES.TURNED_OFF; END_IF\n"
        "  ENUM_SORTER_STATES.CALL:\n"
        "    IF ack THEN state := ENUM_SORTER_STATES.RUN; END_IF\n"
        "  ENUM_SORTER_STATES.E_STOPPED:\n"
        "    IF release THEN state := ENUM_SORTER_STATES.TURNED_OFF; END_IF\n"
        "END_CASE\n"
    )
    machines = [m for m in find_machines(source) if m.is_fsm]
    assert len(machines) == 1
    return machines[0]


def _returns_machine():
    """A single chain whose steps keep falling back to earlier ones, so
    several side links have to share the gutter without colliding."""
    from cts_shared.st.fsm import find_machines

    source = (
        "CASE state OF\n"
        "  A:\n    IF g1 THEN state := B; END_IF\n"
        "  B:\n    IF g2 THEN state := C; END_IF\n"
        "    IF g3 THEN state := A; END_IF\n"
        "  C:\n    IF g4 THEN state := D; END_IF\n"
        "    IF g5 THEN state := A; END_IF\n"
        "  D:\n    IF g6 THEN state := B; END_IF\n"
        "END_CASE\n"
    )
    machines = [m for m in find_machines(source) if m.is_fsm]
    assert len(machines) == 1
    return machines[0]


def _merge_machine():
    """Three routes chosen at one step and rejoining at the next - the shape
    of a sorter that weighs a part, sends it left/forward/right and delivers
    all three the same way."""
    from cts_shared.st.fsm import find_machines

    source = (
        "CASE state OF\n"
        "  IDLE:\n    IF go THEN state := PICK; END_IF\n"
        "  PICK:\n"
        "    IF a THEN state := LEFT; END_IF\n"
        "    IF b THEN state := MID; END_IF\n"
        "    IF c THEN state := RIGHT; END_IF\n"
        "  LEFT:\n    IF d1 THEN state := DONE; END_IF\n"
        "  MID:\n    IF d2 THEN state := DONE; END_IF\n"
        "  RIGHT:\n    IF d3 THEN state := DONE; END_IF\n"
        "  DONE:\n    IF rst THEN state := IDLE; END_IF\n"
        "END_CASE\n"
    )
    machines = [m for m in find_machines(source) if m.is_fsm]
    assert len(machines) == 1
    return machines[0]


def test_pending_indexes_skips_already_analyzed_blocks():
    items = [
        {"analysis": None},
        {"analysis": "done"},
        {"analysis": None},
        {"analysis": "error"},
    ]
    assert picker_common.pending_indexes(items, [0, 1, 2, 3]) == [0, 2]
    # Only the filtered subset is ever swept.
    assert picker_common.pending_indexes(items, [1, 3]) == []
    assert picker_common.pending_indexes(items, []) == []


def test_the_shared_enum_prefix_is_named_once_and_stripped_everywhere():
    layout = fsm_layout.build_layout(_prefixed_machine())
    assert layout.prefix == "ENUM_SORTER_STATES."
    labels = [step.label for step in layout.steps]
    assert "TURNED_OFF" in labels
    assert not any("." in label for label in labels)
    # The full label survives for hit testing and selection.
    assert layout.step_for("ENUM_SORTER_STATES.RUN") is not None


def test_a_state_entered_only_from_outside_the_case_is_not_the_initial_step():
    # E_STOPPED has no incoming transition inside the CASE, but it is
    # reached by `IF stop` - it is a reaction state, not the entry point.
    layout = fsm_layout.build_layout(_prefixed_machine())
    assert layout.steps[0].label == "TURNED_OFF"
    assert layout.steps[0].initial is True
    assert [s.label for s in layout.steps if s.initial] == ["TURNED_OFF"]
    assert layout.steps[0].number == 1


def test_a_priority_transition_shows_the_block_it_lands_in():
    layout = fsm_layout.build_layout(_prefixed_machine())
    assert layout.has_any is True
    globals_ = [link for link in layout.links if link.kind == "global"]
    assert len(globals_) == 2
    for link in globals_:
        assert link.transition.source is None
        # One stem out of the "any" box, then the rail, then the drop.
        assert link.points[0][0] == link.points[1][0]
        assert link.bar[2] == "h"
        assert link.arrow[2] == "down"
    # Each row ends in a chip naming the target, so the reader never has to
    # match a number against a step somewhere else on the page.
    assert [chip.label for chip in layout.chips] == ["E_STOPPED", "WARNING_SIGNAL"]
    by_label = dict((step.label, step.number) for step in layout.steps)
    for chip in layout.chips:
        assert chip.number == by_label[chip.label]
    # No priority transition leaks into the ordinary links.
    for link in layout.links:
        if link.kind != "global":
            assert link.transition.source is not None
    flagged = sorted(s.label for s in layout.steps if s.priority)
    assert flagged == ["E_STOPPED", "WARNING_SIGNAL"]


def test_the_priority_block_is_a_divergence_rather_than_a_cascade():
    # It used to walk down the stem and turn right into each target, one row
    # per transition. GRAFCET draws this as a divergence: down, across, down.
    layout = fsm_layout.build_layout(_prefixed_machine())
    globals_ = [link for link in layout.links if link.kind == "global"]
    any_x, any_y, any_w, any_h = layout.any_box

    rails = set()
    drops = []
    for link in globals_:
        (stem_x, stem_y), (rail_x, rail_y), (turn_x, turn_y), (drop_x, drop_y) = link.points
        assert stem_x == rail_x == any_x + any_w // 2, "the stem leaves the any box"
        assert stem_y == any_y + any_h
        assert turn_y == rail_y, "the middle run is horizontal"
        assert turn_x == drop_x and drop_y > turn_y, "then it drops into the target"
        rails.add(rail_y)
        drops.append(drop_x)
    assert len(rails) == 1, "every branch hangs off one rail"
    assert drops == sorted(drops), "branches read left to right, in source order"

    # The chips stand side by side under the rail, not stacked down the page.
    tops = set(chip.y for chip in layout.chips)
    assert len(tops) == 1
    ordered = sorted(layout.chips, key=lambda chip: chip.x)
    for left, right in zip(ordered, ordered[1:]):
        assert right.x > left.right, "chips must not overlap"
    for chip, drop_x in zip(layout.chips, drops):
        assert chip.x < drop_x < chip.right, "the drop lands on its own chip"
    # The box is centred over the rail, so the stem never doubles back.
    assert layout.width >= max(chip.right for chip in layout.chips)


def test_a_single_priority_transition_draws_as_one_straight_drop():
    from cts_shared.st.fsm import find_machines

    source = (
        "IF stop THEN\n"
        "  state := IDLE;\n"
        "END_IF\n"
        "CASE state OF\n"
        "  IDLE:\n"
        "    IF start THEN state := RUN; END_IF\n"
        "  RUN:\n"
        "    IF done THEN state := IDLE; END_IF\n"
        "END_CASE\n"
    )
    machine = [m for m in find_machines(source) if m.is_fsm][0]
    layout = fsm_layout.build_layout(machine)
    globals_ = [link for link in layout.links if link.kind == "global"]
    assert len(globals_) == 1
    xs = set(x for x, _y in globals_[0].points)
    assert len(xs) == 1, "with one branch there is nothing to fan out to"


def test_consecutive_steps_are_joined_by_a_straight_vertical_link():
    layout = fsm_layout.build_layout(_sample_machine())
    assert layout.columns == 1
    chain = [link for link in layout.links if link.kind == "chain"]
    assert len(chain) == 2
    for link in chain:
        (x0, y0), (x1, y1) = link.points
        assert x0 == x1            # the chain runs straight down
        assert y1 > y0
        assert link.bar[2] == "h"  # the bar lies across the link
        assert link.arrow is None  # top-to-bottom flow needs no arrowhead
    # The link closing the loop back to the top is a side link instead.
    sides = [link for link in layout.links if link.kind == "side"]
    assert len(sides) == 1
    assert sides[0].arrow[2] == "right"


def test_side_links_run_in_the_left_gutter_and_never_share_a_lane():
    # A link jumping UP the page arrives with its endpoints reversed; if
    # that is not normalised the lane assignment silently overlaps them.
    layout = fsm_layout.build_layout(_returns_machine())
    sides = [link for link in layout.links if link.kind == "side"]
    assert len(sides) == 3
    leftmost_box = min(step.x for step in layout.steps)
    runs = []
    for link in sides:
        ys = [y for _, y in link.points]
        lane_x = min(x for x, _ in link.points)
        # The gutter is to the LEFT: a lane on the right would have to
        # cross the next column's boxes.
        assert lane_x < leftmost_box
        runs.append((lane_x, min(ys), max(ys)))
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            ax, a0, a1 = runs[i]
            bx, b0, b1 = runs[j]
            if ax != bx:
                continue
            assert a1 < b0 or b1 < a0, (
                "lane {0} carries overlapping links".format(ax)
            )


def test_an_empty_guard_reads_as_unconditional_and_long_ones_are_clipped():
    assert fsm_layout.clip_guard("") == "=1"
    assert fsm_layout.clip_guard("   ") == "=1"
    assert fsm_layout.clip_guard("a AND\n  b") == "a AND b"
    clipped = fsm_layout.clip_guard("x" * 80)
    assert len(clipped) == fsm_layout.GUARD_CHARS
    assert clipped.endswith("...")


def test_clicks_land_on_steps_links_and_their_receptivities():
    layout = fsm_layout.build_layout(_sample_machine())
    step = layout.steps[1]
    assert layout.step_at(step.cx, step.cy) is step
    assert layout.step_at(step.cx, step.y - 200) is None

    chain = [link for link in layout.links if link.kind == "chain"][0]
    (x0, y0), (x1, y1) = chain.points
    assert layout.link_at(x0, (y0 + y1) // 2) is chain
    # The receptivity beside the bar is part of the transition's hit area.
    gx, gy = chain.guard_at
    assert layout.link_at(gx + 2, gy + 2) is chain
    assert layout.link_at(x0 - 500, y0) is None


def test_every_coordinate_stays_an_int_when_measurement_returns_floats():
    # GDI+ measures text as a float, but a CLR Point takes Int32 only.
    layout = fsm_layout.build_layout(
        _prefixed_machine(),
        measure=lambda text: len(text) * 7.3,
        guard_measure=lambda text: len(text) * 6.1,
    )
    values = [layout.width, layout.height]
    for step in layout.steps:
        values += [step.x, step.y, step.w, step.h]
    for link in layout.links:
        for x, y in link.points:
            values += [x, y]
        values += [link.guard_w, link.note_w]
        for pair in (link.bar, link.guard_at, link.note_at, link.arrow):
            if pair is not None:
                values += [pair[0], pair[1]]
    assert all(isinstance(value, int) for value in values)


def test_no_transition_is_silently_dropped_from_the_diagram():
    machine = _prefixed_machine()
    layout = fsm_layout.build_layout(machine)
    assert layout.dropped == 0
    assert len(layout.links) == len(machine.transitions)
    drawn = set(id(link.transition) for link in layout.links)
    assert drawn == set(id(t) for t in machine.transitions)


def test_a_side_sequence_gets_its_own_column():
    # A CASE is not one sequence: the branch at RUN starts a second chain,
    # and reading two short columns beats one tall one full of long links.
    layout = fsm_layout.build_layout(_prefixed_machine())
    assert layout.columns >= 2
    columns = dict((step.label, step.col) for step in layout.steps)
    assert columns["CALL"] != columns["RUN"]
    forks = [link for link in layout.links if link.kind == "fork"]
    assert len(forks) == 1
    fork = forks[0]
    # An ordinary link, not a divergence bar: exactly one state is active,
    # so a choice cannot mean two branches running at once.
    assert len(fork.points) == 4
    assert fork.arrow is None
    assert fork.bar[2] == "h"
    source = layout.step_for(fork.transition.source)
    target = layout.step_for(fork.transition.target)
    assert fork.points[0][0] == source.cx
    assert fork.points[-1][0] == target.cx
    assert fork.bar[0] == target.cx


def test_a_distant_jump_becomes_a_connector_instead_of_a_line():
    layout = fsm_layout.build_layout(_prefixed_machine())
    jumps = [link for link in layout.links if link.kind == "jump"]
    assert len(jumps) == 2
    for link in jumps:
        target = layout.step_for(link.transition.target)
        source = layout.step_for(link.transition.source)
        # The connector stops just below its source; it never reaches
        # across the page to the block it names.
        assert len(link.points) == 4
        assert max(py for _, py in link.points) <= source.bottom + 60
        # Down, right, back up: the same hook whichever way the target lies,
        # so the arrowhead reads as "go to", not as a direction on the page.
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = link.points
        assert x0 == x1 == source.cx
        assert y1 > y0
        assert x2 == x3 > x1
        assert y2 == y1 and y3 < y2
        assert link.arrow == (x3, y3, "up")
        assert link.note_text == "{0}  {1}".format(target.number, target.label)
        # The target says who arrives here, since nothing points at it.
        assert source.number in target.inbound


def test_receptivity_text_never_runs_over_a_block():
    # The receptivity is drawn to the right of its bar, so the column pitch
    # has to reserve room for it or it lands on the neighbouring column.
    layout = fsm_layout.build_layout(
        _prefixed_machine(),
        measure=lambda text: len(text) * 7,
        guard_measure=lambda text: len(text) * 6,
    )
    boxes = [(s.x, s.y, s.x + s.w, s.y + s.h) for s in layout.steps]
    boxes += [(c.x, c.y, c.x + c.w, c.y + c.h) for c in layout.chips]
    for link in layout.links:
        gx, gy = link.guard_at
        gx2 = gx + link.guard_w
        gy2 = gy + fsm_layout.TEXT_H
        for bx, by, bx2, by2 in boxes:
            overlaps = gx < bx2 and bx < gx2 and gy < by2 and by < gy2
            assert not overlaps, (
                "receptivity {0!r} lands on a block".format(link.guard_text)
            )


def test_branches_that_rejoin_are_drawn_as_one_convergence():
    # Three routes leave PICK and all end in DONE. Drawn as ordinary links
    # that would be one sequence plus two connectors, and the reader would
    # have to notice the captions to see that the routes rejoin at all.
    layout = fsm_layout.build_layout(_merge_machine())
    merges = [link for link in layout.links if link.kind == "merge"]
    assert len(merges) == 3
    target = layout.step_for(merges[0].transition.target)
    assert target.label == "DONE"

    rails = set()
    for link in merges:
        source = layout.step_for(link.transition.source)
        assert layout.step_for(link.transition.target) is target
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = link.points
        assert x0 == x1 == source.cx, "the branch leaves its own step"
        assert y0 == source.bottom and y1 > y0
        assert y2 == y1, "the middle run is the shared rail"
        assert x2 == x3 == target.cx and y3 == target.y, "one stem enters"
        assert y3 > y2
        # Its own receptivity, above the rail, beside its own bar.
        assert link.bar[0] == source.cx and link.bar[2] == "h"
        assert link.bar[1] < y1
        assert link.arrow is None, "flow runs top-to-bottom"
        rails.add(y1)
    assert len(rails) == 1, "every branch meets on one rail"

    # The convergence replaces the connectors: nothing arrives at DONE by
    # caption any more, so the step needs no "who reaches me" marker.
    assert target.inbound == []
    for link in layout.links:
        if link.transition.target == target.full_label:
            assert link.kind == "merge"

    guards = sorted(link.guard_text for link in merges)
    assert guards == ["a AND d1", "b AND d2", "c AND d3"] or len(set(guards)) == 3
