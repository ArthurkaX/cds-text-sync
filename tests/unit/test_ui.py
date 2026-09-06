"""Tests for the optional UI adapter; pywebview itself is not required."""

from __future__ import annotations

from pathlib import Path

from analyze_helpers import copy_fixture
from cds_text_sync.ui import AnalyzerApi, analyze_workspace


def test_ui_adapter_runs_existing_analyzer(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)

    response = analyze_workspace(root)

    assert response["ok"] is True
    assert response["workspace"] == root
    assert response["result"]["schema_version"] == 1
    assert response["result"]["summary"]["files"] > 0
    assert response["result"]["findings"]
    assert all(item["rule_id"] != "VISU001" for item in response["result"]["findings"])
    assert all("fixable" in item for item in response["result"]["findings"])


def test_ui_adapter_returns_workspace_error_as_data(tmp_path):
    response = analyze_workspace(str(tmp_path / "missing"))

    assert response["ok"] is False
    assert "workspace directory not found" in response["error"]


def test_ui_initial_state_exposes_analyzer_version():
    state = AnalyzerApi("C:/project").initial_state()

    assert state["workspace"] == "C:/project"
    assert state["analyzer_version"]


def test_ui_launch_uses_environment_workspace_fallback(monkeypatch):
    monkeypatch.setenv("CTS_INITIAL_WORKSPACE", "C:/from-codesys")

    import cds_text_sync.ui as ui

    assert ui._resolve_initial_workspace() == "C:/from-codesys"
    assert ui._resolve_initial_workspace("C:/explicit") == "C:/explicit"


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


def test_open_file_rejects_disallowed_extensions(tmp_path):
    api = AnalyzerApi()
    api._last_project_view = str(tmp_path)

    for disallowed in ("malicious.bat", "run.cmd", "app.exe", "shortcut.lnk", "doc.txt"):
        f = tmp_path / disallowed
        f.write_text("dummy", encoding="utf-8")
        res = api.open_file(disallowed)
        assert res["ok"] is False
        assert "Invalid source file type" in res["error"]


def test_open_file_accepts_st_and_xml_case_insensitively(tmp_path, monkeypatch):
    api = AnalyzerApi()
    api._last_project_view = str(tmp_path)
    calls = []
    monkeypatch.setattr("cds_text_sync.ui.os.startfile", lambda path: calls.append(path), raising=False)

    for allowed in ("POU.st", "DATA.ST", "screen.xml", "VISU.XML"):
        f = tmp_path / allowed
        f.write_text("content", encoding="utf-8")
        res = api.open_file(allowed)
        assert res["ok"] is True


def test_source_context_is_limited_to_st_files_and_project_view(tmp_path):
    source = tmp_path / "Main.st"
    source.write_text("PROGRAM Main\nvalue := 1;\nEND_PROGRAM\n", encoding="utf-8")
    api = AnalyzerApi()
    api._last_project_view = str(tmp_path)

    response = api.source_context("Main.st", 2, radius=1)

    assert response["ok"] is True
    assert response["lines"] == [
        {"number": 1, "text": "PROGRAM Main", "hot": False},
        {"number": 2, "text": "value := 1;", "hot": True},
        {"number": 3, "text": "END_PROGRAM", "hot": False},
    ]
    assert api.source_context("../outside.st", 1)["error"] == "Invalid source path."
    assert api.source_context("notes.txt", 1)["error"] == (
        "Only .st source context is available."
    )


def test_source_context_repairs_obvious_mojibake_in_exported_comments(tmp_path):
    source = tmp_path / "Main.st"
    comment = "// Массив данных Расходомеров"
    corrupted = comment.encode("utf-8").decode("latin-1")
    corrupted = corrupted.encode("utf-8").decode("utf-8")
    source.write_text("PROGRAM Main\n" + corrupted + "\nEND_PROGRAM\n", encoding="utf-8")
    api = AnalyzerApi()
    api._last_project_view = str(tmp_path)

    response = api.source_context("Main.st", 2, radius=1)

    assert response["ok"] is True
    assert response["lines"][1]["text"] == comment


