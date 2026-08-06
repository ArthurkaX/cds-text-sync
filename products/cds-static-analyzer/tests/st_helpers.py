"""ST-only analyzer product fixtures."""

from __future__ import annotations

from pathlib import Path
import shutil


FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "analyze"


def fixture_path(*parts):
    return str(FIXTURE_DIR.joinpath(*parts))


def fixture_project_view():
    return fixture_path("project-view")


def copy_fixture(dest):
    """Copy the analyzer project fixture into a temporary workspace."""
    shutil.copytree(fixture_project_view(), str(Path(dest) / "project-view"))
    return str(dest)


def run_rule(rule_id, snapshot, options=None):
    """Run one analyzer rule over a snapshot through production dispatch.

    ``options`` is a raw per-rule option mapping, applied exactly as a project
    ``cts-analyze.toml`` would apply it - handy for exercising switches such as
    ``merge`` without writing a config file.
    """
    from cds_static_analyzer.config import ResolvedConfig
    from cds_static_analyzer.runner import RunOptions, run_analysis
    from cds_static_analyzer.workspace import Workspace

    config = ResolvedConfig()
    if options:
        config.rule_overrides[rule_id] = {"options": dict(options)}
    result = run_analysis(
        Workspace(root=".", project_view=".", state_dir="."),
        snapshot,
        config,
        RunOptions(rule_filter={rule_id}),
    )
    return result.findings
