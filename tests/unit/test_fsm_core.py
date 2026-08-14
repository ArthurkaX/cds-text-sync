"""Unit tests for the CPython FSM core package (cds_text_sync.fsm)."""

import json
import time
from pathlib import Path

import pytest

from cds_text_sync.engine.variable_map import ST_IMPLEMENTATION_MARKER, split_decl_impl
from cds_text_sync.fsm import (
    STATE_ERROR,
    STATE_FSM,
    STATE_NONE,
    analyze_path,
    analyze_text,
    bootstrap,
    file_result,
    machine_from_payload,
    machine_payload,
)
from cds_text_sync.fsm.workspace import iter_source_files, resolve_in_root, snapshot
from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_layout import build_layout
from cts_shared.st.fsm_mermaid import to_mermaid


SAMPLE_ST = (
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

MARKERLESS_ST = (
    "PROGRAM MarkerLess\n"
    "VAR\n"
    "  st : INT;\n"
    "END_VAR\n"
    "CASE st OF\n"
    "  0: st := 1;\n"
    "  1: st := 0;\n"
    "END_CASE\n"
)


def _body(text):
    """The section a file scan feeds to find_machines."""
    _decl, impl = split_decl_impl(text)
    return impl if impl is not None else text


def _first_machine(text):
    return next(machine for machine in find_machines(_body(text)) if machine.is_fsm)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_manifest(workspace: Path, created: str) -> None:
    manifest = workspace / ".dump" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"created": created}), encoding="utf-8")


# ---------------------------------------------------------------------------
# machine_payload: anti-regression seam against fsm_search
# ---------------------------------------------------------------------------


def test_machine_payload_matches_fsm_search():
    from cds_text_sync.fsm_search import _machine_payload as legacy_payload

    machine = _first_machine(SAMPLE_ST)
    assert machine_payload(machine) == legacy_payload(machine)
    assert json.loads(json.dumps(machine_payload(machine))) == machine_payload(machine)


def test_machine_from_payload_feeds_layout_and_mermaid():
    machine = _first_machine(SAMPLE_ST)
    adapted = machine_from_payload(machine_payload(machine))

    layout = build_layout(adapted)
    assert layout.width > 0
    assert layout.height > 0

    assert to_mermaid(adapted) == to_mermaid(machine)
    assert to_mermaid(adapted, title="Motor") == to_mermaid(machine, title="Motor")


# ---------------------------------------------------------------------------
# file_result state selection
# ---------------------------------------------------------------------------


def test_file_result_state_selection():
    machines = [{"selector": "state", "states": [], "transitions": []}]
    assert file_result("a.st", machines, error=None)["state"] == STATE_FSM
    assert file_result("a.st", [], error=None)["state"] == STATE_NONE
    assert file_result("a.st", machines, error="boom")["state"] == STATE_ERROR
    assert file_result("a.st", [], error="boom")["state"] == STATE_ERROR

    row = file_result("a.st", machines)
    assert row["path"] == "a.st"
    assert row["error"] is None
    assert row["fingerprint"] is None


def test_package_exports_contract():
    import cds_text_sync.fsm as fsm

    assert fsm.__all__ == [
        "machine_payload",
        "file_result",
        "machine_from_payload",
        "STATE_FSM",
        "STATE_NONE",
        "STATE_ERROR",
        "source_root",
        "bootstrap",
        "analyze_text",
        "analyze_path",
        "layout_payload",
        "to_svg",
        "to_mermaid_text",
    ]


# ---------------------------------------------------------------------------
# iter_source_files sorting
# ---------------------------------------------------------------------------


def test_iter_source_files_sort_is_case_insensitive_and_deterministic(tmp_path):
    # Case-only siblings in one directory would collapse on a case-insensitive
    # Windows volume, so the fixture spreads the cases across directories.
    root = tmp_path / "project-view"
    root.mkdir()
    for rel in ("b.st", "A.st", "nested/c.st", "nested/B.st"):
        _write(root / rel, "x")

    first = [p.relative_to(root).as_posix() for p in iter_source_files(root)]
    second = [p.relative_to(root).as_posix() for p in iter_source_files(root)]
    assert first == second
    assert first == ["A.st", "b.st", "nested/B.st", "nested/c.st"]


# ---------------------------------------------------------------------------
# resolve_in_root
# ---------------------------------------------------------------------------


def test_resolve_in_root_accepts_normal_relative_path(tmp_path):
    root = tmp_path / "project-view"
    root.mkdir()
    _write(root / "One.st", "x")

    resolved = resolve_in_root(root, "One.st")
    assert resolved is not None
    assert resolved == (root / "One.st").resolve()


def test_resolve_in_root_rejects_escapes(tmp_path):
    root = tmp_path / "project-view"
    root.mkdir()

    assert resolve_in_root(root, "../outside.st") is None
    assert resolve_in_root(root, "a/../../outside.st") is None

    outside = tmp_path / "outside.st"
    outside.write_text("x", encoding="utf-8")
    assert resolve_in_root(root, str(outside)) is None


