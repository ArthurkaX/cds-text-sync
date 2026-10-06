# -*- coding: utf-8 -*-
"""
conftest.py - Test-tier isolation for the real user profile.

The per-user defaults layer (``engine/_user_defaults.py``) resolves to the
machine's ``%APPDATA%\\cds-text-sync\\defaults.json`` (Windows) or
``$XDG_CONFIG_HOME/cds-text-sync/defaults.json`` (elsewhere), and reading it
creates the file on first access. A test run must never touch the developer's
real file, so point both environment variables at a throwaway directory for
every test in the tier, without exception.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_defaults(tmp_path_factory, monkeypatch):
    config_home = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("APPDATA", str(config_home))
    yield config_home


@pytest.fixture(autouse=True)
def _reset_cli_timeout_cache():
    """The CLI memoises the daemon's timeout profile per process.

    Tests share the process, so a value fetched in one case would leak into
    the next. Import is guarded: not every tier has the CLI on its path.
    """
    try:
        from cds_cli import _cli_handlers_daemon as daemon_handlers

        daemon_handlers._reset_timeout_profile_cache()
    except Exception:
        pass
    yield
