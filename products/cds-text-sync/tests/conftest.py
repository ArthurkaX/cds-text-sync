"""Bootstrap for sync-product compatibility tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "src",
    ROOT.parent / "cds-static-analyzer" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


@pytest.fixture(autouse=True)
def _isolate_user_defaults(tmp_path_factory, monkeypatch):
    """Keep the real per-user defaults file out of the test run."""
    config_home = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("APPDATA", str(config_home))
    yield config_home
