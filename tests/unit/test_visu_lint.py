"""Machine-only visu XML lint is independent from the human analyzer."""

import json

from analyze_helpers import fixture_path, run_cli
from cds_text_sync.visu_lint.dead_explicit_color import lint


def test_visu_lint_flags_generated_dead_explicit_color():
    path = fixture_path("project-view", "Runtime", "PLC Logic", "Application", "HMI", "Screen1.xml")
    findings = lint(open(path, encoding="utf-8").read(), path="Screen1.xml")
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "VISU001"
    assert findings[0]["location"]["line"] == 15


def test_visu_lint_cli_is_json_only_machine_contract():
    path = fixture_path("project-view", "Runtime", "PLC Logic", "Application", "HMI", "Screen1.xml")
    code, out, _err = run_cli(["visu-lint", "--xml", path])
    report = json.loads(out)
    assert code == 1
    assert report["ok"] is False
    assert report["findings"][0]["rule_id"] == "VISU001"


def test_machine_linter_has_no_dependency_on_human_analyzer():
    import cds_text_sync.visu_lint.dead_explicit_color as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "cds_static_analyzer" not in source