# ---------------------------------------------------------------------------
# snapshot classification
# ---------------------------------------------------------------------------


def test_snapshot_missing_without_project_view(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = snapshot(workspace)
    assert result["state"] == "missing"
    assert result["message"]
    assert result["created"] is None
    assert result["age_seconds"] is None


def test_snapshot_unknown_without_manifest(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "project-view").mkdir(parents=True)

    result = snapshot(workspace)
    assert result["state"] == "unknown"
    assert result["message"]
    assert result["created"] is None
    assert result["age_seconds"] is None


def test_snapshot_fresh_for_a_current_stamp(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "project-view").mkdir(parents=True)
    created = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_manifest(workspace, created)

    result = snapshot(workspace)
    assert result["state"] == "fresh"
    assert result["message"]
    assert result["created"] == created
    assert result["age_seconds"] is not None
    assert "Re-export" not in result["message"]


def test_snapshot_accepts_a_project_view_path_directly(tmp_path):
    # source_root takes a path pointing straight at project-view, so snapshot
    # has to resolve the sync folder the same way or it looks for the manifest
    # one level too deep and calls a healthy workspace "missing".
    workspace = tmp_path / "workspace"
    (workspace / "project-view").mkdir(parents=True)
    created = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_manifest(workspace, created)

    assert snapshot(workspace / "project-view") == snapshot(workspace)
    assert snapshot(workspace / "project-view")["state"] == "fresh"


def test_snapshot_stale_for_an_old_stamp(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "project-view").mkdir(parents=True)
    created = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
    _write_manifest(workspace, created)

    result = snapshot(workspace)
    assert result["state"] == "stale"
    assert result["message"]
    assert result["created"] == created
    assert result["age_seconds"] is not None
    assert "Re-export" in result["message"]


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_returns_sorted_forward_slash_paths(tmp_path):
    workspace = tmp_path / "workspace"
    for rel in ("z.st", "A.st", "nested/B.st"):
        _write(workspace / "project-view" / rel, "x")

    payload = bootstrap(workspace)

    assert payload["workspace"] == str(workspace.resolve())
    assert payload["source_root"] == str((workspace / "project-view").resolve())
    assert [entry["path"] for entry in payload["files"]] == [
        "A.st", "nested/B.st", "z.st",
    ]
    for entry in payload["files"]:
        assert entry["size"] == 1
        assert isinstance(entry["mtime_ns"], int)
    # No manifest was written, so the snapshot is deterministically unknown.
    assert payload["snapshot"]["state"] == "unknown"
    assert payload["snapshot"]["message"]


def test_bootstrap_raises_for_nonexistent_workspace(tmp_path):
    with pytest.raises(ValueError):
        bootstrap(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# analyze_text / analyze_path
# ---------------------------------------------------------------------------


def test_analyze_text_with_marker():
    machines = analyze_text(SAMPLE_ST)
    assert len(machines) == 1
    assert machines[0]["selector"] == "state"
    assert [state["label"] for state in machines[0]["states"]] == ["0", "1", "2"]


def test_analyze_text_without_marker():
    machines = analyze_text(MARKERLESS_ST)
    assert len(machines) == 1
    assert machines[0]["selector"] == "st"


def test_analyze_path_good_file(tmp_path):
    st_path = tmp_path / "Motor.st"
    st_path.write_text(SAMPLE_ST, encoding="utf-8")

    result = analyze_path(str(st_path), relative="Motor.st")
    assert result["state"] == STATE_FSM
    assert result["path"] == "Motor.st"
    assert result["machines"]
    assert result["error"] is None
    assert result["fingerprint"] is not None
    assert set(result["fingerprint"]) == {"size", "mtime_ns"}
    # write_text translates newlines to CRLF on Windows, so compare against
    # the actual on-disk size rather than the in-memory text length.
    assert result["fingerprint"]["size"] == st_path.stat().st_size


def test_analyze_path_uses_path_text_when_no_relative(tmp_path):
    st_path = tmp_path / "One.st"
    st_path.write_text(SAMPLE_ST, encoding="utf-8")

    result = analyze_path(str(st_path))
    assert result["path"] == str(st_path)
    assert result["state"] == STATE_FSM


def test_analyze_path_error_on_directory_or_missing(tmp_path):
    result = analyze_path(str(tmp_path / "nope.st"), relative="nope.st")
    assert result["state"] == STATE_ERROR
    assert result["error"]
    assert result["machines"] == []

    directory = tmp_path / "adir"
    directory.mkdir()
    result = analyze_path(str(directory), relative="adir")
    assert result["state"] == STATE_ERROR
    assert result["error"]
    assert result["machines"] == []
