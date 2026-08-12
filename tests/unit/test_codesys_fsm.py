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
