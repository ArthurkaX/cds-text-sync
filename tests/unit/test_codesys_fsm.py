"""Regression tests for the pure Project_fsm seams."""

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "src"
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
for path in (str(SHARED), str(BRIDGE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import codesys_fsm_operation as fsm  # noqa: E402
import codesys_fsm_ui as fsm_ui  # noqa: E402
import codesys_fsm_picker as fsm_picker  # noqa: E402
import ide_picker_common as picker_common  # noqa: E402
from cts_shared.st import fsm_layout  # noqa: E402


def test_modules_import_cleanly():
    # The module must import under CPython whether or not WinForms is present.
    assert hasattr(fsm_ui, "show_fsm_diagram")
    assert hasattr(fsm_ui, "show_message")
    assert hasattr(fsm_ui, "FsmDiagramForm")


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

    # A raising section getter means "no such section" (GVL/DUT have no
    # textual_implementation), not a read error.
    raising_getter = {"object": Object(None, raise_on_read=True), "label": "GVL", "status": None, "analysis": None}
    fsm._analyze_item(raising_getter)
    assert raising_getter["suffix"] == "[no FSM]"
    assert raising_getter["status"] == "ok"
    assert raising_getter["analysis"] == "done"

    # A genuine read error is a document whose .text raises.
    class RaisingDocument:
        @property
        def text(self):
            raise RuntimeError("boom")

    class BrokenObject:
        @property
        def textual_implementation(self):
            return RaisingDocument()

    broken = {"object": BrokenObject(), "label": "POU", "status": None, "analysis": None}
    fsm._analyze_item(broken)
    assert broken["suffix"] == "[read error]"
    assert broken["status"] == "error"
    assert broken["analysis"] == "error"


def test_fsm_picker_labels_carry_the_fsm_wording():
    assert fsm_picker.FSM_PICKER_LABELS["title"] == "FSM - Select object"
    assert fsm_picker.FSM_PICKER_LABELS["scan_button"] == "Find next FSM"
    assert fsm_picker.FSM_PICKER_LABELS["open_button"] == "Show diagram"
    assert fsm_picker.FSM_PICKER_LABELS["scan_none"] == "No state machine was found in the matching blocks."
    assert fsm_picker.FSM_PICKER_LABELS["message_title"] == "FSM"
    assert "{0}" in fsm_picker.FSM_PICKER_LABELS["analysis_done"]
    assert "{0}" in fsm_picker.FSM_PICKER_LABELS["analysis_hits"]


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


class _Keys:
    Enter = 13


class _KeyEvent:
    def __init__(self, key_code):
        self.KeyCode = key_code
        self.Handled = False
        self.SuppressKeyPress = False
        self.IsInputKey = False


class _List:
    def __init__(self, selected=-1):
        self.SelectedIndex = selected

    def Invalidate(self):
        pass


class _Text:
    def __init__(self, text=""):
        self.Text = text

    def Focus(self):
        pass


class _SearchPicker:
    """The picker reduced to what the Enter path actually touches.

    Both handlers are the real ones, so the test fails if Enter can no longer
    reach the search - which is exactly how it broke.
    """

    _on_search_key_down = fsm_picker.FsmObjectPickerForm._on_search_key_down
    _on_search_preview_key = fsm_picker.FsmObjectPickerForm._on_search_preview_key
    _accept = fsm_picker.FsmObjectPickerForm._accept
    _accept_all = fsm_picker.FsmObjectPickerForm._accept_all
    _show_diagram = fsm_picker.FsmObjectPickerForm._show_diagram

    def __init__(self, query="AERATION", selected=-1):
        self.labels = dict(fsm_picker.FSM_PICKER_LABELS)
        self._search = _Text(query)
        self._status = _Text()
        self._search_confirmed = False
        self._listed_query = None
        self._visible_indexes = []
        self.list = _List(selected)
        self.analyzing = False
        self.UseWaitCursor = False
        self.selected_index = -1
        self.items = []
        self.calls = []
        self.refreshed = 0
        self.analyzed = []
        self._scanning = False
        self._stop_requested = False
        self._analysis_queue = []
        self._analysis_cursor = 0
        self.started = []
        self.view_callback = None
        self.viewed_count = 0
        self.action = "cancel"
        self.DialogResult = None
        self.closed = 0

    def Close(self):
        self.closed += 1

    def _analyze_index(self, index):
        self.analyzed.append(index)

    def scan_callback(self, index, visible_indexes=None, query=""):
        self.calls.append((index, visible_indexes, query))
        self.items.append({"label": "AERATION/AERATION.st", "display": "AERATION"})
        return {"status": "Found 1 matching block(s)."}

    def _start_background_analysis(self, indexes):
        self.started.append(list(indexes))

    def _analysis_status(self):
        return "status line"

    def _stop_background_analysis(self):
        pass

    def _refresh_list(self):
        self.refreshed += 1


def test_enter_runs_the_external_search_instead_of_dying_on_arity(monkeypatch):
    # Enter calls _accept_all() with no arguments, but WinForms binds it as a
    # Click handler too. When it insisted on (sender, event) the call raised
    # inside the message pump, the search never ran, and the picker just sat
    # there with an empty list.
    monkeypatch.setattr(fsm_picker, "Keys", _Keys, raising=False)
    picker = _SearchPicker()

    picker._on_search_key_down(picker, _KeyEvent(_Keys.Enter))

    assert picker.calls == [(0, [], "AERATION")]
    assert picker.refreshed == 1
    assert picker._search_confirmed is True
    assert picker._status.Text == "Found 1 matching block(s)."
    assert len(picker.items) == 1
    # The key must not reach the form, or AcceptButton closes the dialog.
    assert picker.analyzing is False


def test_enter_on_a_blank_search_asks_for_a_term_and_runs_nothing(monkeypatch):
    monkeypatch.setattr(fsm_picker, "Keys", _Keys, raising=False)
    picker = _SearchPicker(query="   ")

    picker._on_search_key_down(picker, _KeyEvent(_Keys.Enter))

    assert picker.calls == []
    assert picker._search_confirmed is False
    assert picker._status.Text == fsm_picker.FSM_PICKER_LABELS["search_prompt"]


def test_the_search_box_claims_enter_so_key_down_is_reached_at_all(monkeypatch):
    # A single-line TextBox reports IsInputKey(Enter) as False, so WinForms
    # routes Enter to ProcessDialogKey - the form's AcceptButton - and never
    # raises KeyDown. Everything the Enter path does hangs off this flag.
    monkeypatch.setattr(fsm_picker, "Keys", _Keys, raising=False)
    picker = _SearchPicker()

    enter = _KeyEvent(_Keys.Enter)
    picker._on_search_preview_key(picker, enter)
    assert enter.IsInputKey is True

    other = _KeyEvent(_Keys.Enter + 1)
    picker._on_search_preview_key(picker, other)
    assert other.IsInputKey is False, "only Enter may be taken from the dialog"


def test_the_wiring_that_makes_enter_reachable_is_not_dropped():
    # The bug was never in the handlers; it was that nothing called them.
    # Only the subscription itself can catch that regression.
    source = Path(fsm_picker.__file__).read_text(encoding="utf-8")
    assert "search.PreviewKeyDown += self._on_search_preview_key" in source
    assert "search.KeyDown += self._on_search_key_down" in source


def test_accept_runs_the_search_when_there_is_nothing_to_open():
    # If Enter still arrives through AcceptButton, an empty list plus a
    # filled search box means "search", not "press Enter first" - which was
    # a deadlock, since only the unreachable KeyDown could confirm.
    picker = _SearchPicker(selected=-1)

    picker._accept(picker, None)

    assert picker.calls == [(0, [], "AERATION")]
    assert picker._search_confirmed is True
    assert picker.analyzed == []


def test_accept_still_opens_a_selected_block_instead_of_researching():
    picker = _SearchPicker(selected=0)

    picker._accept(picker, None)

    assert picker.calls == [], "a selected block must not trigger a new search"
    assert picker._status.Text == fsm_picker.FSM_PICKER_LABELS["search_prompt"]


def test_a_broad_search_returns_instead_of_deadlocking_on_a_full_pipe(tmp_path, monkeypatch):
    view = tmp_path / "project-view"
    view.mkdir()
    for index in range(400):
        (view / ("Application_Block%03d.st" % index)).write_text(
            "value := 1;\n", encoding="utf-8"
        )
    (view / "Насос_Automat.st").write_text("value := 1;\n", encoding="utf-8")

    cds_src = ROOT / "products" / "cds-text-sync" / "src"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(cds_src), str(SHARED)]))
    monkeypatch.setattr(fsm, "_project_sync_folder", lambda project: (str(tmp_path), None))
    monkeypatch.setattr(fsm, "_python_command", lambda: sys.executable)
    monkeypatch.setattr(fsm, "_body_root", lambda: str(cds_src))
    # Fail fast: a regression must not stall the suite for the real 120s.
    monkeypatch.setattr(fsm, "FSM_SEARCH_TIMEOUT_SECONDS", 60)

    result = fsm._search_workspace(object(), "a", list_only=True)

    assert len(result["candidates"]) == 401
    assert "Насос_Automat.st" in result["candidates"]


