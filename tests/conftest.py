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
