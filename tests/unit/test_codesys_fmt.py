"""Regression tests for the pure Project_fmt seams."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "src"
BRIDGE = ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
for path in (str(SHARED), str(BRIDGE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import codesys_fmt_operation as fmt  # noqa: E402
import codesys_fmt_ui as ui  # noqa: E402


def test_string_keywords_do_not_change_block_nesting():
    source = (
        "IF enabled THEN\n"
        "msg := 'CASE not handled';\n"
        "value := 1;\n"
        "END_IF;\n"
        "after := 2;\n"
    )

    formatted = fmt.format_text(source)

    assert formatted == (
        "IF enabled THEN\n"
        " msg := 'CASE not handled';\n"
        " value := 1;\n"
        "END_IF;\n"
        "after := 2;\n"
    )


def test_text_repairs_obvious_russian_mojibake():
    comment = "// Сброс признака первой циклы"
    corrupted = comment.encode("utf-8").decode("latin-1")

    assert fmt._repair_mojibake(corrupted) == comment


def test_declaration_formatting_preserves_crlf_when_no_change_is_needed():
    source = "VAR\r\nfoo        : INT;\r\nlongername : BOOL;\r\nEND_VAR\r\n"

    assert fmt.format_text(source, declaration=True) == source


def test_declaration_formatting_preserves_crlf_when_fixing_alignment():
    source = "VAR\r\nfoo : INT;\r\nlongername : BOOL;\r\nEND_VAR\r\n"

    formatted = fmt.format_text(source, declaration=True)

    assert "\r\n" in formatted
    assert "\n" not in formatted.replace("\r\n", "")
    assert formatted.endswith("END_VAR\r\n")
    assert formatted != source


def test_declaration_formatting_aligns_trailing_variable_comments():
    source = (
        "FUNCTION occupation_unit : DUT_Occupied_Sim_statuses\n"
        "VAR_INPUT\n"
        "    input : BOOL; // input occupation\n"
        "    longer_input : ARRAY[1..2] OF BOOL; (* simulation data *)\n"
        "    label : STRING := '// not a comment'; // display name\n"
        "END_VAR\n"
    )

    formatted = fmt.format_text(source, declaration=True)

    comment_lines = [
        line for line in formatted.splitlines()
        if "input occupation" in line or "simulation data" in line or "display name" in line
    ]
    comment_columns = [
        line.index("// input occupation")
        if "input occupation" in line
        else line.index("(* simulation data *)")
        if "simulation data" in line
        else line.rindex("// display name")
        for line in comment_lines
    ]
    assert comment_columns == [comment_columns[0]] * 3
    assert "STRING := '// not a comment';  // display name" in formatted


def test_large_repeated_source_highlights_only_changed_indexes():
    before = "\n".join(["END_IF;", "", "END_IF;"] * 80)
    lines = before.split("\n")
    lines[121] = "END_FOR;"
    after = "\n".join(lines)

    left, right = ui._changed_line_sets(before, after)

    assert left == {121}
    assert right == {121}


def test_line_by_line_view_keeps_context_once_and_pairs_a_change():
    text, removed, added = ui._line_by_line_diff(
        "IF x THEN\n y := 1;\nEND_IF;\n",
        "IF x THEN\n  y := 1;\nEND_IF;\n",
    )

    assert text.split("\n") == [
        "  IF x THEN",
        "-  y := 1;",
        "+   y := 1;",
        "  END_IF;",
        "  ",
    ]
    assert removed == {1}
    assert added == {2}


def test_picker_sorting_by_name_and_changes_keeps_unanalyzed_last():
    items = [
        {"label": "Zebra", "analysis": "done", "changed_lines": 2},
        {"label": "Alpha", "analysis": None},
        {"label": "Middle", "analysis": "done", "changed_lines": 0},
        {"label": "Beta", "analysis": "done", "changed_lines": 5},
    ]

    assert ui.sort_item_indexes(items, range(4), "name") == [1, 3, 2, 0]
    assert ui.sort_item_indexes(items, range(4), "name", descending=True) == [0, 2, 3, 1]
    assert ui.sort_item_indexes(items, range(4), "changes") == [2, 0, 3, 1]
    assert ui.sort_item_indexes(items, range(4), "changes", descending=True) == [3, 0, 2, 1]


def test_fmt_picker_labels_carry_the_fmt_wording():
    assert ui.PICKER_LABELS["title"] == "FMT - Select object"
    assert ui.PICKER_LABELS["scan_button"] == "Review All"
    assert ui.PICKER_LABELS["open_button"] == "Open selected"
    assert ui.PICKER_LABELS["scan_none"] == "No formatting changes were found."
    assert ui.PICKER_LABELS["message_title"] == "FMT"
    assert "{0}" in ui.PICKER_LABELS["analysis_done"]
    assert "{0}" in ui.PICKER_LABELS["analysis_hits"]


def test_text_mode_exposes_noninteractive_formatter_seam():
    result = fmt.main({"text": "IF x THEN\ny := 1;\nEND_IF;\n"})

    assert result["status"] == "success"
    assert result["changed_lines"] == 1
    assert result["after"] == "IF x THEN\n y := 1;\nEND_IF;\n"


def test_implementation_formatting_expands_compound_if_and_inline_else():
    source = (
        "IF aAct.wCmd <> _NoCmd AND aAct.eDev <> _Alrm AND aAct.eDev <> _Bnk THEN\n"
        "_Need2Lock := TRUE;\n"
        "ELSE _Need2Lock := FALSE;\n"
        "END_IF;\n"
    )

    formatted = fmt.format_text(source)

    assert formatted == (
        "IF aAct.wCmd <> _NoCmd\n"
        "    AND aAct.eDev <> _Alrm\n"
        "    AND aAct.eDev <> _Bnk\n"
        "THEN\n"
        "    _Need2Lock := TRUE;\n"
        "ELSE\n"
        "    _Need2Lock := FALSE;\n"
        "END_IF;\n"
    )
    assert fmt.format_text(formatted) == formatted


def test_compound_condition_does_not_split_operators_in_strings_or_parentheses():
    source = (
        "IF Check('AND') AND (a OR b) AND enabled THEN\n"
        "result := TRUE;\n"
        "END_IF;\n"
    )

    formatted = fmt.format_text(source)

    assert formatted == (
        "IF Check('AND')\n"
        "    AND (a OR b)\n"
        "    AND enabled\n"
        "THEN\n"
        "    result := TRUE;\n"
        "END_IF;\n"
    )


def test_analyze_keeps_a_valid_section_when_other_section_is_unavailable():
    class Document:
        text = "IF x THEN\ny := 1;\nEND_IF;\n"

    class Object:
        textual_implementation = Document()

        @property
        def textual_declaration(self):
            raise RuntimeError("Declaration is not available for this object type")

        def get_name(self):
            return "ImplementationOnly"

    item = {"object": Object(), "label": "ImplementationOnly"}

    fmt._analyze_item(item)

    assert item["status"] == "changed"
    assert item["changed_lines"] == 1


def test_raising_section_getter_is_no_section_not_a_read_error():
    # GVL/DUT expose no textual_implementation; the CODESYS getter raises
    # instead of returning None. That must read as "no such section", not as a
    # read error — otherwise every such object in the project shows up as
    # [read error].
    class Document:
        text = "VAR\r\nfoo : INT;\r\nlongername : BOOL;\r\nEND_VAR\r\n"

    class Object:
        textual_declaration = Document()

        @property
        def textual_implementation(self):
            raise RuntimeError("Implementation is not available for this object type")

        def get_name(self):
            return "DeclarationOnly"

    item = {"object": Object(), "label": "DeclarationOnly"}

    fmt._analyze_item(item)

    assert item["status"] == "changed"
    assert not item.get("read_errors")
    assert item["suffix"] is None
    assert item["display"].endswith("[1 line(s) to fix]")


def test_analyze_keeps_a_valid_section_when_declaration_text_raises():
    class Document:
        text = "IF x THEN\ny := 1;\nEND_IF;\n"

    class RaisingDocument:
        @property
        def text(self):
            raise RuntimeError("Declaration is not available for this object type")

    class Object:
        textual_implementation = Document()

        @property
        def textual_declaration(self):
            return RaisingDocument()

        def get_name(self):
            return "ImplementationOnly"

    item = {"object": Object(), "label": "ImplementationOnly"}

    fmt._analyze_item(item)

    assert item["status"] == "changed"
    assert item["read_errors"]
    assert item["suffix"].endswith(", partial]")
    assert item["error"]


def test_analyze_marks_error_when_both_sections_are_unreadable():
    class RaisingDocument:
        @property
        def text(self):
            raise RuntimeError("Section is not available for this object type")

    class Object:
        textual_declaration = RaisingDocument()
        textual_implementation = RaisingDocument()

        def get_name(self):
            return "Unreadable"

    item = {"object": Object(), "label": "Unreadable"}

    fmt._analyze_item(item)

    assert item["status"] == "error"
    assert item["analysis"] == "error"
    assert item["display"].endswith("[read error]")


def test_closing_single_preview_returns_to_the_picker(monkeypatch):
    item = {
        "label": "POU",
        "analysis": "done",
        "status": "changed",
        "changed_lines": 1,
        "after": "formatted text",
        "writes": [],
    }
    calls = []

    class Ui:
        def warning(self, message):
            raise AssertionError(message)

    class Runtime:
        ui = Ui()
        projects = object()
        system = None
        caller_globals = None

    class Projects:
        primary = object()

    responses = [("selected", 0), ("cancel", 0)]
    monkeypatch.setattr(fmt, "resolve_projects", lambda *args: Projects())
    monkeypatch.setattr(fmt, "_build_items", lambda *args: ([item], 0))
    monkeypatch.setattr(
        fmt.codesys_fmt_ui,
        "show_object_picker",
        lambda _items, index, *_args: (calls.append(index) or responses.pop(0)),
    )
    monkeypatch.setattr(fmt, "_show_preview", lambda _item: "stop")

    result = fmt.main(runtime=Runtime())

    assert result == {"status": "cancelled"}
    assert calls == [0, 0]


def test_applying_single_preview_returns_to_the_picker(monkeypatch):
    item = {
        "label": "POU",
        "analysis": "done",
        "status": "changed",
        "changed_lines": 1,
        "after": "formatted text",
        "writes": [],
    }
    calls = []

    class Runtime:
        projects = object()
        system = None
        caller_globals = None

    class Projects:
        primary = object()

    responses = [("selected", 0), ("cancel", 0)]
    monkeypatch.setattr(fmt, "resolve_projects", lambda *args: Projects())
    monkeypatch.setattr(fmt, "_build_items", lambda *args: ([item], 0))
    monkeypatch.setattr(
        fmt.codesys_fmt_ui,
        "show_object_picker",
        lambda _items, index, *_args: (calls.append(index) or responses.pop(0)),
    )
    monkeypatch.setattr(fmt, "_show_preview", lambda _item: "apply")
    monkeypatch.setattr(fmt, "_apply_item", lambda _item: "")
    monkeypatch.setattr(
        fmt, "_analyze_item",
        lambda _item: (_ for _ in ()).throw(AssertionError("must not reread after apply")),
    )
    monkeypatch.setattr(fmt.codesys_fmt_ui, "show_message", lambda *args: None)

    result = fmt.main(runtime=Runtime())

    assert result == {"status": "cancelled"}
    assert item["status"] == "ok"
    assert calls == [0, 0]


def test_selected_wrapper_with_same_guid_is_not_inserted_twice(monkeypatch):
    class Document:
        def __init__(self, text):
            self.text = text

    class Object:
        def __init__(self, guid):
            self.guid = guid
            self.textual_implementation = Document("x := 1;\n")

        def get_name(self):
            return "POU"

    listed = Object("{ABC}")
    selected_wrapper = Object("abc")

    class Project:
        def get_children(self, recursive=True):
            return [listed]

    project = Project()
    monkeypatch.setattr(fmt, "_selected_object", lambda holder: selected_wrapper if holder is project else None)
    monkeypatch.setattr(fmt, "_object_label", lambda obj: "POU")

    items, selected_index = fmt._build_items(project, None, None)

    assert len(items) == 1
    assert selected_index == 0
