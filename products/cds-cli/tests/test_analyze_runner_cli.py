"""CLI-facing analyzer runner integration tests."""

import json
import os

from analyze_helpers import copy_fixture, fixture_project_view, run_analyze_json, run_cli


def test_file_ignore_directive_counter_survives_cli_filtering(tmp_path):
    root = copy_fixture(tmp_path)
    source = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write("// cts:ignore-file CTS0001, CTS0002 -- legacy fixture\n" + text)

    data = run_analyze_json(str(root), extra=["--rule", "CTS0001", "--rule", "CTS0002"])

    assert data["_exit"] == 0
    assert data["summary"]["total"] == 0
    assert data["summary"]["suppressed"] == 3
    assert data["summary"]["suppressed_by_directive"] == 3

def test_file_ignore_directive_reports_missing_reason(tmp_path):
    root = copy_fixture(tmp_path)
    source = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write("// cts:ignore-file CTS9999\n" + text)

    data = run_analyze_json(str(root))
    kinds = {item["kind"] for item in data["diagnostics"]}
    assert "directive-missing-reason" in kinds

def test_file_ignore_directive_reports_unknown_rule(tmp_path):
    root = copy_fixture(tmp_path)
    source = os.path.join(root, "project-view", "POUs", "Main.st")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write("// cts:ignore-file CTS9999 -- typo\n" + text)

    data = run_analyze_json(str(root))
    assert any(item["kind"] == "directive-unknown-rule" for item in data["diagnostics"])

def test_cli_json_envelope(tmp_path):
    code, out, err = run_cli(
        ["analyze", "--workspace", fixture_project_view(), "--format", "json"]
    )
    assert code == 1
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert "findings" in data and "diagnostics" in data
    assert data["summary"]["total"] == 30

def test_cli_read_only_no_state_written(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    before = set()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            before.add(os.path.relpath(os.path.join(dirpath, f), root))
    code, out, _err = run_cli(["analyze", "--workspace", root, "--format", "json"])
    after = set()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            after.add(os.path.relpath(os.path.join(dirpath, f), root))
    assert before == after  # the analyzer writes nothing
