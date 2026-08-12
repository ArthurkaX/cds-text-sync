"""Regression tests for the pure Project_fsm seams."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "src"
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
for path in (str(SHARED), str(BRIDGE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import codesys_fsm_operation as fsm  # noqa: E402
import codesys_fsm_ui as fsm_ui  # noqa: E402
import codesys_fmt_ui as fmt_ui  # noqa: E402
from cts_shared.st import fsm_layout  # noqa: E402


def test_modules_import_cleanly():
    # The module must import under CPython whether or not WinForms is present.
    assert hasattr(fsm_ui, "show_fsm_diagram")
    assert hasattr(fsm_ui, "show_message")
    assert hasattr(fsm_ui, "FsmDiagramForm")
    assert fsm_ui.codesys_fmt_ui is not None


def test_headless_text_mode_finds_struct_and_next_state_fsm():
    source = (
        "CASE state OF\n"
        "  IDLE:\n"
        "    next_state := RUN;\n"
        "  RUN:\n"
        "    next_state := IDLE;\n"
        "END_CASE;\n"
    )

    result = fsm.main({"text": source})

    assert result["status"] == "success"
    assert len(result["machines"]) == 1
    machine = result["machines"][0]
    assert machine["selector"] == "state"
    assert machine["states"] == ["IDLE", "RUN"]
    assert len(machine["transitions"]) == 2
    assert len(result["mermaid"]) == 1
    assert result["mermaid"][0].startswith("stateDiagram-v2")


def test_headless_text_mode_dispatch_case_has_no_fsm():
    source = (
        "CASE command OF\n"
        "  1:\n"
        "    value := 10;\n"
        "  2:\n"
        "    value := 20;\n"
        "END_CASE;\n"
    )

    result = fsm.main({"text": source})

    assert result["status"] == "success"
    assert result["machines"] == []
    assert result["mermaid"] == []


def test_analyze_item_sets_suffix_and_status():
    class Document:
        def __init__(self, text):
            self.text = text

    class Object:
        def __init__(self, implementation=None, raise_on_read=False):
            self._implementation = implementation
            self._raise = raise_on_read

        @property
        def textual_implementation(self):
            if self._raise:
                raise RuntimeError("boom")
            return self._implementation

    source = (
        "CASE state OF\n"
        "  IDLE:\n"
        "    next_state := RUN;\n"
        "  RUN:\n"
        "    next_state := IDLE;\n"
        "END_CASE;\n"
    )

    with_fsm = {"object": Object(Document(source)), "label": "POU", "status": None, "analysis": None}
    fsm._analyze_item(with_fsm)
    assert with_fsm["suffix"] == "[1 FSM]"
    assert with_fsm["status"] == "changed"
    assert with_fsm["analysis"] == "done"

    no_impl = {"object": Object(None), "label": "GVL", "status": None, "analysis": None}
    fsm._analyze_item(no_impl)
    assert no_impl["suffix"] == "[no FSM]"
    assert no_impl["status"] == "ok"
    assert no_impl["analysis"] == "done"

    broken = {"object": Object(None, raise_on_read=True), "label": "POU", "status": None, "analysis": None}
    fsm._analyze_item(broken)
    assert broken["suffix"] == "[read error]"
    assert broken["status"] == "error"
    assert broken["analysis"] == "error"


def test_picker_labels_default_to_fmt_when_labels_omitted():
    assert fmt_ui.PICKER_LABELS["title"] == "FMT - Select object"
    assert fmt_ui.PICKER_LABELS["scan_button"] == "Review All"
    assert fmt_ui.PICKER_LABELS["open_button"] == "Open selected"
    assert fmt_ui.PICKER_LABELS["scan_none"] == "No formatting changes were found."
    assert fmt_ui.PICKER_LABELS["message_title"] == "FMT"


class _FakePanel:
    """Stands in for the diagram Panel; only the scroll offset is read."""

    def __init__(self, scroll_y=0):
        # WinForms reports the offset as zero or negative.
        self.AutoScrollPosition = fsm_ui._Pt(0, -scroll_y)


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


def test_pending_indexes_skips_already_analyzed_blocks():
    items = [
        {"analysis": None},
        {"analysis": "done"},
        {"analysis": None},
        {"analysis": "error"},
    ]
    assert fmt_ui.pending_indexes(items, [0, 1, 2, 3]) == [0, 2]
    # Only the filtered subset is ever swept.
    assert fmt_ui.pending_indexes(items, [1, 3]) == []
    assert fmt_ui.pending_indexes(items, []) == []


def test_fsm_labels_defer_analysis_and_fmt_does_not():
    assert fmt_ui.PICKER_LABELS["deferred_analysis"] is False
    assert fmt_ui.PICKER_LABELS["analyze_button"] == "Analyze"
    assert "{0}" in fmt_ui.PICKER_LABELS["analysis_done"]
    assert "{0}" in fmt_ui.PICKER_LABELS["analysis_hits"]


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
        # The stem runs down out of the "any" box, then turns into the block.
        assert link.points[0][0] == link.points[1][0]
        assert link.bar[2] == "h"
        assert link.arrow[2] == "right"
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


def test_a_click_is_translated_by_the_scroll_offset():
    # The panel scrolls owner-drawn content by hand, so a click has to be
    # moved back down into the part of the diagram that scrolled away.
    panel = _FakePanel(scroll_y=120)

    class _Form:
        _to_content = fsm_ui.FsmDiagramForm._to_content

        def __init__(self, diagram):
            self._diagram = diagram

    moved = _Form(panel)._to_content(fsm_ui._Pt(50, 30))
    assert (moved.X, moved.Y) == (50, 150)


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
        assert len(link.points) == 2
        assert link.arrow[2] in ("up", "down")
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
