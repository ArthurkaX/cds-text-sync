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


class _Geometry:
    """The pure geometry helpers of FsmDiagramForm, without WinForms.

    The form itself cannot be constructed outside the IDE, so the layout
    methods are borrowed onto a stub that only carries the machine list.
    """

    _BOX_X = fsm_ui.FsmDiagramForm._BOX_X
    _BOX_W = fsm_ui.FsmDiagramForm._BOX_W
    _BOX_H = fsm_ui.FsmDiagramForm._BOX_H
    _GAP = fsm_ui.FsmDiagramForm._GAP

    for _name in (
        "_current_machine", "_row_count", "_row_y", "_state_row",
        "_any_row", "_box_contains", "_to_content", "_state_at",
    ):
        locals()[_name] = getattr(fsm_ui.FsmDiagramForm, _name)
    del _name

    def __init__(self, machine, scroll_y=0):
        self.machines = [machine]
        self.current = 0
        self._diagram = _FakePanel(scroll_y)


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


def test_state_hit_test_follows_the_scroll_offset():
    machine = _sample_machine()
    assert [s.label for s in machine.states] == ["IDLE", "RUN", "DONE"]

    unscrolled = _Geometry(machine)
    row = unscrolled._state_row("DONE")
    centre_y = unscrolled._row_y(row) + unscrolled._BOX_H // 2
    click_x = unscrolled._BOX_X + 10

    hit = unscrolled._state_at(fsm_ui._Pt(click_x, centre_y))
    assert hit is not None and hit.label == "DONE"

    # Scrolled down, the same box is drawn 120px higher on screen, so the
    # click that lands on it arrives with a correspondingly smaller Y.
    scrolled = _Geometry(machine, scroll_y=120)
    hit = scrolled._state_at(fsm_ui._Pt(click_x, centre_y - 120))
    assert hit is not None and hit.label == "DONE"

    # Ignoring the offset is the bug this guards: the unshifted point now
    # falls on a different row entirely.
    stale = scrolled._state_at(fsm_ui._Pt(click_x, centre_y))
    assert stale is None or stale.label != "DONE"


def test_clicks_outside_any_box_select_nothing():
    geometry = _Geometry(_sample_machine())
    far_right = geometry._BOX_X + geometry._BOX_W + 50
    assert geometry._state_at(fsm_ui._Pt(far_right, geometry._row_y(0) + 5)) is None
    # The vertical gap between two boxes belongs to no state.
    gap_y = geometry._row_y(0) + geometry._BOX_H + 5
    assert geometry._state_at(fsm_ui._Pt(geometry._BOX_X + 10, gap_y)) is None


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
