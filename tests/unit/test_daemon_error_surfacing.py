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
import ide_runtime_common as runtime_common


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


# ── T55: the guards must not depend on hasattr ─────────────────────────────


def _python2_hasattr(monkeypatch):
    """Mimic Python 2's ``hasattr``, which returns False for *any* exception.

    CPython 3 propagates a non-AttributeError out of ``hasattr``; Python 2 --
    and therefore IronPython -- swallows it and answers False. That is what
    turned a refusing getter into "this attribute is absent" on the VM while
    the same code recorded the error under the test interpreter.
    """
    import builtins

    real_hasattr = builtins.hasattr

    def py2_hasattr(obj, name):
        try:
            return real_hasattr(obj, name)
        except Exception:
            return False

    monkeypatch.setattr(builtins, "hasattr", py2_hasattr)


def test_get_project_info_object_records_a_property_that_raises_on_access(
    monkeypatch,
):
    """The old hasattr guard would read this as "no Project Information"."""
    _python2_hasattr(monkeypatch)

    class _Project(object):
        @property
        def project_info(self):
            raise RuntimeError("properties locked")

    errors = []
    assert helpers._get_project_info_object(_Project(), errors) is None
    assert any("properties locked" in message for message in errors)


def test_read_project_info_attr_records_a_property_that_raises_on_access(
    monkeypatch,
):
    _python2_hasattr(monkeypatch)

    class _Info(object):
        Company = "Acme"

        @property
        def Title(self):
            raise RuntimeError("locked")

    errors = []
    assert helpers._read_project_info_attr(_Info(), ["Title"], errors) is None
    assert any("Title" in message and "locked" in message for message in errors)


def test_mapping_to_dict_records_a_pair_whose_key_refuses():
    class _Pair(object):
        @property
        def Key(self):
            raise RuntimeError("no key")

        Value = "x"

    class _Values(object):
        def __iter__(self):
            return iter([_Pair()])

    errors = []
    result = helpers._mapping_to_dict(_Values(), errors)

    assert result == {}
    assert any("no key" in message for message in errors)


def test_get_sync_folder_reports_a_refusing_project_info(monkeypatch):
    """The same flaw, one function over: with the old hasattr guard a project
    whose Project Information refuses to read was answered with "sync folder
    not configured", pointing at settings instead of at the read failure."""
    _python2_hasattr(monkeypatch)

    class _Project(object):
        @property
        def project_info(self):
            raise RuntimeError("properties locked")

    projects = SimpleNamespace(primary=_Project())
    monkeypatch.setattr(sys, "_codesys_daemon_loop", {"projects": projects}, raising=False)

    path, error = helpers._get_sync_folder()

    assert path is None
    assert "properties locked" in error
    assert "not configured" not in error


# ── T47/T53: the object type is the ``type`` property ─────────────────────


def test_object_type_reads_the_type_property():
    class _Obj(object):
        type = "FFBFA93A-B94D-45FC-A329-229860183B1D"

    guid, error = runtime_common.object_type(_Obj())

    assert guid == "ffbfa93a-b94d-45fc-a329-229860183b1d"
    assert error is None


def test_object_type_reports_a_refusing_type_property():
    class _Obj(object):
        @property
        def type(self):
            raise RuntimeError("type unavailable")

    guid, error = runtime_common.object_type(_Obj())

    assert guid is None
    assert "type unavailable" in error


def test_object_type_is_absent_not_an_error_for_the_project_root():
    """ScriptProject has no ``type``; that is an absent property, not a
    refusal, so no type_error may be invented for the tree root."""

    class _Project(object):
        pass

    assert runtime_common.object_type(_Project()) == (None, None)


def test_build_tree_carries_the_type_of_each_node():
    class _Obj(object):
        def __init__(self, name, type_guid):
            self._name = name
            self.type = type_guid

        def get_name(self):
            return self._name

        def get_children(self):
            return []

    tree = helpers._build_tree(_Obj("ST_PROGRAMM", "6F9DAC99-8DE1-4EFC-8465-68AC443B7D08"))

    assert tree["type"] == "6f9dac99-8de1-4efc-8465-68ac443b7d08"


def test_read_object_reports_the_real_type_not_unknown(monkeypatch):
    class _Obj(object):
        type = "6f9dac99-8de1-4efc-8465-68ac443b7d08"

    monkeypatch.setattr(handlers, "_get_active_project", lambda: (object(), None))
    monkeypatch.setattr(handlers, "_find_object_by_selector", lambda project, params: _Obj())
    monkeypatch.setattr(handlers, "_obj_name", lambda obj: "ST_PROGRAMM")
    monkeypatch.setattr(handlers, "_build_path", lambda obj: "Device/App/ST_PROGRAMM")

    result = handlers._cmd_read_object({"name": "ST_PROGRAMM"})

    assert result["ok"] is True
    assert result["data"]["type"] == "6f9dac99-8de1-4efc-8465-68ac443b7d08"
    assert "type_error" not in result["data"]


def test_read_object_names_a_refusing_type(monkeypatch):
    class _Obj(object):
        @property
        def type(self):
            raise RuntimeError("type unavailable")

    monkeypatch.setattr(handlers, "_get_active_project", lambda: (object(), None))
    monkeypatch.setattr(handlers, "_find_object_by_selector", lambda project, params: _Obj())
    monkeypatch.setattr(handlers, "_obj_name", lambda obj: "Mystery")
    monkeypatch.setattr(handlers, "_build_path", lambda obj: "Device/App/Mystery")

    result = handlers._cmd_read_object({"name": "Mystery"})

    assert result["ok"] is True
    assert "type" not in result["data"]
    assert "type unavailable" in result["data"]["type_error"]
