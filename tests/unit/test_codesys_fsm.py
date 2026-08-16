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
    several backward hops have to become connectors without colliding."""
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


def _skips_machine():
    """A single chain whose steps skip FORWARD over the ones below them, so
    several side links have to share the gutter without colliding."""
    from cts_shared.st.fsm import find_machines

    source = (
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


def _branching_machine():
    """A traffic light: two steps have three outgoing transitions each, so
    their bars, receptivities and connector captions have to share the gap
    below the step without landing on one another."""
    from cts_shared.st.fsm import find_machines

    source = (
        "CASE state OF\n"
        "  TRAFFIC_OFF:\n    IF xRun THEN state := TRAFFIC_RED; END_IF\n"
        "  TRAFFIC_RED:\n"
        "    IF NOT xRun THEN state := TRAFFIC_OFF;\n"
        "    ELSIF xNightMode THEN state := TRAFFIC_FLASHING;\n"
        "    ELSIF xTimerDone THEN state := TRAFFIC_RED_YELLOW; END_IF\n"
        "  TRAFFIC_FLASHING:\n"
        "    IF NOT xRun THEN state := TRAFFIC_OFF;\n"
        "    ELSIF NOT xNightMode THEN state := TRAFFIC_RED; END_IF\n"
        "  TRAFFIC_RED_YELLOW:\n"
        "    IF xTimerDone THEN state := TRAFFIC_GREEN; END_IF\n"
        "  TRAFFIC_GREEN:\n"
        "    IF NOT xRun THEN state := TRAFFIC_OFF;\n"
        "    ELSIF xNightMode THEN state := TRAFFIC_FLASHING;\n"
        "    ELSIF xTimerDone THEN state := TRAFFIC_YELLOW; END_IF\n"
        "  TRAFFIC_YELLOW:\n"
        "    IF xTimerDone THEN state := TRAFFIC_RED; END_IF\n"
        "END_CASE\n"
    )
    machines = [m for m in find_machines(source) if m.is_fsm]
    assert len(machines) == 1
    return machines[0]


def _routing_machine():
    """A three-way route: one step whose branches each start a column of their
    own and then rejoin.  Both a divergence and the convergence under it, so
    each rail has to be the only horizontal of its kind on its own row."""
    from cts_shared.st.fsm import find_machines

    source = (
        "CASE state OF\n"
        "  STATE_IDLE:\n"
        "    IF xStart THEN state := STATE_EXIT; END_IF\n"
        "  STATE_EXIT:\n"
        "    IF xLeft THEN state := STATE_ROUTE_LEFT;\n"
        "    ELSIF xForward THEN state := STATE_ROUTE_FORWARD;\n"
        "    ELSIF xRight THEN state := STATE_ROUTE_RIGHT; END_IF\n"
        "  STATE_ROUTE_LEFT:\n"
        "    IF xDone THEN state := STATE_DONE; END_IF\n"
        "  STATE_ROUTE_FORWARD:\n"
        "    IF xDone THEN state := STATE_DONE; END_IF\n"
        "  STATE_ROUTE_RIGHT:\n"
        "    IF xDone THEN state := STATE_DONE; END_IF\n"
        "  STATE_DONE:\n"
        "    IF xReset THEN state := STATE_IDLE; END_IF\n"
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
    # The link closing the loop back to the top is a connector instead: a
    # line drawn back up the page drags the eye against the flow.
    jumps = [link for link in layout.links if link.kind == "jump"]
    assert len(jumps) == 1
    assert jumps[0].arrow[2] == "up"
    target = layout.step_for(jumps[0].transition.target)
    assert target.inbound == [3]


def test_side_links_run_in_the_left_gutter_and_never_share_a_lane():
    # Only a forward skip still runs in a lane; two of them whose spans
    # overlap must not be handed the same one.
    layout = fsm_layout.build_layout(_skips_machine())
    sides = [link for link in layout.links if link.kind == "side"]
    assert len(sides) == 2
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
    # A branch of its step's divergence that lands in another column: it
    # leaves the trunk, runs along the rail and drops straight into its
    # target, carrying its bar directly above the step it enters. Given a
    # slot near the source it turned sideways a second time, and those runs
    # overlapped into a second horizontal line beside the rail.
    assert fork.arrow is None
    assert fork.bar[2] == "h"
    source = layout.step_for(fork.transition.source)
    target = layout.step_for(fork.transition.target)
    assert len(fork.points) == 4
    assert fork.points[0][0] == source.cx
    assert fork.points[-1][0] == target.cx
    assert fork.bar[0] == target.cx
    assert fork.guard_at[0] > fork.bar[0], "the receptivity stays with its bar"


def test_a_distant_jump_becomes_a_connector_instead_of_a_line():
    layout = fsm_layout.build_layout(_prefixed_machine())
    jumps = [link for link in layout.links if link.kind == "jump"]
    assert len(jumps) == 3
    for link in jumps:
        target = layout.step_for(link.transition.target)
        source = layout.step_for(link.transition.source)
        # The connector stops just below its source; it never reaches
        # across the page to the block it names.
        assert len(link.points) == 4
        # The hook lives in the gap under its own step: it never runs down
        # into the row below, however many transitions share that gap.
        below = [s.y for s in layout.steps if s.y > source.bottom]
        if below:
            assert max(py for _, py in link.points) < min(below)
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


def test_every_transition_leaving_a_step_gets_its_own_branch():
    # They all used to be drawn one fixed offset below the step, in a heap,
    # and then stacked down one stem - a row each, which reads as
    # transitions in series rather than as a choice between them.
    layout = fsm_layout.build_layout(_branching_machine())
    groups = {}
    for link in layout.links:
        if link.transition.source is None:
            continue
        groups.setdefault(link.transition.source, []).append(link)

    branching = 0
    for links in groups.values():
        if len(links) < 2:
            continue
        if len(links) >= 3:
            branching += 1
        bars = sorted((link.transition.offset, link.bar[0], link.bar[1])
                      for link in links)
        bar_x = [x for _, x, _ in bars]
        bar_y = [y for _, _, y in bars]
        assert len(set(bar_y)) == 1, "one divergence, so one rail"
        assert len(set(bar_x)) == len(bar_x), "branches must not share an x"
        assert bar_x == sorted(bar_x), (
            "branches read in the order the IF/ELSIF chain does"
        )
        rects = []
        for link in links:
            gx, gy = link.guard_at
            rects.append((gx, gy, gx + link.guard_w, gy + fsm_layout.TEXT_H))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax, ay, ax2, ay2 = rects[i]
                bx, by, bx2, by2 = rects[j]
                assert not (ax < bx2 and bx < ax2 and ay < by2 and by < ay2), (
                    "receptivities in the gap overlap"
                )
    assert branching >= 1, "the machine must actually branch"


def test_a_divergence_hangs_off_one_trunk_below_its_step():
    # Every branch starts on the rail so the trunk keeps the ordinary link
    # colour; with nothing but connectors leaving a step there was no branch
    # left to draw the trunk, and the rail floated free under the box.
    machines = (
        ("branching", _branching_machine()),
        ("skips", _skips_machine()),
        ("merge", _merge_machine()),
    )
    for name, machine in machines:
        layout = fsm_layout.build_layout(machine)
        groups = {}
        for link in layout.links:
            if link.transition.source is None:
                continue
            groups.setdefault(link.transition.source, []).append(link)
        for label, links in groups.items():
            if len(links) < 2:
                continue
            step = layout.step_for(label)
            rail_y = step.bottom + fsm_layout.FAN_RAIL
            joined = False
            for link in links:
                for (ax, ay), (bx, by) in zip(link.points, link.points[1:]):
                    if (ax == bx == step.cx
                            and min(ay, by) <= step.bottom
                            and max(ay, by) >= rail_y):
                        joined = True
            assert joined, (
                "the divergence at {0} in {1} floats free of its step"
                .format(label, name)
            )


def test_a_divergence_draws_one_rail_and_drops_each_branch_on_its_own_axis():
    # A fork used to take a slot beside its source and then turn sideways a
    # second time to reach its column, so a three-way route drew the rail plus
    # a second horizontal made of the overlapping turns, with all three
    # receptivities bunched at the left instead of over the steps they name.
    layout = fsm_layout.build_layout(_routing_machine())
    step = layout.step_for("STATE_EXIT")
    branches = [link for link in layout.links
                if link.transition.source == "STATE_EXIT"]
    assert len(branches) == 3
    targets = [layout.step_for(link.transition.target) for link in branches]
    floor = min(target.y for target in targets)

    rails = set()
    for link in branches:
        for (ax, ay), (bx, by) in zip(link.points, link.points[1:]):
            if ay == by and ax != bx and step.bottom < ay < floor:
                rails.add(ay)
    assert rails == set([step.bottom + fsm_layout.FAN_RAIL]), rails

    # Each branch drops off that one rail straight into its target, so its bar
    # stands on the target's own axis rather than somewhere in between.
    for link, target in zip(branches, targets):
        assert link.bar[0] == target.cx, link.transition.target
        assert link.points[-1] == (target.cx, target.y)


def test_two_connectors_from_one_step_do_not_share_one_hook():    # A step's connectors used to share one fixed hook, so two captions
    # naming different targets landed on top of each other.
    layout = fsm_layout.build_layout(_branching_machine())
    by_source = {}
    for link in layout.links:
        if link.kind == "jump":
            by_source.setdefault(link.transition.source, []).append(link)
    pairs = [links for links in by_source.values() if len(links) >= 2]
    assert pairs, "no step has two connectors"
    for links in pairs:
        shapes = [tuple(point for point in link.points) for link in links]
        assert len(set(shapes)) == len(shapes), "connectors share one hook"
        rects = []
        for link in links:
            nx, ny = link.note_at
            rects.append((nx, ny, nx + link.note_w, ny + fsm_layout.TEXT_H))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax, ay, ax2, ay2 = rects[i]
                bx, by, bx2, by2 = rects[j]
                assert not (ax < bx2 and bx < ax2 and ay < by2 and by < ay2), (
                    "connector captions overlap"
                )


def test_nothing_drawn_below_a_step_reaches_the_next_one():
    # A branching step's bars, receptivities and connector hooks used to
    # run down into the row below them.
    machines = (
        ("branching", _branching_machine()),
        ("prefixed", _prefixed_machine()),
        ("merge", _merge_machine()),
        ("returns", _returns_machine()),
        ("skips", _skips_machine()),
    )
    for name, machine in machines:
        layout = fsm_layout.build_layout(
            machine,
            measure=lambda text: len(text) * 7,
            guard_measure=lambda text: len(text) * 6,
        )
        boxes = [(s.x, s.y, s.x + s.w, s.y + s.h) for s in layout.steps]
        boxes += [(c.x, c.y, c.x + c.w, c.y + c.h) for c in layout.chips]
        for link in layout.links:
            for px, py in link.points:
                for bx, by, bx2, by2 in boxes:
                    assert not (bx < px < bx2 and by < py < by2), (
                        "vertex inside a block in {0}".format(name)
                    )
            if link.note_at is not None:
                nx, ny = link.note_at
                nx2, ny2 = nx + link.note_w, ny + fsm_layout.TEXT_H
                for bx, by, bx2, by2 in boxes:
                    assert not (nx < bx2 and bx < nx2 and ny < by2 and by < ny2), (
                        "connector caption on a block in {0}".format(name)
                    )


def test_the_inbound_marker_never_runs_into_a_side_lane():
    # The "N -> " marker used to sit at a fixed INBOUND_W; on a column with
    # lanes it ran right through them into the step's own arrowheads.
    layout = fsm_layout.build_layout(_skips_machine())
    # Lanes belong to a COLUMN, not to the step that opened them: the marker
    # on step 1 sits in the same gutter as the lanes leaving steps 2 and 3.
    side_lanes = {}
    for link in layout.links:
        if link.kind == "side":
            col = layout.step_for(link.transition.source).col
            side_lanes.setdefault(col, []).append(
                min(px for px, _ in link.points)
            )
    marked = 0
    for step in layout.steps:
        if not step.inbound:
            continue
        marked += 1
        text = ", ".join(str(number) for number in step.inbound)
        right_edge = step.inbound_x + len(text) * fsm_layout.CHAR_W
        assert step.inbound_x < step.x
        for lane_x in side_lanes.get(step.col, []):
            assert right_edge <= lane_x, (
                "marker for step {0} runs into a lane".format(step.number)
            )
    assert marked >= 1, "no step carries an inbound marker"