def test_rules_catalog_contains_only_human_analyzer_rules(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    response = AnalyzerApi().rules(root)
    assert response["ok"] is True
    from cds_static_analyzer.registry import load_builtin_rules

    assert {rule["id"] for rule in response["rules"]} == set(load_builtin_rules())
    assert all("documentation" in rule for rule in response["rules"])
    assert next(rule for rule in response["rules"] if rule["id"] == "CTS0007")["fixable"] is True
    assert next(rule for rule in response["rules"] if rule["id"] == "CTS0008")["fixable"] is True


def test_cts0008_autofix_requires_preview_and_applies_only_unchanged_source(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    analysis = analyze_workspace(root)
    finding = next(item for item in analysis["result"]["findings"] if item["rule_id"] == "CTS0008")
    api = AnalyzerApi()

    preview = api.autofix_preview(root, finding)

    assert preview["ok"] is True
    assert any(line.startswith("-") for line in preview["diff"])
    assert any(line.startswith("+") for line in preview["diff"])
    applied = api.autofix_apply(root, finding, preview["before_hash"])
    assert applied["ok"] is True

    stale = api.autofix_apply(root, finding, preview["before_hash"])
    assert stale["ok"] is False
    assert "Source changed after the preview" in stale["error"]


def _cts0008_finding(root):
    """Return the first CTS0008 finding; its source line is ``POUs/FB_Conveyor.st``."""
    analysis = analyze_workspace(root)
    return next(item for item in analysis["result"]["findings"] if item["rule_id"] == "CTS0008")


def _cts0008_source(root, finding):
    """Return the ``Path`` of the finding's source file."""
    return Path(root) / "project-view" / finding["location"]["path"]


def test_cts0008_autofix_preserves_crlf_line_endings(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    finding = _cts0008_finding(root)
    target = _cts0008_source(root, finding)
    # Normalize first because Windows checkouts may already be CRLF when
    # core.autocrlf is enabled.
    source_bytes = target.read_bytes().replace(b"\r\n", b"\n")
    crlf = source_bytes.replace(b"\n", b"\r\n")
    target.write_bytes(crlf)
    api = AnalyzerApi()

    preview = api.autofix_preview(root, finding)
    assert preview["ok"] is True
    applied = api.autofix_apply(root, finding, preview["before_hash"])
    assert applied["ok"] is True

    written = target.read_bytes()
    # CRLF survives and the intended alignment fix took effect.
    assert b"\r\n" in written
    assert b"    speed      : INT;" in written
    assert b"\n" not in written.replace(b"\r\n", b"")
    assert b"\r" not in written.replace(b"\r\n", b"")


def test_cts0008_autofix_preserves_utf8_bom(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    finding = _cts0008_finding(root)
    target = _cts0008_source(root, finding)
    target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes())
    api = AnalyzerApi()

    preview = api.autofix_preview(root, finding)
    assert preview["ok"] is True
    applied = api.autofix_apply(root, finding, preview["before_hash"])
    assert applied["ok"] is True

    written = target.read_bytes()
    # The leading BOM is written exactly once and the fix took effect.
    assert written.startswith(b"\xef\xbb\xbf")
    assert written.count(b"\xef\xbb\xbf") == 1
    assert b"    speed      : INT;" in written


def test_cts0008_autofix_preserves_trailing_newline(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    finding = _cts0008_finding(root)
    target = _cts0008_source(root, finding)
    original = target.read_bytes()
    api = AnalyzerApi()

    # No trailing newline on the last line stays missing after apply.
    target.write_bytes(original.rstrip(b"\r\n"))
    preview = api.autofix_preview(root, finding)
    assert preview["ok"] is True
    assert api.autofix_apply(root, finding, preview["before_hash"])["ok"] is True
    written = target.read_bytes()
    assert not written.endswith(b"\n") and not written.endswith(b"\r\n")
    assert b"    speed      : INT;" in written

    # A single trailing newline stays a single trailing newline after apply.
    target.write_bytes(original)
    preview = api.autofix_preview(root, finding)
    assert preview["ok"] is True
    assert api.autofix_apply(root, finding, preview["before_hash"])["ok"] is True
    written = target.read_bytes()
    assert written.endswith(b"\n") and not written.endswith(b"\n\n")
    assert b"    speed      : INT;" in written


def test_cts0008_stale_guard_catches_line_ending_only_edit(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    finding = _cts0008_finding(root)
    target = _cts0008_source(root, finding)
    api = AnalyzerApi()

    preview = api.autofix_preview(root, finding)
    assert preview["ok"] is True

    # An external edit that only flips CRLF <-> LF must invalidate the preview.
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))

    stale = api.autofix_apply(root, finding, preview["before_hash"])
    assert stale["ok"] is False
    assert "Source changed after the preview" in stale["error"]



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


def test_progress_is_idle_outside_a_run():
    assert AnalyzerApi().progress() == AnalyzerApi.IDLE_PROGRESS


def test_progress_hands_out_a_copy():
    """The page polls this on a second thread while ``analyze`` writes; a
    caller must not be able to reach into the record being written."""
    api = AnalyzerApi()
    api._record_progress("rules", 3, 24, "CTS0012")

    snapshot = api.progress()
    snapshot["done"] = 999

    assert api.progress()["done"] == 3


def test_analyze_reports_the_phases_it_runs_then_goes_idle(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    api = AnalyzerApi()
    seen = []
    record = api._record_progress

    def spy(phase, done, total, detail):
        seen.append((phase, done, total))
        record(phase, done, total, detail)

    api._record_progress = spy

    response = api.analyze(root)

    assert response["ok"] is True
    assert [phase for phase, _done, _total in seen if phase == "start"] == ["start"]
    assert {"parse", "prepare", "rules", "finalize"} <= {row[0] for row in seen}
    assert all(done <= total for _phase, done, total in seen if total)
    # Nothing is in flight once the answer is on its way back to the page.
    assert api.progress() == AnalyzerApi.IDLE_PROGRESS


def test_analyze_goes_idle_after_a_failed_run(tmp_path):
    api = AnalyzerApi()

    assert api.analyze(str(tmp_path / "missing"))["ok"] is False
    assert api.progress() == AnalyzerApi.IDLE_PROGRESS
