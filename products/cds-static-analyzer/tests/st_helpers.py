"""ST-only analyzer product fixtures."""

from __future__ import annotations

from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "analyze"


def fixture_path(*parts):
    return str(FIXTURE_DIR.joinpath(*parts))


def fixture_project_view():
    return fixture_path("project-view")
