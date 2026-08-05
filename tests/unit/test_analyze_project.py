"""
test_analyze_project.py - ProjectSnapshot built from the analyze fixture.
"""

import os

from cds_static_analyzer.project import build_compat_snapshot
from cds_static_analyzer.st import kinds as K

from analyze_helpers import fixture_project_view


def test_fixture_has_expected_units():
    snap = build_compat_snapshot(fixture_project_view())
    by_id = {u.id: u for u in snap.units}
    assert snap.diagnostics == []

    assert by_id["POUs/Main.st#Main"].kind == K.PROGRAM
    assert by_id["POUs/FB_Conveyor.st#FB_Conveyor"].kind == K.FUNCTION_BLOCK
    assert by_id["POUs/FB_Conveyor.Run.st#FB_Conveyor.Run"].kind == K.METHOD
    assert by_id["POUs/FB_Conveyor.Advance.st#FB_Conveyor.Advance"].kind == K.ACTION
    assert by_id["POUs/GVL_HMI.st#GVL_HMI"].kind == K.GVL
    assert by_id["POUs/GVL_Persistent.st#GVL_Persistent"].kind == K.GVL_PERSISTENT
    assert by_id["POUs/MyEnum.st#MyEnum"].kind == K.ENUM
    assert by_id["POUs/MyStruct.st#MyStruct"].kind == K.STRUCT
    assert by_id["POUs/GlobalTextList.xml#GlobalTextList"].kind == K.TEXTLIST
    screen = by_id["Runtime/PLC Logic/Application/HMI/Screen1.xml#Screen1"]
    assert screen.kind == K.VISUALIZATION


def test_owner_resolution():
    snap = build_compat_snapshot(fixture_project_view())
    run = snap.find_unit("POUs/FB_Conveyor.Run.st#FB_Conveyor.Run")
    fb = snap.find_unit("POUs/FB_Conveyor.st#FB_Conveyor")
    assert run is not None and fb is not None
    assert run.owner_name == "FB_Conveyor"
    assert run.owner_id == fb.id


def test_units_owned_by():
    snap = build_compat_snapshot(fixture_project_view())
    owned = snap.units_owned_by("FB_Conveyor")
    assert {u.qualified_name for u in owned} == {
        "FB_Conveyor.Run",
        "FB_Conveyor.Advance",
    }


def test_decl_impl_split_with_offsets():
    snap = build_compat_snapshot(fixture_project_view())
    main = snap.find_unit("POUs/Main.st#Main")
    assert main is not None
    assert main.declaration.startswith("PROGRAM MAIN")
    assert main.implementation.strip().startswith("x := 10;")
    # Span line numbers are 1-based and precise.
    impl_span = [s for s in main.source_spans if s.role == "implementation"][0]
    assert impl_span.line == 17  # the IMPLEMENTATION marker's body line


def test_action_has_no_declaration():
    snap = build_compat_snapshot(fixture_project_view())
    action = snap.find_unit("POUs/FB_Conveyor.Advance.st#FB_Conveyor.Advance")
    assert action is not None
    assert action.declaration.strip() == "ACTION Advance"
    assert "bDirection" in (action.implementation or "")


def test_unit_ids_are_stable():
    snap = build_compat_snapshot(fixture_project_view())
    ids = [u.id for u in snap.units]
    assert ids == sorted(ids)  # deterministic order
    assert len(ids) == len(set(ids))  # unique


def test_unknown_but_parseable_xml_is_not_an_error(tmp_path):
    """A parseable XML that is simply not a supported analysis type must
    stay silent: only a document the parser could not read counts as a gap.
    """
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "sub"))
    with open(os.path.join(root, "sub", "Unrelated.xml"), "w", encoding="utf-8") as fh:
        fh.write("<Foo><Bar>hello</Bar></Foo>\n")
    snap = build_compat_snapshot(root)
    assert snap.source_errors == []
    assert snap.diagnostics == []
    assert not any(u.kind == K.VISUALIZATION for u in snap.units)


def test_codesys_native_task_archives_are_classified_as_task_config(tmp_path):
    root = str(tmp_path / "project-view")
    task_dir = os.path.join(root, "Application", "Task Configuration")
    os.makedirs(task_dir)
    with open(os.path.join(task_dir, "Fast.xml"), "w", encoding="utf-8") as fh:
        fh.write(
            '<Single Type="{task}">'
            '<Single Name="Object">'
            '<List Name="PouList"><Single Name="Name" Type="string">Main</Single></List>'
            "</Single></Single>"
        )

    snap = build_compat_snapshot(root)
    task = snap.find_unit("Application/Task Configuration/Fast.xml#Fast")
    assert task is not None
    assert task.kind == K.TASK_CONFIG


def test_unparsable_xml_is_a_source_error(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "HMI"))
    with open(os.path.join(root, "HMI", "Broken.xml"), "w", encoding="utf-8") as fh:
        fh.write('<Visualization>\n  <Single Name="x">\n')
    snap = build_compat_snapshot(root)
    assert len(snap.source_errors) == 1
    record = snap.source_errors[0]
    assert record.source_kind == K.VISUALIZATION
    assert record.location.path == "HMI/Broken.xml"
    assert "cannot parse" in record.message
