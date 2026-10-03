"""Test bootstrap for the standalone static-analyzer product."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


@pytest.fixture(autouse=True)
def _isolate_user_defaults(tmp_path_factory, monkeypatch):
    """Keep the real per-user defaults file out of the test run."""
    config_home = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("APPDATA", str(config_home))
    yield config_home
