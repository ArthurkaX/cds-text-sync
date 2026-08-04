"""Tests for the optional UI adapter; pywebview itself is not required."""

from __future__ import annotations

from analyze_helpers import copy_fixture
from cds_text_sync.ui import AnalyzerApi, analyze_workspace


def test_ui_adapter_runs_existing_analyzer(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)

    response = analyze_workspace(root)

    assert response["ok"] is True
    assert response["workspace"] == root
    assert response["result"]["schema_version"] == 1
    assert response["result"]["findings"]
    assert all(item["rule_id"] != "VISU001" for item in response["result"]["findings"])


def test_ui_adapter_returns_workspace_error_as_data(tmp_path):
    response = analyze_workspace(str(tmp_path / "missing"))

    assert response["ok"] is False
    assert "workspace directory not found" in response["error"]


def test_open_file_rejects_path_outside_project_view(tmp_path):
    api = AnalyzerApi()
    api._last_project_view = str(tmp_path)

    response = api.open_file("../outside.st")

    assert response["ok"] is False
    assert response["error"] == "Invalid source path."


def test_open_file_accepts_optional_line(tmp_path, monkeypatch):
    source = tmp_path / "Main.st"
    source.write_text("PROGRAM Main\n", encoding="utf-8")
    api = AnalyzerApi()
    api._last_project_view = str(tmp_path)
    calls = []
    monkeypatch.setattr("cds_text_sync.ui.subprocess.Popen", lambda args, **_: calls.append(args))

    response = api.open_file("Main.st", 7)

    assert response == {"ok": True, "opened_at_line": 7}
    assert calls and calls[0][0:2] == ["code", "-g"]


def test_rules_catalog_contains_only_human_analyzer_rules(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    response = AnalyzerApi().rules(root)
    assert response["ok"] is True
    assert {rule["id"] for rule in response["rules"]} == {
            "CTS0001", "CTS0002", "CTS0003", "CTS0004", "CTS0006", "CTS0007", "CTS0008", "CTS0009", "CTS0010", "CTS0011", "CTS0012", "CTS0013", "CTS0014", "CTS0015", "CTS0016", "CTS0017", "CTS0018", "CTS0019", "CTS0020", "CTS0021", "CTS0022", "CTS0023", "CTS0024", "CTS0025", "CTS0026", "CTS0027", "CTS0028", "CTS0029", "CTS0030", "CTS0031"
    }
    assert all("documentation" in rule for rule in response["rules"])


def test_rule_switch_is_saved_to_project_config(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    response = AnalyzerApi().set_rule_enabled(root, "CTS0001", False)
    assert response["ok"] is True
    config = (tmp_path / "sync" / "cts-analyze.toml").read_text(encoding="utf-8")
    assert "[rules.CTS0001]" in config
    assert "enabled = false" in config


def test_suppression_entry_is_copyable_without_writing_state():
    response = AnalyzerApi().suppression_entry(
        {"fingerprint": "cts1:abc", "rule_id": "CTS0001", "unit_id": "Main"}
    )
    assert response["ok"] is True
    assert 'fingerprint = "cts1:abc"' in response["text"]
    assert 'reason = "TODO:' in response["text"]


def test_ui_triage_uses_canonical_suppression_state(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    response = analyze_workspace(root)
    finding = response["result"]["findings"][0]

    applied = AnalyzerApi().triage(root, finding, "suppress", "accepted for legacy code")

    assert applied["ok"] is True
    text = (tmp_path / "sync" / ".cts-analyze" / "suppressions.toml").read_text(
        encoding="utf-8"
    )
    assert finding["fingerprint"] in text


def test_ui_bulk_triage_applies_one_decision_to_group(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    findings = analyze_workspace(root)["result"]["findings"][:2]

    applied = AnalyzerApi().triage_many(root, findings, "fix-later", "group review")

    assert applied["ok"] is True
    assert applied["summary"]["fix_later"] == 2
