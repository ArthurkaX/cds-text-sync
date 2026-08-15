"""test_fsm_cli.py - ``cts fsm`` command surface: scan, show, ui, exit codes."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from analyze_helpers import run_cli


FSM_ST = (
    "PROGRAM Motor\n"
    "VAR\n"
    "  state : INT;\n"
    "  start : BOOL;\n"
    "  done : BOOL;\n"
    "END_VAR\n"
    "// --- implementation ---\n"
    "CASE state OF\n"
    "  0: IF start THEN state := 1; END_IF\n"
    "  1: IF done THEN state := 2; END_IF\n"
    "  2: state := 0;\n"
    "END_CASE\n"
)

PUMP_ST = (
    "PROGRAM Pump\n"
    "VAR\n"
    "  mode : INT;\n"
    "  go : BOOL;\n"
    "END_VAR\n"
    "// --- implementation ---\n"
    "CASE mode OF\n"
    "  0: mode := 1;\n"
    "  1: IF go THEN mode := 0; END_IF\n"
    "END_CASE\n"
)

PLAIN_ST = (
    "FUNCTION NoMachine : BOOL\n"
    "// --- implementation ---\n"
    "value := 1;\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _workspace(tmp_path) -> Path:
    """project-view with one numeric FSM, one plain file, one nested FSM."""
    view = tmp_path / "project-view"
    _write(view / "Motor.st", FSM_ST)
    _write(view / "Plain.st", PLAIN_ST)
    _write(view / "Machines" / "Pump.st", PUMP_ST)
    return tmp_path


def _no_fsm_workspace(tmp_path) -> Path:
    """project-view with one plain file and nothing else."""
    view = tmp_path / "project-view"
    _write(view / "Plain.st", PLAIN_ST)
    return tmp_path


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def test_fsm_scan_json_exits_zero_with_counts(tmp_path):
    code, out, err = run_cli(
        ["fsm", "scan", "--workspace", str(_workspace(tmp_path)), "--json"]
    )
    assert code == 0
    data = json.loads(out)  # exactly one JSON document
    assert data["counts"]["total"] == 3
    assert data["counts"]["completed"] == 3
    assert data["counts"]["hits"] == 2
    assert data["counts"]["errors"] == 0
    assert {row["path"] for row in data["results"]} == {
        "Motor.st", "Plain.st", "Machines/Pump.st",
    }
    assert data["source_root"].endswith("project-view")
    assert "workspace" in data and "snapshot" in data


def test_fsm_scan_text_lists_fsm_paths(tmp_path):
    code, out, err = run_cli(
        ["fsm", "scan", "--workspace", str(_workspace(tmp_path))]
    )
    assert code == 0
    assert "Motor.st" in out
    assert "Machines/Pump.st" in out
    assert "Plain.st" not in out  # no FSM, no line
    assert "Scanned 3 file(s): 2 with FSM, 0 error(s)" in out


def test_fsm_scan_query_filters_case_insensitive(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "scan", "--workspace", str(_workspace(tmp_path)),
            "--query", "MOTOR", "--json",
        ]
    )
    assert code == 0
    data = json.loads(out)
    assert data["counts"]["total"] == 1
    assert [row["path"] for row in data["results"]] == ["Motor.st"]


def test_fsm_scan_no_fsm_workspace_exits_zero(tmp_path):
    code, out, err = run_cli(
        ["fsm", "scan", "--workspace", str(_no_fsm_workspace(tmp_path)), "--json"]
    )
    assert code == 0  # absence is reported in the payload, not the exit status
    data = json.loads(out)
    assert data["counts"]["total"] == 1
    assert data["counts"]["hits"] == 0
    assert data["results"][0]["machines"] == []


def test_fsm_scan_nonexistent_workspace_exits_2(tmp_path):
    code, out, err = run_cli(
        ["fsm", "scan", "--workspace", str(tmp_path / "nope"), "--json"]
    )
    assert code == 2
    assert out == ""
    assert err.strip() != ""


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_fsm_show_json_on_fsm_file(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Motor.st", "--format", "json",
        ]
    )
    assert code == 0
    data = json.loads(out)
    assert data["path"] == "Motor.st"
    assert len(data["machines"]) == 1
    assert data["machines"][0]["selector"] == "state"


def test_fsm_show_json_on_no_fsm_file_exits_zero_with_empty_machines(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Plain.st", "--format", "json",
        ]
    )
    # THE exit-code contract: no FSM is 0, never 1.
    assert code == 0
    data = json.loads(out)
    assert data["machines"] == []
    assert data["state"] == "none"


def test_fsm_show_mermaid(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Motor.st", "--format", "mermaid",
        ]
    )
    assert code == 0
    assert out.startswith("stateDiagram-v2")


def test_fsm_show_svg(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Motor.st", "--format", "svg",
        ]
    )
    assert code == 0
    assert out.lstrip().startswith("<?xml") or out.lstrip().startswith("<svg")
    ET.fromstring(out)  # parses as XML


def test_fsm_show_plantuml(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Motor.st", "--format", "plantuml",
        ]
    )
    assert code == 0
    assert out.startswith("@startuml")
    assert out.rstrip().endswith("@enduml")


def test_fsm_show_traversal_exits_2(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "../escape.st",
        ]
    )
    assert code == 2
    assert out == ""
    assert err.strip() != ""


def test_fsm_show_bad_machine_index_exits_2(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Motor.st", "--machine", "99",
        ]
    )
    assert code == 2
    assert out == ""
    assert err.strip() != ""


def test_fsm_show_mermaid_no_fsm_diagnostic(tmp_path):
    code, out, err = run_cli(
        [
            "fsm", "show", "--workspace", str(_workspace(tmp_path)),
            "--file", "Plain.st", "--format", "mermaid",
        ]
    )
    assert code == 0  # no FSM is not an error
    assert out == ""
    assert err.strip() != ""


# ---------------------------------------------------------------------------
# ui
# ---------------------------------------------------------------------------


def test_fsm_ui_dispatch_calls_launch_with_workspace(monkeypatch, tmp_path):
    import cds_text_sync.fsm.ui as fsm_ui

    calls = []
    monkeypatch.setattr(
        fsm_ui, "launch", lambda workspace: calls.append(workspace) or 0
    )
    code, out, err = run_cli(["fsm", "ui", "--workspace", str(tmp_path)])
    assert code == 0
    assert calls == [str(tmp_path)]
    assert out == ""
    assert err == ""


def test_fsm_ui_propagates_launch_exit_code(monkeypatch, tmp_path):
    import cds_text_sync.fsm.ui as fsm_ui

    monkeypatch.setattr(fsm_ui, "launch", lambda workspace: 2)
    code, out, err = run_cli(["fsm", "ui", "--workspace", str(tmp_path)])
    assert code == 2
    assert out == ""
    assert err == ""  # the monkeypatched launch decides the code on its own


def test_fsm_ui_allows_omitted_workspace_and_project_file(monkeypatch):
    import cds_text_sync.fsm.ui as fsm_ui

    calls = []
    monkeypatch.setattr(
        fsm_ui, "launch", lambda workspace: calls.append(workspace) or 0
    )
    code, out, err = run_cli(["fsm", "ui"])
    assert code == 0
    assert calls == [""]

    code, out, err = run_cli(["fsm", "ui", "--project-file", "x.project"])
    assert code == 0
    assert calls == ["", ""]