def test_the_second_click_hands_analysis_to_the_timer_instead_of_blocking():
    picker = _SearchPicker(query="a")
    picker._search_confirmed = True
    picker._listed_query = "a"
    picker._visible_indexes = [0, 1, 2]

    picker._accept_all()

    assert picker.started == [[0, 1, 2]]
    assert picker.calls == []


def test_a_click_while_the_scan_runs_stops_it():
    picker = _SearchPicker(query="a")
    picker._search_confirmed = True
    picker._listed_query = "a"
    picker._scanning = True

    picker._accept_all()

    assert picker._stop_requested is True
    assert picker.started == []
    assert picker.calls == []


class _DialogResult:
    OK = "ok"


class _ScanPicker:
    """The picker reduced to what the Find-next-FSM sweep touches."""

    _start_background_analysis = fsm_picker.FsmObjectPickerForm._start_background_analysis
    _run_scan = fsm_picker.FsmObjectPickerForm._run_scan
    _closed_or_closing = fsm_picker.FsmObjectPickerForm._closed_or_closing
    _analyze_queued = fsm_picker.FsmObjectPickerForm._analyze_queued
    _report_progress = fsm_picker.FsmObjectPickerForm._report_progress
    _pump = fsm_picker.FsmObjectPickerForm._pump
    _refresh_after_scan = fsm_picker.FsmObjectPickerForm._refresh_after_scan
    _set_scan_button_text = fsm_picker.FsmObjectPickerForm._set_scan_button_text
    _stop_background_analysis = fsm_picker.FsmObjectPickerForm._stop_background_analysis
    _analysis_status = fsm_picker.FsmObjectPickerForm._analysis_status
    _open_scan_hit = fsm_picker.FsmObjectPickerForm._open_scan_hit
    _show_diagram = fsm_picker.FsmObjectPickerForm._show_diagram

    def __init__(self, items, view_callback=None):
        self.items = items
        self.analyzing = False
        self.IsDisposed = False
        self.Disposing = False
        self._is_closing = False
        self._scanning = False
        self._stop_requested = False
        self._analysis_queue = []
        self._analysis_cursor = 0
        self._visible_indexes = list(range(len(items)))
        self._sort_key = None
        self._status = _Text()
        self.list = _List(-1)
        self.selected_index = -1
        self.action = "cancel"
        self.DialogResult = None
        self.view_callback = view_callback
        self.viewed_count = 0
        self.analyzed = []
        self.closed = 0

    def analyze_callback(self, index):
        self.analyzed.append(index)
        item = self.items[index]
        item["analysis"] = "done"
        item["status"] = "changed" if item.get("fsm") else "ok"

    def _refresh_list(self):
        pass

    def Close(self):
        self.closed += 1


