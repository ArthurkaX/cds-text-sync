"""Tests for the local documentation bundle generator."""

import json

from cds_text_sync import docgen


def test_generate_docs_separates_project_and_library_sources(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    libraries = tmp_path / "codesys"
    project.mkdir(parents=True)
    libraries.mkdir()
    (project / "Main.st").write_text(
        "\ufeffPROGRAM Main\nVAR\n    x : INT;\nEND_VAR\nx := 1;\n",
        encoding="utf-8",
    )
    (libraries / "Standard.xml").write_text(
        "<library>\n  <FUNCTION_BLOCK FB_Standard />\n</library>\n",
        encoding="utf-8",
    )

    result = docgen.generate_docs(workspace, library_path=libraries)
    output = workspace / ".cts-docs"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (output / "symbols.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["ok"] is True
    assert result["output"] == str(output)
    assert manifest["counts"] == {
        "files": 2,
        "project_files": 1,
        "library_files": 1,
        "declarations": 2,
    }
    assert manifest["library_path_exists"] is True
    assert {record["source"] for record in records} == {"project", "library"}
    assert all("text" not in record for record in records)
    bundle = (output / "bundle.md").read_text(encoding="utf-8")
    assert "project: `Main.st`" in bundle
    assert "library: `Standard.xml`" in bundle
    assert "PROGRAM Main" in bundle
    assert "FUNCTION_BLOCK FB_Standard" in bundle


def test_generate_docs_accepts_project_view_and_missing_default_library(tmp_path, monkeypatch):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "Types.st").write_text("TYPE TState : INT; END_TYPE\n", encoding="utf-8")
    missing = tmp_path / "missing-libraries"
    monkeypatch.setattr(docgen, "DEFAULT_LIBRARY_PATH", missing)

    result = docgen.generate_docs(project_view)
    manifest = json.loads(
        (project_view.parent / ".cts-docs" / "manifest.json").read_text(encoding="utf-8")
    )

    assert result["ok"] is True
    assert manifest["project_view"] == str(project_view)
    assert manifest["library_path_exists"] is False
    assert manifest["counts"]["project_files"] == 1
    assert manifest["counts"]["library_files"] == 0
