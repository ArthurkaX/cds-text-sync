"""ST-only project snapshot contracts."""

import os

import cds_static_analyzer as analyzer
from cds_static_analyzer.project import build_st_snapshot
from cds_static_analyzer.st import kinds as K


def test_codedys_property_accessors_are_classified_from_filename(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    for suffix in ("Get", "Set"):
        path = os.path.join(root, "POUs", f"FB_Conveyor.Speed.{suffix}.st")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("VAR\nEND_VAR\n\n// --- implementation ---\nvalue := 1;\n")

    snap = build_st_snapshot(root)
    assert snap.diagnostics == []
    assert snap.find_unit("POUs/FB_Conveyor.Speed.Get.st#FB_Conveyor.Speed.Get").kind == K.PROPERTY_GET
    assert snap.find_unit("POUs/FB_Conveyor.Speed.Set.st#FB_Conveyor.Speed.Set").kind == K.PROPERTY_SET


def test_implementation_only_child_files_are_classified_from_filename(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    files = {
        "FB_Conveyor.FB_Conveyor_Action.st": ("xDone := TRUE;", K.ACTION),
        "FB_Conveyor.Init.st": ("xReady := TRUE;", K.METHOD),
    }
    for name, (text, expected_kind) in files.items():
        with open(os.path.join(root, "POUs", name), "w", encoding="utf-8") as fh:
            fh.write(text)

    snap = build_st_snapshot(root)

    assert snap.find_unit(
        "POUs/FB_Conveyor.FB_Conveyor_Action.st#FB_Conveyor.FB_Conveyor_Action"
    ).kind == K.ACTION
    assert snap.find_unit(
        "POUs/FB_Conveyor.Init.st#FB_Conveyor.Init"
    ).kind == K.METHOD


def test_snapshot_parses_file_directives_once_at_project_boundary(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    path = os.path.join(root, "POUs", "Main.st")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("// cts:ignore-file cts0001 -- generated example\nPROGRAM Main\n")

    snap = build_st_snapshot(root)
    directives = snap.file_directives["POUs/Main.st"]
    assert directives.rules == frozenset({"CTS0001"})
    assert directives.issues == ()


def test_st_snapshot_normalizes_bom_and_crlf_offsets(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    path = os.path.join(root, "POUs", "Main.st")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\ufeffPROGRAM Main\r\nIMPLEMENTATION\r\nx := 1;\r\n")

    snap = build_st_snapshot(root)
    unit = snap.find_unit("POUs/Main.st#Main")
    assert unit is not None
    assert unit.kind == K.PROGRAM
    assert "\ufeff" not in unit.text
    assert "\r" not in unit.text
    assert unit.implementation.startswith("x := 1;")


def test_public_st_snapshot_ignores_xml_files(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    with open(os.path.join(root, "POUs", "Main.st"), "w", encoding="utf-8") as fh:
        fh.write("PROGRAM Main\n")
    with open(os.path.join(root, "Screen.xml"), "w", encoding="utf-8") as fh:
        fh.write("<Visualization><Single Name=\"Screen\" /></Visualization>\n")

    snap = build_st_snapshot(root)

    assert [unit.source_path for unit in snap.units] == ["POUs/Main.st"]
    assert snap.source_errors == []


def test_package_public_api_exposes_st_builder_only():
    assert analyzer.build_st_snapshot is build_st_snapshot
    assert not hasattr(analyzer, "build_snapshot")


# ===================================================================
# Phase 3 Step 3.2: ST split regression tests
# ===================================================================


def test_st_split_canonical_uppercase():
    text = "PROGRAM Main\nVAR\nx : INT;\nEND_VAR\nIMPLEMENTATION\nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.declaration == "PROGRAM Main\nVAR\nx : INT;\nEND_VAR"
    assert unit.implementation == "x := 1;\n"
    decl_span = [s for s in unit.source_spans if s.role == "declaration"][0]
    impl_span = [s for s in unit.source_spans if s.role == "implementation"][0]
    assert decl_span.start_offset == 0
    assert decl_span.end_offset == 33
    assert decl_span.line == 1
    assert impl_span.start_offset == 49
    assert impl_span.line == 6


def test_st_split_lowercase_and_mixed_case():
    text = "PROGRAM Main\nVAR\nx : INT;\nEND_VAR\nImPlEmEnTaTiOn\nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.declaration == "PROGRAM Main\nVAR\nx : INT;\nEND_VAR"
    assert unit.implementation == "x := 1;\n"

    text_lower = "PROGRAM Main\nVAR\nx : INT;\nEND_VAR\nimplementation\nx := 1;\n"
    unit_lower = analyzer.project._build_st_unit("POUs/Main.st", text_lower)
    assert unit_lower.declaration == "PROGRAM Main\nVAR\nx : INT;\nEND_VAR"
    assert unit_lower.implementation == "x := 1;\n"


def test_st_split_marker_at_byte_offset_zero():
    text = "IMPLEMENTATION\nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.Action.st", text)
    assert unit.declaration == ""
    assert unit.implementation == "x := 1;\n"
    decl_span = [s for s in unit.source_spans if s.role == "declaration"][0]
    impl_span = [s for s in unit.source_spans if s.role == "implementation"][0]
    assert decl_span.start_offset == 0
    assert decl_span.end_offset == 0
    assert impl_span.start_offset == 15
    assert impl_span.line == 2


def test_st_split_trailing_spaces_and_tabs():
    text = "PROGRAM Main\nIMPLEMENTATION  \t  \nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.declaration == "PROGRAM Main"
    assert unit.implementation == "x := 1;\n"


def test_st_split_lf_and_crlf_input():
    text_crlf = "PROGRAM Main\r\nVAR\r\nx : INT;\r\nEND_VAR\r\nIMPLEMENTATION\r\nx := 1;\r\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text_crlf)
    assert unit.declaration == "PROGRAM Main\nVAR\nx : INT;\nEND_VAR"
    assert unit.implementation == "x := 1;\n"


def test_st_split_marker_at_end_of_file():
    text = "PROGRAM Main\nIMPLEMENTATION"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.declaration == "PROGRAM Main"
    assert unit.implementation == ""


def test_st_split_blank_lines_immediately_after_marker():
    text = "PROGRAM Main\nIMPLEMENTATION\n\n\nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.declaration == "PROGRAM Main"
    assert unit.implementation == "x := 1;\n"
    impl_span = [s for s in unit.source_spans if s.role == "implementation"][0]
    assert impl_span.start_offset == 30
    assert impl_span.line == 5


def test_st_split_implementation_in_line_comment_ignored():
    text = "PROGRAM Main\n// IMPLEMENTATION\nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.implementation is None
    assert unit.declaration == "PROGRAM Main\n// IMPLEMENTATION\nx := 1;\n"


def test_st_split_implementation_in_block_comment_ignored():
    text = "PROGRAM Main\n(*\nIMPLEMENTATION\n*)\nx := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.implementation is None
    assert "IMPLEMENTATION" in unit.declaration


def test_st_split_identifier_containing_word_ignored():
    text = "PROGRAM Main\nMY_IMPLEMENTATION := 1;\n"
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    assert unit.implementation is None
    assert "MY_IMPLEMENTATION" in unit.declaration


def test_st_split_exact_declaration_and_implementation_spans_and_lines():
    text = "PROGRAM P\nVAR\n  y : INT;\nEND_VAR\nIMPLEMENTATION\n\ny := 2;\n"
    decl, decl_span, impl, impl_span = analyzer.project._split_st_with_offsets(text)
    assert decl == "PROGRAM P\nVAR\n  y : INT;\nEND_VAR"
    assert decl_span.start_offset == 0
    assert decl_span.end_offset == 32
    assert decl_span.line == 1
    assert decl_span.column == 1
    assert decl_span.end_line == 4
    assert decl_span.end_column == 8
    assert impl == "y := 2;\n"
    assert impl_span.start_offset == 49
    assert impl_span.end_offset == len(text)
    assert impl_span.line == 7
    assert impl_span.column == 1


def test_st_split_rules_see_declaration_and_implementation_correctly():
    from st_helpers import run_rule

    # CTS0073 checks declaration (undocumented public POU)
    # CTS0068 checks implementation (direct hardware addresses)
    text = (
        "PROGRAM Main\n"
        "VAR_INPUT\n"
        "    Command : BOOL;\n"
        "END_VAR\n"
        "   implementation \t\n"
        "%QX0.1 := Command;\n"
    )
    unit = analyzer.project._build_st_unit("POUs/Main.st", text)
    snap = analyzer.project.ProjectSnapshot(".", [unit])

    findings_decl = run_rule("CTS0073", snap)
    assert {f.anchor for f in findings_decl} == {"Main", "Command"}

    findings_impl = run_rule("CTS0068", snap)
    assert len(findings_impl) == 1
    assert findings_impl[0].anchor == "%QX0.1"
