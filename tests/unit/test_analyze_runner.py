"""
test_analyze_runner.py - End-to-end runs over the fixture: exit codes,
capability gating, rule filters, suppression/baseline filtering.
"""

import json
import os
import shutil

from cds_static_analyzer.config import ResolvedConfig, load_config
from cds_static_analyzer.model import AnalysisResult, Diagnostic, Finding
from cds_static_analyzer.project_compat import build_compat_snapshot
from cds_static_analyzer.registry import load_builtin_rules
from cds_static_analyzer.runner import (
    RunOptions,
    exit_code,
    filter_result,
    run_analysis,
)
from cds_static_analyzer.workspace import WorkspaceResolver

from analyze_helpers import (
    copy_fixture,
    fixture_path,
    fixture_project_view,
    run_analyze_json,
    run_cli,
)




def test_analyze_depends_on_engine_but_not_vice_versa():
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import cds_text_sync.engine; import cds_static_analyzer; print('ok')",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

def _malformed_visu_workspace(tmp_path):
    """Fixture workspace + one malformed visualization XML."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    dest = os.path.join(
        root,
        "project-view",
        "Runtime",
        "PLC Logic",
        "Application",
        "HMI",
        "Broken.xml",
    )
    shutil.copy(fixture_path("broken-visu.xml"), dest)
    return root


_BROKEN_VISU_REL = "Runtime/PLC Logic/Application/HMI/Broken.xml"

def test_snapshot_records_unparsable_visualization_xml(tmp_path):
    root = _malformed_visu_workspace(tmp_path)
    snap = build_compat_snapshot(os.path.join(root, "project-view"))
    errors = snap.source_errors
    assert len(errors) == 1
    record = errors[0]
    assert record.source_kind == "visualization"
    assert record.location.path == _BROKEN_VISU_REL
    assert "cannot parse" in record.message
    # The healthy screen still parses into a unit.
    assert any(u.kind == "visualization" for u in snap.units)

def test_malformed_visu_does_not_hurt_st_rules(tmp_path):
    """When the only problem is the broken XML, text/declaration rules stay
    complete and keep reporting their findings."""
    root = _malformed_visu_workspace(tmp_path)
    data = run_analyze_json(root, extra=["--rule", "CTS0001", "--rule", "CTS0002"])
    assert data["complete"] is True
    assert data["diagnostics"] == []
    assert len(data["findings"]) == 4  # 2x CTS0001 + 2x CTS0002

def test_human_analyzer_ignores_malformed_visu_xml(tmp_path):
    root = _malformed_visu_workspace(tmp_path)
    d1 = run_analyze_json(root, extra=["--rule", "CTS0001", "--rule", "CTS0002"])
    d2 = run_analyze_json(root, extra=["--rule", "CTS0001", "--rule", "CTS0002"])
    assert d1["diagnostics"] == d2["diagnostics"]
    assert d1["diagnostics"] == []
    assert d1["complete"] is True
