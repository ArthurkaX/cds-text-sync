"""Unit tests for the FSM pywebview bridge (cds_text_sync.fsm.api).

The API owns a ``Scanner`` that is rebuilt whenever the workspace changes.
Every test here drives the bridge exactly as the page would, without ever
opening a window: scans run inline (``max_workers=1``) so no process pool is
spawned, matching the convention of ``test_fsm_scanner.py``.
"""

import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from cds_text_sync.engine.variable_map import ST_IMPLEMENTATION_MARKER
from cds_text_sync.fsm import scanner as scanner_mod
from cds_text_sync.fsm.api import FsmApi
from cds_text_sync.fsm.model import STATE_FSM
from cds_text_sync.fsm.scanner import Scanner


FSM_ST = (
    "PROGRAM Motor\n"
    "VAR\n"
    "  state : INT;\n"
    "  start : BOOL;\n"
    "  done : BOOL;\n"
    "END_VAR\n"
    + ST_IMPLEMENTATION_MARKER + "\n"
    "CASE state OF\n"
    "  0: IF start THEN state := 1; END_IF\n"
    "  1: IF done THEN state := 2; END_IF\n"
    "  2: state := 0;\n"
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
    """project-view with one FSM file and one plain (no-machine) file."""
    view = tmp_path / "project-view"
    _write(view / "Motor.st", FSM_ST)
    _write(view / "Plain.st", PLAIN_ST)
    return tmp_path


class _InlineScanner(Scanner):
    """Scanner forced to one worker so unit tests never spawn a process pool."""

    def __init__(self, workspace, budget_seconds=10.0, max_workers=None):
        super().__init__(workspace, budget_seconds=budget_seconds, max_workers=1)


@pytest.fixture
def api_cls(monkeypatch):
    """FsmApi whose Scanner always runs scans inline."""
    monkeypatch.setattr("cds_text_sync.fsm.api.Scanner", _InlineScanner)
    return FsmApi


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_returns_ok_and_paths(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        payload = api.bootstrap()
        assert payload["ok"] is True
        assert payload["error"] is None
        assert payload["workspace"] == str(tmp_path.resolve())
        assert payload["source_root"] == str((tmp_path / "project-view").resolve())
        assert [entry["path"] for entry in payload["files"]] == ["Motor.st", "Plain.st"]
        assert payload["snapshot"]["state"] == "unknown"  # no manifest written
    finally:
        api.close()


def test_bootstrap_nonexistent_workspace_is_ok_false(tmp_path):
    api = FsmApi(str(tmp_path / "does-not-exist"))
    try:
        payload = api.bootstrap()
        assert payload == {"ok": False, "error": payload["error"]}
        assert isinstance(payload["error"], str) and payload["error"]
    finally:
        api.close()


def test_set_workspace_switches_roots(tmp_path, api_cls):
    first = _workspace(tmp_path)
    second = tmp_path / "other"
    _write(second / "project-view" / "Nested" / "Pump.st", FSM_ST)

    api = api_cls(str(first))
    try:
        boot = api.bootstrap()
        assert boot["ok"] is True
        assert [entry["path"] for entry in boot["files"]] == ["Motor.st", "Plain.st"]

        switched = api.set_workspace(str(second))
        assert switched["ok"] is True
        assert switched["workspace"] == str(second.resolve())
        assert [entry["path"] for entry in switched["files"]] == ["Nested/Pump.st"]

        refresh = api.refresh_workspace()
        assert refresh["ok"] is True
        assert [entry["path"] for entry in refresh["files"]] == ["Nested/Pump.st"]
    finally:
        api.close()


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------


def test_full_scan_loop_reaches_completed(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        assert api.bootstrap()["ok"] is True

        started = api.start_scan()
        assert started["ok"] is True
        assert started["error"] is None
        assert started["total"] == 2

        job_id = started["job_id"]
        cursor = 0
        poll = None
        # poll_scan returns only what is past the cursor, so the events have to
        # be accumulated: whether both land in one poll or one each is a race.
        events = []
        for _ in range(500):
            poll = api.poll_scan(job_id, cursor)
            assert poll["ok"] is True
            cursor = poll["cursor"]
            events.extend(poll["events"])
            if poll["state"] in ("completed", "cancelled", "failed"):
                break
            time.sleep(0.01)

        assert poll["state"] == "completed"
        assert poll["total"] == 2
        assert poll["completed"] == 2
        assert poll["hits"] == 1
        assert poll["errors"] == 0
        assert len(events) == 2
        assert [event["path"] for event in events] == ["Motor.st", "Plain.st"]
        assert event_states(events) == [STATE_FSM, "none"]
    finally:
        api.close()


def test_cancel_scan_cancels_a_running_job(tmp_path, api_cls, monkeypatch):
    workspace = _workspace(tmp_path)
    view = workspace / "project-view"
    # Extra files keep the job alive until the cancel call lands.
    for index in range(10):
        _write(view / f"Extra{index}.st", FSM_ST)

    api = api_cls(str(workspace))
    try:
        api.bootstrap()
        release = threading.Event()
        original = scanner_mod._analyze_worker

        def blocking_worker(path_text, relative=None):
            if relative == "Motor.st":
                release.wait(30.0)
            return original(path_text, relative=relative)

        monkeypatch.setattr(scanner_mod, "_analyze_worker", blocking_worker)

        started = api.start_scan()
        job_id = started["job_id"]
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if api.poll_scan(job_id)["state"] == "running":
                break
            time.sleep(0.01)

        cancelled = api.cancel_scan(job_id)
        assert cancelled["ok"] is True
        assert cancelled["error"] is None
        release.set()

        result = _wait_terminal(api, job_id)
        assert result["ok"] is True
        assert result["state"] == "cancelled"
    finally:
        api.close()


def test_cancel_scan_unknown_job_is_ok_false(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        result = api.cancel_scan("does-not-exist")
        assert result["ok"] is False
        assert result["error"]
        assert "error" in result
    finally:
        api.close()


# ---------------------------------------------------------------------------
# analyze_file
# ---------------------------------------------------------------------------


def test_analyze_file_good_and_missing(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()

        good = api.analyze_file("Motor.st")
        assert good["ok"] is True
        assert good["error"] is None
        assert good["state"] == STATE_FSM
        assert good["machines"]

        missing = api.analyze_file("Nope.st")
        assert missing["ok"] is False
        assert missing["error"]
        assert missing["machines"] == []
    finally:
        api.close()


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_svg_data_transition_matches_transitions(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        result = api.render("Motor.st")
        assert result["ok"] is True
        assert result["error"] is None
        assert result["path"] == "Motor.st"
        assert result["machine"] == 0
        assert result["count"] == 1
        assert result["svg"]
        assert result["mermaid"].startswith("stateDiagram-v2")
        assert result["plantuml"].startswith("@startuml")
        assert result["summary"] == {
            "selector": "state",
            "state_count": 3,
            "transition_count": 3,
            "deferred": False,
            "numeric": True,
        }
        assert result["warnings"] == []

        # The transition rows are in payload order with payload indices, so
        # they line up exactly with the data-transition the SVG emits.
        expected = {row["index"] for row in result["transitions"]}
        assert expected == {0, 1, 2}

        root = ET.fromstring(result["svg"])
        svg_indices = {
            int(element.attrib["data-transition"])
            for element in root.iter()
            if "data-transition" in element.attrib
        }
        assert svg_indices == expected
    finally:
        api.close()


def test_render_file_with_no_fsm_is_ok_count_zero(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        result = api.render("Plain.st")
        assert result["ok"] is True
        assert result["error"] is None
        assert result["count"] == 0
        assert result["svg"] == ""
        assert result["mermaid"] == ""
        assert result["plantuml"] == ""
        assert result["summary"] is None
        assert result["warnings"] == []
        assert result["transitions"] == []
    finally:
        api.close()


def test_render_out_of_range_machine_index_is_ok_false(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        result = api.render("Motor.st", machine=5)
        assert result["ok"] is False
        assert "out of range" in result["error"]

        negative = api.render("Motor.st", machine=-1)
        assert negative["ok"] is False

        non_int = api.render("Motor.st", machine="nope")
        assert non_int["ok"] is False
    finally:
        api.close()


def test_render_missing_file_is_ok_false(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        result = api.render("Nope.st")
        assert result["ok"] is False
        assert result["error"]
    finally:
        api.close()


# ---------------------------------------------------------------------------
# status / dialogs
# ---------------------------------------------------------------------------


def test_progress_returns_snapshot(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        idle = api.progress()
        assert idle["running"] is False
        assert idle["total"] == 0

        api.bootstrap()
        after = api.progress()
        assert after["running"] is False
        assert after["phase"] == "idle"
        assert after["total"] == 2
    finally:
        api.close()


def test_choose_workspace_returns_dict(monkeypatch):
    api = FsmApi("")
    try:
        monkeypatch.setattr(
            "cds_text_sync.fsm.api.shell.choose_folder", lambda: r"C:\picked"
        )
        assert api.choose_workspace() == {
            "ok": True,
            "workspace": r"C:\picked",
            "error": None,
        }

        # A cancelled dialog is ok=True with an empty workspace.
        monkeypatch.setattr("cds_text_sync.fsm.api.shell.choose_folder", lambda: "")
        cancelled = api.choose_workspace()
        assert cancelled == {"ok": True, "workspace": "", "error": None}

        def boom():
            raise RuntimeError("dialog failed")

        monkeypatch.setattr("cds_text_sync.fsm.api.shell.choose_folder", boom)
        failed = api.choose_workspace()
        assert failed["ok"] is False
        assert failed["error"]
    finally:
        api.close()


def test_invalid_workspace_all_bridge_methods_return_dicts(tmp_path):
    api = FsmApi(str(tmp_path / "does-not-exist"))
    try:
        boot = api.bootstrap()
        assert set(boot) == {"ok", "error"}
        assert boot["ok"] is False
        assert boot["error"]

        payloads = [
            api.set_workspace(str(tmp_path / "also-missing")),
            api.refresh_workspace(),
            api.start_scan(),
            api.poll_scan("no-such-job"),
            api.cancel_scan("no-such-job"),
            api.analyze_file("Motor.st"),
            api.render("Motor.st"),
            api.progress(),
        ]
        for payload in payloads:
            assert isinstance(payload, dict)
    finally:
        api.close()


def test_close_twice_is_safe(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    api.bootstrap()
    api.close()
    api.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def event_states(events):
    return [event["state"] for event in events]


def _wait_terminal(api, job_id, timeout=30.0):
    """Poll until the job leaves the running state; fail loudly on timeout."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = api.poll_scan(job_id)
        if last["state"] in ("completed", "cancelled", "failed"):
            return last
        time.sleep(0.01)
    raise AssertionError(
        f"scan did not finish within {timeout}s (last state: {last['state'] if last else None})"
    )


# ---------------------------------------------------------------------------
# source: the code behind a step and behind a transition
# ---------------------------------------------------------------------------


def test_source_of_a_state_is_its_branch_body(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        result = api.source("Motor.st", 0, "state", "0")
        assert result["ok"] is True
        assert result["kind"] == "state"
        assert result["title"] == "0"
        assert result["block"] is True
        assert result["code"] == "0: IF start THEN state := 1; END_IF"
        # The file line, not the offset into the implementation section: the
        # declaration and the marker are seven lines, so the CASE head is on
        # line 8 and the first branch on line 9.
        assert result["line"] == 9
    finally:
        api.close()


def test_source_of_a_transition_is_the_arm_it_fires_inside(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        rows = api.render("Motor.st")["transitions"]
        guarded = next(row for row in rows if row["guard"] == "done")
        result = api.source("Motor.st", 0, "transition", guarded["index"])
        assert result["ok"] is True
        assert result["kind"] == "transition"
        assert result["title"] == "1 → 2"
        assert result["subtitle"] == "done"
        # The whole arm, so actions that run with the transition are visible
        # and not just the assignment the guard text implies.
        assert result["block"] is True
        assert result["code"] == "IF done THEN state := 2;"
        assert result["line"] == 10
    finally:
        api.close()


def test_source_of_an_unconditional_transition_falls_back_to_the_statement(
    tmp_path, api_cls
):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        rows = api.render("Motor.st")["transitions"]
        plain = next(row for row in rows if row["guard"] == "")
        result = api.source("Motor.st", 0, "transition", plain["index"])
        assert result["ok"] is True
        assert result["block"] is False
        assert result["code"] == "state := 0;"
    finally:
        api.close()


def test_source_rejects_unknown_keys_and_kinds(tmp_path, api_cls):
    api = api_cls(str(_workspace(tmp_path)))
    try:
        api.bootstrap()
        assert api.source("Motor.st", 0, "banana", "0")["ok"] is False
        assert api.source("Motor.st", 0, "state", "nope")["ok"] is False
        assert api.source("Motor.st", 0, "transition", 99)["ok"] is False
        assert api.source("Motor.st", 7, "state", "0")["ok"] is False
        # Traversal is the Scanner's rule and it still holds on this path.
        assert api.source("../outside.st", 0, "state", "0")["ok"] is False
    finally:
        api.close()
