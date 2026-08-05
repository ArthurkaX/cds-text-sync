"""
test_analyze_staleness.py - The ``project-stale`` Diagnostic.

A ``project-view`` whose ``.dump`` XML mirror is newer than its ``.st``
projection means the IDE side moved ahead of the text we analyse. The reverse
(a locally edited ``.st``) is the normal text-first workflow and is never
reported. Detection is best-effort and must never break a run.
"""

import json
import os

from cds_static_analyzer.config import ResolvedConfig
from cds_static_analyzer.project import build_st_snapshot
from cds_static_analyzer.runner import RunOptions, run_analysis
from cds_static_analyzer.staleness import (
    MTIME_TOLERANCE_SECONDS,
    stale_projections,
    staleness_diagnostic,
)
from cds_static_analyzer.workspace import Workspace

from st_helpers import copy_fixture


def _workspace(tmp_path):
    """A real project-view (the analyze fixture) plus a sync root and .dump."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    ws = Workspace(
        root=root,
        project_view=os.path.join(root, "project-view"),
        state_dir=os.path.join(root, ".cts-analyze"),
    )
    return ws, root


def _set_mtime(path, t):
    os.utime(path, (t, t))


def _write_projection(ws, rel, mtime):
    path = os.path.join(ws.project_view, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("PROGRAM X\nEND_PROGRAM\n")
    _set_mtime(path, mtime)
    return path


def _write_dump_xml(ws, rel, mtime, xml_root=True):
    if xml_root:
        path = os.path.join(ws.root, ".dump", rel)
    else:
        path = os.path.join(ws.project_view, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<Single Name='Object'/>")
    _set_mtime(path, mtime)
    return path


def _write_manifest(ws, entries):
    path = os.path.join(ws.root, ".dump", "manifest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"entries": entries}, fh)
    return path


def test_bare_project_view_without_manifest_is_silent(tmp_path):
    """Analysing a bare project-view with no sync state stays silent."""
    ws, _root = _workspace(tmp_path)
    assert not os.path.exists(os.path.join(ws.root, ".dump", "manifest.json"))
    assert stale_projections(ws) == []
    assert staleness_diagnostic(ws) is None


def test_locally_edited_st_newer_than_xml_is_not_reported(tmp_path):
    """The normal text-first edit (a newer .st) must never be a stale report."""
    ws, _root = _workspace(tmp_path)
    _write_projection(ws, "POUs/A.st", 1000.0)
    _write_dump_xml(ws, "A.xml", 900.0, xml_root=True)
    _write_manifest(
        ws,
        [
            {
                "xml_path": "A.xml",
                "xml_root": "dump",
                "projection_paths": ["POUs/A.st"],
            }
        ],
    )
    assert stale_projections(ws) == []
    assert staleness_diagnostic(ws) is None


def test_xml_newer_than_st_yields_one_diagnostic_naming_path(tmp_path):
    ws, _root = _workspace(tmp_path)
    _write_projection(ws, "POUs/A.st", 1000.0)
    _write_dump_xml(ws, "A.xml", 1000.0 + MTIME_TOLERANCE_SECONDS + 5, xml_root=True)
    _write_manifest(
        ws,
        [
            {
                "xml_path": "A.xml",
                "xml_root": "dump",
                "projection_paths": ["POUs/A.st"],
            }
        ],
    )
    stale = stale_projections(ws)
    assert stale == ["POUs/A.st"]
    diag = staleness_diagnostic(ws)
    assert diag is not None
    assert diag.kind == "project-stale"
    assert "POUs/A.st" in diag.message
    assert "1" in diag.message


def test_more_than_three_stale_files_still_one_diagnostic_with_true_total(tmp_path):
    ws, _root = _workspace(tmp_path)
    xml_t = 1000.0 + MTIME_TOLERANCE_SECONDS + 5
    stale_paths = []
    for i in range(5):
        rel = f"POUs/F{i}.st"
        _write_projection(ws, rel, 1000.0)
        _write_dump_xml(ws, f"F{i}.xml", xml_t, xml_root=True)
        stale_paths.append(rel)
    _write_manifest(
        ws,
        [
            {
                "xml_path": f"F{i}.xml",
                "xml_root": "dump",
                "projection_paths": [f"POUs/F{i}.st"],
            }
            for i in range(5)
        ],
    )
    stale = stale_projections(ws)
    assert len(stale) == 5
    diag = staleness_diagnostic(ws)
    assert diag is not None
    assert diag.kind == "project-stale"
    assert "5" in diag.message
    # Names up to three examples but reports the true total.
    assert "POUs/F0.st" in diag.message
    assert "POUs/F2.st" in diag.message
    # The 4th/5th examples are not all listed, but the true total is.
    assert "5 project-view files" in diag.message


def test_malformed_manifest_is_silent_no_exception(tmp_path):
    ws, _root = _workspace(tmp_path)
    path = os.path.join(ws.root, ".dump", "manifest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("this is not json {")
    assert stale_projections(ws) == []
    assert staleness_diagnostic(ws) is None


def test_unreadable_manifest_is_silent_no_exception(tmp_path):
    ws, _root = _workspace(tmp_path)
    # A directory named manifest.json cannot be read as a file.
    path = os.path.join(ws.root, ".dump", "manifest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{}")
    os.remove(path)
    os.makedirs(path)
    assert stale_projections(ws) == []
    assert staleness_diagnostic(ws) is None


def test_xml_root_dump_resolves_xml_under_dump(tmp_path):
    """``xml_root: "dump"`` (any case) resolves the XML under .dump/, not the
    project-view."""
    ws, _root = _workspace(tmp_path)
    _write_projection(ws, "POUs/A.st", 1000.0)
    _write_dump_xml(ws, "A.xml", 1000.0 + MTIME_TOLERANCE_SECONDS + 5, xml_root=True)
    _write_manifest(
        ws,
        [
            {
                "xml_path": "A.xml",
                "xml_root": "DUMP",
                "projection_paths": ["POUs/A.st"],
            }
        ],
    )
    assert stale_projections(ws) == ["POUs/A.st"]


def test_entries_pointing_at_missing_files_are_skipped(tmp_path):
    ws, _root = _workspace(tmp_path)
    _write_dump_xml(ws, "A.xml", 1000.0 + MTIME_TOLERANCE_SECONDS + 5, xml_root=True)
    _write_manifest(
        ws,
        [
            {
                "xml_path": "Missing.xml",
                "xml_root": "dump",
                "projection_paths": ["POUs/Missing.st"],
            }
        ],
    )
    assert stale_projections(ws) == []
    assert staleness_diagnostic(ws) is None


def test_run_analysis_surfaces_diagnostic_and_sets_complete_false(tmp_path):
    """A stale view flows through the real runner: one project-stale
    Diagnostic and complete=False."""
    ws, _root = _workspace(tmp_path)
    _write_projection(ws, "POUs/A.st", 1000.0)
    _write_dump_xml(ws, "A.xml", 1000.0 + MTIME_TOLERANCE_SECONDS + 5, xml_root=True)
    _write_manifest(
        ws,
        [
            {
                "xml_path": "A.xml",
                "xml_root": "dump",
                "projection_paths": ["POUs/A.st"],
            }
        ],
    )
    snap = build_st_snapshot(ws.project_view)
    config = ResolvedConfig()
    result = run_analysis(ws, snap, config, RunOptions())
    stale = [d for d in result.diagnostics if d.kind == "project-stale"]
    assert len(stale) == 1
    assert "POUs/A.st" in stale[0].message
    assert result.complete is False
    # The aggregate Diagnostic is counted in the summary total.
    assert result.summary.diagnostics == len(result.diagnostics)

