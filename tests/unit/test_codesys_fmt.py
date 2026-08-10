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


def test_large_repeated_source_highlights_only_changed_indexes():
    before = "\n".join(["END_IF;", "", "END_IF;"] * 80)
    lines = before.split("\n")
    lines[121] = "END_FOR;"
    after = "\n".join(lines)

    left, right = ui._changed_line_sets(before, after)

    assert left == {121}
    assert right == {121}


def test_text_mode_exposes_noninteractive_formatter_seam():
    result = fmt.main({"text": "IF x THEN\ny := 1;\nEND_IF;\n"})

    assert result["status"] == "success"
    assert result["changed_lines"] == 1
    assert result["after"] == "IF x THEN\n y := 1;\nEND_IF;\n"


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