def _blocks(count):
    return [{"label": "B%d.st" % index, "analysis": None} for index in range(count)]


def test_the_sweep_runs_on_the_click_instead_of_waiting_for_a_timer_tick():
    # The sweep used to be handed to a WinForms timer, and inside the IDE's
    # nested modal pump that tick never arrived: the button said Stop and
    # nothing was ever analyzed. The click itself has to do the work.
    picker = _ScanPicker(_blocks(5), view_callback=lambda index: True)

    picker._start_background_analysis([0, 1, 2, 3, 4])

    assert picker.analyzed == [0, 1, 2, 3, 4]
    assert picker._status.Text == fsm_picker.FSM_PICKER_LABELS["scan_none"]
    assert picker.closed == 0
    assert picker._scanning is False


def test_the_sweep_stops_at_the_first_machine_and_shows_it_without_closing():
    items = _blocks(5)
    items[2]["fsm"] = True
    viewed = []
    picker = _ScanPicker(items, view_callback=lambda index: viewed.append(index) or True)

    picker._start_background_analysis([0, 1, 2, 3, 4])

    assert picker.analyzed == [0, 1, 2]
    assert viewed == [2], "the diagram opens on top of the picker"
    assert picker.closed == 0, "closing the picker is what stranded the user in the IDE"
    assert picker.selected_index == 2
    assert picker.viewed_count == 1


