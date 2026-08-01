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
