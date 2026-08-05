"""ST-only project snapshot contracts."""

import os

from cds_static_analyzer.project import build_snapshot
from cds_static_analyzer.st import kinds as K


def test_codedys_property_accessors_are_classified_from_filename(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    for suffix in ("Get", "Set"):
        path = os.path.join(root, "POUs", f"FB_Conveyor.Speed.{suffix}.st")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("VAR\nEND_VAR\n\n// --- implementation ---\nvalue := 1;\n")

    snap = build_snapshot(root)
    assert snap.diagnostics == []
    assert snap.find_unit("POUs/FB_Conveyor.Speed.Get.st#FB_Conveyor.Speed.Get").kind == K.PROPERTY_GET
    assert snap.find_unit("POUs/FB_Conveyor.Speed.Set.st#FB_Conveyor.Speed.Set").kind == K.PROPERTY_SET


def test_snapshot_parses_file_directives_once_at_project_boundary(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    path = os.path.join(root, "POUs", "Main.st")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("// cts:ignore-file cts0001 -- generated example\nPROGRAM Main\n")

    snap = build_snapshot(root)
    directives = snap.file_directives["POUs/Main.st"]
    assert directives.rules == frozenset({"CTS0001"})
    assert directives.issues == ()


def test_st_snapshot_normalizes_bom_and_crlf_offsets(tmp_path):
    root = str(tmp_path / "project-view")
    os.makedirs(os.path.join(root, "POUs"))
    path = os.path.join(root, "POUs", "Main.st")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\ufeffPROGRAM Main\r\nIMPLEMENTATION\r\nx := 1;\r\n")

    snap = build_snapshot(root)
    unit = snap.find_unit("POUs/Main.st#Main")
    assert unit is not None
    assert unit.kind == K.PROGRAM
    assert "\ufeff" not in unit.text
    assert "\r" not in unit.text
    assert unit.implementation.startswith("x := 1;")