def test_the_next_click_resumes_at_the_block_after_the_last_machine():
    items = _blocks(5)
    items[1]["fsm"] = True
    items[3]["fsm"] = True
    viewed = []
    picker = _ScanPicker(items, view_callback=lambda index: viewed.append(index) or True)

    picker._start_background_analysis([0, 1, 2, 3, 4])
    picker._start_background_analysis([0, 1, 2, 3, 4])

    assert picker.analyzed == [0, 1, 2, 3]
    assert viewed == [1, 3]
    assert picker.closed == 0


def test_a_sweep_without_a_view_callback_still_hands_the_hit_to_the_caller(monkeypatch):
    monkeypatch.setattr(fsm_picker, "DialogResult", _DialogResult, raising=False)
    items = _blocks(3)
    items[1]["fsm"] = True
    picker = _ScanPicker(items)

    picker._start_background_analysis([0, 1, 2])

    assert picker.action == "all"
    assert picker.selected_index == 1
    assert picker.closed == 1


def test_stop_halts_the_sweep_between_blocks():
    picker = _ScanPicker(_blocks(5), view_callback=lambda index: True)
    plain = picker.analyze_callback

    def analyze_then_stop(index):
        plain(index)
        picker._stop_background_analysis()

    picker.analyze_callback = analyze_then_stop
    picker._start_background_analysis([0, 1, 2, 3, 4])

    assert picker.analyzed == [0]
    assert picker._status.Text == fsm_picker.FSM_PICKER_LABELS["scan_stopped"]
    assert picker._analysis_cursor == 1


def test_a_block_that_cannot_be_read_is_marked_and_does_not_stop_the_sweep():
    picker = _ScanPicker(_blocks(3), view_callback=lambda index: True)

    def analyze(index):
        picker.analyzed.append(index)
        if index == 1:
            raise IOError("locked")
        picker.items[index]["analysis"] = "done"
        picker.items[index]["status"] = "ok"

    picker.analyze_callback = analyze
    picker._start_background_analysis([0, 1, 2])

    assert picker.analyzed == [0, 1, 2]
    assert picker.items[1]["status"] == "error"
    assert picker.items[1]["error"] == "locked"


def test_show_diagram_keeps_the_picker_open_instead_of_returning_to_the_ide():
    picker = _SearchPicker(selected=0)
    picker._search_confirmed = True
    picker._visible_indexes = [0]
    picker.items = [{"label": "A.st", "analysis": "done", "status": "changed"}]
    viewed = []
    picker.view_callback = lambda index: viewed.append(index) or True

    picker._accept(picker, None)

    assert viewed == [0]
    assert picker.closed == 0
    assert picker.viewed_count == 1
    assert picker.selected_index == 0


def test_a_diagram_that_cannot_be_shown_leaves_the_picker_up_with_a_reason():
    picker = _SearchPicker(selected=0)
    picker._search_confirmed = True
    picker._visible_indexes = [0]
    picker.items = [{"label": "A.st", "analysis": "done", "status": "changed"}]
    picker.view_callback = lambda index: False

    picker._accept(picker, None)

    assert picker.closed == 0
    assert picker.viewed_count == 0
    assert "A.st" in picker._status.Text


