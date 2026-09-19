"""Regression fixtures distilled from the docs review, without project data."""

import json
import os
from pathlib import Path

import pytest

from cds_text_sync import docgen


FIXTURES = Path(__file__).parent / "fixtures" / "docs_review"


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_review_fixtures_are_all_emitted_as_symbols_or_diagnostics(tmp_path):
    project = tmp_path / "project-view"
    project.mkdir()
    for path in FIXTURES.glob("*.st"):
        (project / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    docgen.generate_docs(project, library_path=tmp_path / "libraries")
    output = tmp_path / ".cts-docs"
    symbols = _jsonl(output / "symbols.jsonl")
    diagnostics = _jsonl(output / "diagnostics.jsonl")
    covered = {row["path"] for row in symbols}
    covered.update(row.get("source_ref", {}).get("path") for row in diagnostics)
    assert {path.name for path in project.glob("*.st")} <= covered


def test_review_fixtures_preserve_declarations_comments_and_behavior(tmp_path):
    project = tmp_path / "project-view"
    project.mkdir()
    for path in FIXTURES.glob("*.st"):
        (project / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    docgen.generate_docs(project, library_path=tmp_path / "libraries")
    symbols = _jsonl(tmp_path / ".cts-docs" / "symbols.jsonl")
    by_name = {row["name"]: row for row in symbols}
    assert by_name["ATR_STATE"]["declaration"]["base_type"] == "UINT"
    assert {"qualified_only", "strict"} <= set(by_name["ATR_STATE"]["declaration"]["attributes"])
    assert by_name["DUT_HMI_POSITIONS"]["declaration"]["extends"] == "DUT_BASE"
    assert by_name["DUT_HMI_POSITIONS"]["interface"][0]["comment"] == "horizontal position"
    assert by_name["FB_TIMER"]["behavior"]["status"] in {"extracted", "partial"}
    assert any(fact["kind"] == "timer_call" for fact in by_name["FB_TIMER"]["behavior"]["facts"])


def test_optional_vko_beumer_smoke(tmp_path):
    root = os.environ.get("VKO_BEUMER_PROJECT")
    if not root or not Path(root).is_dir():
        pytest.skip("set VKO_BEUMER_PROJECT to run the optional local smoke test")
    docgen.generate_docs(root, output=tmp_path / ".cts-docs")
    manifest = json.loads((tmp_path / ".cts-docs" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "cts-docs/v3"
    assert (tmp_path / ".cts-docs" / "diagnostics.jsonl").is_file()
