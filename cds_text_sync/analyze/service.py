"""Canonical analysis orchestration shared by CLI and the desktop UI."""

from __future__ import annotations

from cds_text_sync.analyze import state as state_mod
from cds_text_sync.analyze.config import load_config
from cds_text_sync.analyze.project import build_snapshot
from cds_text_sync.analyze.runner import RunOptions, filter_result, run_analysis
from cds_text_sync.analyze.state import baseline_fingerprints, is_expired
from cds_text_sync.analyze.workspace import WorkspaceResolver


def analyze_resolved(workspace, config, options=None, apply_state=True):
    """Run analysis for an already resolved workspace/config pair."""
    options = options or RunOptions()
    snapshot = build_snapshot(workspace.project_view)
    result = run_analysis(workspace, snapshot, config, options)
    if apply_state:
        state_mod.validate_baseline_schema(workspace.state_dir)
        suppressions = state_mod.read_suppressions(workspace.state_dir)
        baseline, _ = state_mod.read_baseline(workspace.state_dir)
        suppressed = {
            row["fingerprint"] for row in suppressions if not is_expired(row)
        }
        filter_result(result, suppressed, baseline_fingerprints(baseline))
    return workspace, config, result


def analyze(workspace_path, options=None, apply_state=True):
    """Resolve *workspace_path* and run the canonical analysis pipeline."""
    workspace = WorkspaceResolver(workspace=workspace_path).resolve()
    config = load_config(workspace.config_path)
    return analyze_resolved(workspace, config, options, apply_state=apply_state)