def test_the_operation_hands_the_picker_a_view_callback():
    # Without this wiring the picker closes to show a diagram, and closing the
    # diagram drops the user back into CODESYS instead of the picker.
    source = Path(fsm.__file__).read_text(encoding="utf-8")
    assert "view_callback=view_selected" in source
    assert "codesys_fsm_ui.show_fsm_diagram(item[\"label\"], machines)" in source


def test_a_workspace_block_is_parsed_in_process_without_spawning_python(tmp_path):
    # The picker analyzes one block per timer tick, so a block has to be cheap.
    view = tmp_path / "project-view" / "App"
    view.mkdir(parents=True)
    (view / "Насос.st").write_text(
        "FUNCTION_BLOCK Насос\nVAR\n    state : INT;\nEND_VAR\n"
        "// --- implementation ---\n"
        "CASE state OF\n  0: state := 1;\n  1: state := 0;\nEND_CASE;\n",
        encoding="utf-8",
    )
    (view / "Plain.st").write_text(
        "FUNCTION_BLOCK Plain\nVAR\n    x : INT;\nEND_VAR\n"
        "// --- implementation ---\nx := x + 1;\n",
        encoding="utf-8",
    )

    hit = fsm._analyze_workspace_item({"label": "App/Насос.st"}, str(tmp_path))
    miss = fsm._analyze_workspace_item({"label": "App/Plain.st"}, str(tmp_path))
    gone = fsm._analyze_workspace_item({"label": "App/Missing.st"}, str(tmp_path))

    assert hit["status"] == "changed"
    assert hit["suffix"] == "[1 FSM]"
    assert hit["analysis"] == "done"
    assert len(hit["machines"]) == 1
    assert hasattr(hit["machines"][0], "selector")
    assert miss["status"] == "ok"
    assert miss["suffix"] == "[no FSM]"
    assert gone["status"] == "error"
    assert gone["analysis"] == "error"


def _snapshot_workspace(tmp_path, created):
    (tmp_path / "project-view").mkdir()
    dump = tmp_path / ".dump"
    dump.mkdir()
    (dump / "manifest.json").write_text(
        json.dumps({"created": created}), encoding="utf-8"
    )
    return str(tmp_path)


def test_a_snapshot_from_this_sitting_is_not_nagged_about(tmp_path):
    created = time.strftime("%Y-%m-%dT%H:%M:%S")
    folder = _snapshot_workspace(tmp_path, created)

    notice, error = fsm._snapshot_notice(folder)

    assert error is None
    assert "moments ago" in notice
    assert "Re-export" not in notice
    assert created in notice


def test_an_old_snapshot_still_asks_for_a_re_export(tmp_path):
    stamp = time.time() - (3 * 86400 + 12 * 3600)
    created = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stamp))
    folder = _snapshot_workspace(tmp_path, created)

    notice, error = fsm._snapshot_notice(folder)

    assert error is None
    assert "3 days ago" in notice
    assert "Re-export the project" in notice


def test_a_project_saved_after_a_fresh_export_is_flagged(tmp_path):
    created = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 60))
    folder = _snapshot_workspace(tmp_path, created)
    project_file = tmp_path / "Machine.project"
    project_file.write_text("saved after the export", encoding="utf-8")

    class _Project(object):
        path = str(project_file)

    notice, error = fsm._snapshot_notice(folder, _Project())

    assert error is None
    assert "has been saved since" in notice
    quiet, _quiet_error = fsm._snapshot_notice(folder)
    assert "Re-export" not in quiet
    assert "saved since" not in quiet


def test_an_unparseable_stamp_keeps_the_re_export_hint(tmp_path):
    folder = _snapshot_workspace(tmp_path, "yesterday, around noon")

    notice, error = fsm._snapshot_notice(folder)

    assert error is None
    assert "yesterday, around noon" in notice
    assert "Re-export the project" in notice
