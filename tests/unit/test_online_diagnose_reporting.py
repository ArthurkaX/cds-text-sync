# -*- coding: utf-8 -*-
"""
test_online_diagnose_reporting.py — "cannot tell" must not read as a value.

``get_application_state_impl`` backs ``cts diagnose-online``, whose whole job is
to say what is wrong with the online link. It swallowed the device-based lookup
(and every per-attribute read) with a bare ``except: pass``, so:

* an attribute that exists but raised simply disappeared from the answer — a
  missing ``is_running`` reads as "not running";
* a fallback that succeeded after the device route failed looked identical to
  one that never needed a fallback.

The values stay best-effort; the *reason* they are missing is now part of the
answer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)


@pytest.fixture(scope="module")
def helpers():
    """Import ide_online_helpers under CPython (its module level is stdlib-only)."""
    spec = importlib.util.spec_from_file_location(
        "ide_online_helpers", BRIDGE_DIR / "ide_online_helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RaisingProperty(object):
    def __init__(self, error):
        self._error = error

    def __get__(self, instance, owner):
        raise self._error


class _OnlineApp(object):
    application_state = _RaisingProperty(RuntimeError("connection lost mid-read"))
    is_connected = True
    is_running = True

    def _unused(self):  # pragma: no cover - keeps the class obviously fake
        return None


class _Application(object):
    def get_name(self):
        return "Application"


class _Project(object):
    def __init__(self, app):
        self.active_application = app

    def get_children(self, recursive=False):
        return []


@pytest.fixture
def scriptengine(monkeypatch):
    """A scriptengine whose online factory hands back one fake application."""
    app = _Application()
    online_app = _OnlineApp()
    fake = SimpleNamespace(
        online=SimpleNamespace(
            create_online_application=lambda target: online_app,
            create_online_device=lambda device: None,
        )
    )
    monkeypatch.setitem(sys.modules, "scriptengine", fake)
    return SimpleNamespace(project=_Project(app), app=app, online_app=online_app)


# ---------------------------------------------------------------------------
# Per-attribute reads
# ---------------------------------------------------------------------------


def test_an_unreadable_attribute_is_reported_not_omitted(helpers, scriptengine):
    info = helpers.get_application_state_impl(scriptengine.project)

    assert info["application"] == "Application"
    assert "application_state" not in info
    assert "connection lost mid-read" in info["application_state_error"]


def test_readable_attributes_are_still_reported(helpers, scriptengine):
    info = helpers.get_application_state_impl(scriptengine.project)

    assert info["is_connected"] == "True"
    assert info["is_running"] == "True"


# ---------------------------------------------------------------------------
# The device-based route and its fallback
# ---------------------------------------------------------------------------


def test_a_failed_device_route_is_reported(helpers, scriptengine, monkeypatch):
    def _boom(project):
        raise RuntimeError("no main device in this project")

    monkeypatch.setattr(helpers, "_find_main_device", _boom)

    info = helpers.get_application_state_impl(scriptengine.project)

    assert info["application"] == "Application"
    assert "no main device in this project" in info["device_attempt_error"]


def test_a_clean_run_reports_no_device_error(helpers, scriptengine):
    info = helpers.get_application_state_impl(scriptengine.project)

    assert "device_attempt_error" not in info


def test_when_the_fallback_fails_too_both_reasons_survive(helpers, scriptengine, monkeypatch):
    def _no_device(project):
        raise RuntimeError("no main device in this project")

    def _cannot_open(target):
        raise RuntimeError("could not open an online application")

    monkeypatch.setattr(helpers, "_find_main_device", _no_device)
    monkeypatch.setattr(
        sys.modules["scriptengine"].online, "create_online_application", _cannot_open
    )

    info = helpers.get_application_state_impl(scriptengine.project)

    assert info["state"] == "error"
    assert "could not open an online application" in info["error"]
    assert "no main device in this project" in info["device_attempt_error"]
