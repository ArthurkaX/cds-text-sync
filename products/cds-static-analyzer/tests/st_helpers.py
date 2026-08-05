"""ST-only analyzer product fixtures."""

from __future__ import annotations

from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "analyze"


def fixture_path(*parts):
    return str(FIXTURE_DIR.joinpath(*parts))


def fixture_project_view():
    return fixture_path("project-view")


def run_rule(rule_id, snapshot):
    """Run one analyzer rule over a snapshot through production dispatch."""
    from cds_static_analyzer.config import ResolvedConfig
    from cds_static_analyzer.runner import RunOptions, run_analysis
    from cds_static_analyzer.workspace import Workspace

    result = run_analysis(
        Workspace(root=".", project_view=".", state_dir="."),
        snapshot,
        ResolvedConfig(),
        RunOptions(rule_filter={rule_id}),
    )
    return result.findings
