# -*- coding: utf-8 -*-
"""Read failures in the daemon must reach the caller, not be dropped.

Two daemon reads used to swallow every exception: ``cts app-state`` lost a
property that refused to read (a missing ``is_running`` then reads as "not
running"), and Project Information returned a short dict as if it were the
whole truth. These tests pin the replacement behaviour: an unreadable property
is named, either as ``<attr>_error`` in the response or in ``project_info_errors``.
"""

import os
import sys
from types import SimpleNamespace

import pytest


_IDE_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "products",
        "codesys-host",
        "src",
        "ide_bridge",
    )
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

import ide_daemon_helpers as helpers
import ide_handlers_project as handlers


def _install_loop(monkeypatch, project):
    loop = {"projects": SimpleNamespace(primary=project), "started_at": "now"}
    monkeypatch.setattr(sys, "_codesys_daemon_loop", loop, raising=False)
    return loop


# ── application_state ─────────────────────────────────────────────────────


def test_application_state_names_a_property_that_refuses_to_read(monkeypatch):
    class _OnlineApp(object):
        application_state = "run"

        @property
        def is_running(self):
            raise RuntimeError("busy reading")

    se = SimpleNamespace(
        online=SimpleNamespace(create_online_application=lambda app: _OnlineApp())
    )
    monkeypatch.setitem(sys.modules, "scriptengine", se)
    _install_loop(monkeypatch, SimpleNamespace(active_application=object()))

    result = handlers._cmd_application_state()

    assert result["ok"] is True
    data = result["data"]
    assert data["application_state"] == "run"
    assert "is_running" not in data
    assert "busy reading" in data["is_running_error"]


def test_application_state_skips_a_property_that_does_not_exist(monkeypatch):
    class _OnlineApp(object):
        application_state = "stop"

    se = SimpleNamespace(
        online=SimpleNamespace(create_online_application=lambda app: _OnlineApp())
    )
    monkeypatch.setitem(sys.modules, "scriptengine", se)
    _install_loop(monkeypatch, SimpleNamespace(active_application=object()))

    result = handlers._cmd_application_state()

    assert result["ok"] is True
    assert result["data"]["application_state"] == "stop"
    assert not any(key.endswith("_error") for key in result["data"])


# ── project_info ──────────────────────────────────────────────────────────


def test_project_info_names_a_lookup_that_raises(monkeypatch):
    class _Project(object):
        def get_project_info(self):
            raise RuntimeError("properties locked")

        def get_children(self, recursive=False):
            return []

    monkeypatch.setattr(handlers, "_get_active_project", lambda: (_Project(), None))
    monkeypatch.setattr(handlers, "_obj_name", lambda obj: "Demo")
    monkeypatch.setattr(handlers, "_project_file_path", lambda obj: "")
    _install_loop(monkeypatch, _Project())

    result = handlers._cmd_project_info()

    assert result["ok"] is True
    errors = result["data"]["project_info_errors"]
    assert any("properties locked" in message for message in errors)


def test_project_info_has_no_error_field_when_everything_reads(monkeypatch):
    class _Project(object):
        def get_project_info(self):
            return SimpleNamespace(Company="Acme")

        def get_children(self, recursive=False):
            return []

    monkeypatch.setattr(handlers, "_get_active_project", lambda: (_Project(), None))
    monkeypatch.setattr(handlers, "_obj_name", lambda obj: "Demo")
    monkeypatch.setattr(handlers, "_project_file_path", lambda obj: "")
    _install_loop(monkeypatch, _Project())

    result = handlers._cmd_project_info()

    assert result["ok"] is True
    assert result["data"]["summary"] == {"Company": "Acme"}
    assert "project_info_errors" not in result["data"]


# ── helpers ───────────────────────────────────────────────────────────────


def test_read_project_info_attr_records_a_refusing_property():
    class _Info(object):
        Company = "Acme"

        @property
        def Title(self):
            raise RuntimeError("locked")

    errors = []
    value = helpers._read_project_info_attr(_Info(), ["Company", "Title"], errors)

    # Company is found first and returned; Title's failure is not reached, so
    # ask for Title alone to see the error recorded.
    assert value == "Acme"

    errors = []
    assert helpers._read_project_info_attr(_Info(), ["Title"], errors) is None
    assert any("Title" in message and "locked" in message for message in errors)


def test_project_info_summary_records_the_fields_it_could_not_read():
    class _Info(object):
        Company = "Acme"

        @property
        def Title(self):
            raise RuntimeError("locked")

    errors = []
    summary = helpers._project_info_summary(_Info(), errors)

    assert summary == {"Company": "Acme"}
    assert errors


def test_mapping_to_dict_names_an_entry_it_could_not_read():
    class _BadMap(object):
        def keys(self):
            return ["cds-sync-folder"]

        def __getitem__(self, key):
            raise RuntimeError("gone")

    errors = []
    result = helpers._mapping_to_dict(_BadMap(), errors)

    assert result == {}
    assert errors
