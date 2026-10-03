"""Path setup for CLI product tests."""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
for path in (
    ROOT / "products" / "cds-cli" / "src",
    ROOT / "products" / "cds-static-analyzer" / "src",
    ROOT / "products" / "cds-text-sync" / "src",
    ROOT / "tests" / "unit",
):
    path = str(path)
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def _isolate_user_defaults(tmp_path_factory, monkeypatch):
    """Keep the real per-user defaults file out of the test run."""
    config_home = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("APPDATA", str(config_home))
    yield config_home

