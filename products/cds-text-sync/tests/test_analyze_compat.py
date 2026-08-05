"""Sync-owned tests for the legacy analyzer XML compatibility adapter."""

from cds_text_sync import analyze_compat


def test_adapter_exports_only_compatibility_builder():
    assert analyze_compat.__all__ == ["build_compat_snapshot"]


def test_adapter_builds_visualization_unit(tmp_path):
    source = tmp_path / "Screen.xml"
    source.write_text("<Visualization><Single Name='Screen' /></Visualization>", encoding="utf-8")

    snapshot = analyze_compat.build_compat_snapshot(str(tmp_path))

    assert [unit.kind for unit in snapshot.units] == ["visualization"]
    assert snapshot.units[0].qualified_name == "Screen"


def test_adapter_keeps_st_and_xml_compatibility_projection(tmp_path):
    (tmp_path / "Main.st").write_text("PROGRAM Main\n", encoding="utf-8")
    (tmp_path / "Screen.xml").write_text("<Visualization />", encoding="utf-8")

    snapshot = analyze_compat.build_compat_snapshot(str(tmp_path))

    assert {unit.source_path for unit in snapshot.units} == {"Main.st", "Screen.xml"}
