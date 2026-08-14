"""Unit tests for the Scanner background scan service (cds_text_sync.fsm.scanner).

The suite runs with ``max_workers=1`` (inline) everywhere except the single
real-process-pool test, so it stays fast and has no process-spawn overhead.
"""

import threading
import time
from pathlib import Path

from cds_text_sync.fsm import scanner as scanner_mod
from cds_text_sync.fsm.model import STATE_ERROR, STATE_FSM

FSM_ST = (
    "FUNCTION_BLOCK Motor\n"
    "// --- implementation ---\n"
    "CASE state OF\n"
    "  IDLE: next_state := RUN;\n"
    "  RUN: next_state := IDLE;\n"
    "END_CASE;\n"
)

PLAIN_ST = (
    "FUNCTION NoMachine : BOOL\n"
    "// --- implementation ---\n"
    "value := 1;\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_workspace(tmp_path) -> Path:
    """Three .st files under project-view: two with an FSM, one plain."""
    view = tmp_path / "project-view"
    _write(view / "Machines" / "Motor.st", FSM_ST)
    _write(view / "Machines" / "Pump.st", FSM_ST)
    _write(view / "Utilities" / "Plain.st", PLAIN_ST)
    return tmp_path


def _wait_done(scanner, job_id, timeout=30.0):
    """Poll until the job leaves the running state; fail loudly on timeout."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = scanner.poll_scan(job_id)
        if last["state"] in ("completed", "cancelled", "failed"):
            return last
        time.sleep(0.01)
    state = last["state"] if last else None
    raise AssertionError(f"scan did not finish within {timeout}s (last state: {state})")


# ---------------------------------------------------------------------------
# start_scan / poll_scan
# ---------------------------------------------------------------------------


def test_start_scan_reaches_completed_with_correct_hits(tmp_path):
    workspace = _make_workspace(tmp_path)
    scanner = scanner_mod.Scanner(workspace, max_workers=1)
    try:
        scanner.bootstrap()
        started = scanner.start_scan()
        assert started["total"] == 3

        result = _wait_done(scanner, started["job_id"])
        assert result["state"] == "completed"
        assert result["total"] == 3
        assert result["completed"] == result["total"]
        assert result["hits"] == 2
        assert result["errors"] == 0
        assert len(result["events"]) == 3
    finally:
        scanner.close()


def test_poll_scan_cursor_returns_only_new_events(tmp_path):
    workspace = _make_workspace(tmp_path)
    scanner = scanner_mod.Scanner(workspace, max_workers=1)
    try:
        scanner.bootstrap()
        started = scanner.start_scan()
        job_id = started["job_id"]

        # Walk the event list while the job may still be running, then finish
        # the walk after completion so no event can arrive unobserved.
        first = scanner.poll_scan(job_id, cursor=0)
        second = scanner.poll_scan(job_id, cursor=first["cursor"])
        done = _wait_done(scanner, job_id)
        assert done["state"] == "completed"
        third = scanner.poll_scan(job_id, cursor=second["cursor"])

        combined = first["events"] + second["events"] + third["events"]
        full = scanner.poll_scan(job_id, cursor=0)
        assert combined == full["events"]
        assert len(combined) == len(full["events"])
        # No duplicates: every event dict appears exactly once in the walk.
        assert len(combined) == len({id(event) for event in combined})

        # A cursor slice returns only the events after the cursor.
        mid = scanner.poll_scan(job_id, cursor=1)
        assert mid["events"] == full["events"][1:]
        assert mid["cursor"] == len(full["events"])
    finally:
        scanner.close()


def test_poll_scan_unknown_job_returns_failed(tmp_path):
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    try:
        result = scanner.poll_scan("does-not-exist")
        assert result["state"] == "failed"
        assert result["job_id"] == "does-not-exist"
        assert result["events"] == []
        assert result["cursor"] == 0
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# cancel_scan
# ---------------------------------------------------------------------------


def test_cancel_scan_cancels_a_running_job(tmp_path, monkeypatch):
    view = tmp_path / "project-view"
    _write(view / "One.st", FSM_ST)
    scanner = scanner_mod.Scanner(tmp_path, budget_seconds=30.0, max_workers=1)
    try:
        scanner.bootstrap()
        release = threading.Event()
        original = scanner_mod._analyze_worker

        def blocking_worker(path_text, relative=None):
            if relative == "One.st":
                release.wait(30.0)
            return original(path_text, relative=relative)

        monkeypatch.setattr(scanner_mod, "_analyze_worker", blocking_worker)

        started = scanner.start_scan()
        job_id = started["job_id"]
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if scanner.poll_scan(job_id)["state"] == "running":
                break
            time.sleep(0.01)

        cancelled = scanner.cancel_scan(job_id)
        assert cancelled["ok"] is True
        release.set()

        result = _wait_done(scanner, job_id)
        assert result["state"] == "cancelled"
    finally:
        scanner.close()


def test_cancel_scan_unknown_job_returns_ok_false(tmp_path):
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    try:
        result = scanner.cancel_scan("does-not-exist")
        assert result["ok"] is False
        assert result["state"] == "failed"
    finally:
        scanner.close()


def test_cancel_scan_finished_job_returns_ok_false(tmp_path):
    workspace = _make_workspace(tmp_path)
    scanner = scanner_mod.Scanner(workspace, max_workers=1)
    try:
        scanner.bootstrap()
        started = scanner.start_scan()
        done = _wait_done(scanner, started["job_id"])
        assert done["state"] == "completed"

        result = scanner.cancel_scan(started["job_id"])
        assert result["ok"] is False
        assert result["state"] == "completed"
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# fingerprint cache
# ---------------------------------------------------------------------------


def test_fingerprint_cache_avoids_reparse(tmp_path, monkeypatch):
    workspace = _make_workspace(tmp_path)
    scanner = scanner_mod.Scanner(workspace, max_workers=1)
    try:
        scanner.bootstrap()
        first = scanner.start_scan()
        _wait_done(scanner, first["job_id"])

        calls = {"n": 0}
        original = scanner_mod._analyze_worker

        def counting_worker(path_text, relative=None):
            calls["n"] += 1
            return original(path_text, relative=relative)

        monkeypatch.setattr(scanner_mod, "_analyze_worker", counting_worker)

        second = scanner.start_scan()
        result = _wait_done(scanner, second["job_id"])
        assert result["state"] == "completed"
        assert result["completed"] == result["total"]
        assert result["hits"] == 2
        # Nothing changed on disk, so every file came from the cache.
        assert calls["n"] == 0
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# refresh_workspace
# ---------------------------------------------------------------------------


def test_refresh_workspace_invalidates_changed_and_removes_deleted(tmp_path, monkeypatch):
    view = tmp_path / "project-view"
    _write(view / "A.st", PLAIN_ST)
    _write(view / "B.st", FSM_ST)
    _write(view / "C.st", PLAIN_ST)
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    try:
        scanner.bootstrap()
        first = scanner.start_scan()
        _wait_done(scanner, first["job_id"])

        # Rewrite B.st (new size and mtime) and delete C.st.
        time.sleep(0.02)
        _write(view / "B.st", PLAIN_ST + "x := 2;\n")
        (view / "C.st").unlink()

        payload = scanner.refresh_workspace()
        paths = [entry["path"] for entry in payload["files"]]
        assert "C.st" not in paths
        assert "A.st" in paths and "B.st" in paths

        calls = {"n": 0}
        original = scanner_mod._analyze_worker

        def counting_worker(path_text, relative=None):
            calls["n"] += 1
            return original(path_text, relative=relative)

        monkeypatch.setattr(scanner_mod, "_analyze_worker", counting_worker)

        second = scanner.start_scan()
        result = _wait_done(scanner, second["job_id"])
        assert result["state"] == "completed"
        assert result["total"] == 2
        assert result["completed"] == 2
        # Only B.st was re-parsed; unchanged A.st came from the cache.
        assert calls["n"] == 1
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# wall-clock budget
# ---------------------------------------------------------------------------


def test_wall_clock_budget_errors_a_wedged_file_but_completes(tmp_path, monkeypatch):
    view = tmp_path / "project-view"
    _write(view / "Wedged.st", FSM_ST)
    _write(view / "GoodOne.st", FSM_ST)
    _write(view / "GoodTwo.st", FSM_ST)
    scanner = scanner_mod.Scanner(tmp_path, budget_seconds=0.15, max_workers=1)
    try:
        scanner.bootstrap()
        original = scanner_mod._analyze_worker

        def slow_worker(path_text, relative=None):
            if relative == "Wedged.st":
                time.sleep(0.4)
            return original(path_text, relative=relative)

        monkeypatch.setattr(scanner_mod, "_analyze_worker", slow_worker)

        started = scanner.start_scan()
        result = _wait_done(scanner, started["job_id"])

        # The job still reaches completed; the wedged file is an error row and
        # the healthy files produced their normal results.
        assert result["state"] == "completed"
        assert result["total"] == 3
        assert result["completed"] == result["total"]
        assert result["errors"] == 1
        assert result["hits"] == 2

        events = {event["path"]: event for event in result["events"]}
        assert events["Wedged.st"]["state"] == STATE_ERROR
        assert events["Wedged.st"]["error"]
        assert events["Wedged.st"]["machines"] == []
        assert events["GoodOne.st"]["state"] == STATE_FSM
        assert events["GoodTwo.st"]["state"] == STATE_FSM
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# analyze_file
# ---------------------------------------------------------------------------


def test_analyze_file_rejects_escape(tmp_path):
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    try:
        result = scanner.analyze_file("../escape.st")
        assert result["state"] == STATE_ERROR
        assert result["error"]
        assert result["machines"] == []
    finally:
        scanner.close()


def test_analyze_file_rejects_missing(tmp_path):
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    try:
        result = scanner.analyze_file("missing.st")
        assert result["state"] == STATE_ERROR
        assert result["error"]
        assert result["machines"] == []
    finally:
        scanner.close()


def test_analyze_file_returns_normal_result(tmp_path):
    view = tmp_path / "project-view"
    _write(view / "Motor.st", FSM_ST)
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    try:
        scanner.bootstrap()
        result = scanner.analyze_file("Motor.st")
        assert result["state"] == STATE_FSM
        assert result["path"] == "Motor.st"
        assert result["error"] is None
        assert result["machines"]
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# real process pool (Windows spawn picklability)
# ---------------------------------------------------------------------------


def test_process_pool_scan_reaches_completed(tmp_path):
    view = tmp_path / "project-view"
    _write(view / "One.st", FSM_ST)
    _write(view / "Two.st", PLAIN_ST)
    _write(view / "Three.st", FSM_ST)
    scanner = scanner_mod.Scanner(tmp_path, max_workers=2)
    try:
        scanner.bootstrap()
        started = scanner.start_scan()
        result = _wait_done(scanner, started["job_id"], timeout=60.0)
        assert result["state"] == "completed"
        assert result["total"] == 3
        assert result["completed"] == result["total"]
        assert result["hits"] == 2
        assert result["errors"] == 0
    finally:
        scanner.close()


# ---------------------------------------------------------------------------
# close / context manager
# ---------------------------------------------------------------------------


def test_close_twice_is_safe(tmp_path):
    scanner = scanner_mod.Scanner(tmp_path, max_workers=1)
    scanner.close()
    scanner.close()


def test_context_manager_form(tmp_path):
    workspace = _make_workspace(tmp_path)
    with scanner_mod.Scanner(workspace, max_workers=1) as scanner:
        scanner.bootstrap()
        started = scanner.start_scan()
        result = _wait_done(scanner, started["job_id"])
        assert result["state"] == "completed"
        assert result["completed"] == result["total"]
        assert result["hits"] == 2
