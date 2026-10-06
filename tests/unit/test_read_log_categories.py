# -*- coding: utf-8 -*-
"""
test_read_log_categories.py — ``cts read-log`` and the message-category guard.

Live, ``cts read-log`` answered "Value cannot be null. Parameter name:
category".  ``SystemImpl.GetCategory`` returns null for a GUID the message
storage does not know, ``get_messages`` swallows that null but
``get_message_objects`` passes it straight to the storage, which throws.  The
old handler called both with no argument at all and could not say which
category it meant.

These tests pin the replacement: the category is resolved against
``get_message_categories()`` first, an unknown one is an error that lists what
is available (never a crash), and the default is the compiler's Build category.
"""

import os
import sys
import types

import pytest

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import ide_handlers_plc as plc_handlers  # noqa: E402

BUILD = "97f48d64-a2a3-4856-b640-75c046e37ea9"
EXPORT = "2af7707f-1a3a-4f5e-8f0e-42c9d8f1a1c1"
PRE_COMPILE = "217bc73e-1e3b-46e1-9a7f-3b4e1e0c2a55"


class _FakeSystem(object):
    """A message storage with a fixed category list and per-category messages."""

    def __init__(self, categories=None, messages=None):
        self._categories = list(
            categories
            if categories is not None
            else [
                (BUILD, "Build"),
                (EXPORT, "Export/Import"),
                (PRE_COMPILE, "Precompile"),
            ]
        )
        self._messages = dict(messages or {BUILD: ["Build: 1 error"]})
        self.read_calls = []
        self.object_calls = []
        self.clear_calls = []

    def get_message_categories(self):
        return [guid for guid, _description in self._categories]

    def get_message_category_description(self, guid):
        key = str(guid).strip("{}").lower()
        for known, description in self._categories:
            if known.strip("{}").lower() == key:
                return description
        raise KeyError(guid)

    def get_messages(self, category):
        key = str(category).strip("{}").lower()
        self.read_calls.append(key)
        return list(self._messages.get(key, []))

    def get_message_objects(self, category, severities=None):
        key = str(category).strip("{}").lower()
        self.object_calls.append(key)
        if key not in [g.strip("{}").lower() for g, _ in self._categories]:
            # What the real MessageStorage does with a null category.
            raise ValueError("Value cannot be null. Parameter name: category")
        return list(self._messages.get(key, []))

    def clear_messages(self, guid):
        self.clear_calls.append(guid)


@pytest.fixture
def system(monkeypatch):
    fake = _FakeSystem()
    monkeypatch.setattr(
        plc_handlers.sys, "_codesys_daemon_loop", {"system": fake}, raising=False
    )
    return fake


def test_the_default_category_is_the_compiler_build(system):
    result = plc_handlers._cmd_read_log({})

    assert result["ok"] is True
    assert result["data"]["category"]["guid"].strip("{}").lower() == BUILD
    assert result["data"]["category"]["description"] == "Build"
    assert result["data"]["messages"] == ["Build: 1 error"]
    assert system.read_calls == [BUILD]


def test_an_unknown_category_is_an_error_that_lists_the_available_ones(system):
    result = plc_handlers._cmd_read_log({"category": "does-not-exist"})

    assert result["ok"] is False
    assert "Unknown message category 'does-not-exist'" in result["error"]
    assert "Build" in result["error"]
    assert BUILD in result["error"].lower() or BUILD.upper() in result["error"]
    # The guard is the point: an unknown GUID must never reach the throwing API.
    assert system.object_calls == []
    assert system.read_calls == []


def test_an_unknown_guid_never_reaches_get_message_objects(system):
    """The exact live failure: a GUID the storage does not know."""
    result = plc_handlers._cmd_read_log(
        {"category": "11111111-2222-3333-4444-555555555555"}
    )

    assert result["ok"] is False
    assert system.object_calls == []


def test_a_category_can_be_named_by_its_description(system):
    result = plc_handlers._cmd_read_log({"category": "Export/Import"})

    assert result["ok"] is True
    assert result["data"]["category"]["guid"].strip("{}").lower() == EXPORT


def test_a_guid_matches_with_braces_and_any_case(system):
    result = plc_handlers._cmd_read_log({"category": "{" + BUILD.upper() + "}"})

    assert result["ok"] is True
    assert result["data"]["category"]["guid"].strip("{}").lower() == BUILD


def test_an_empty_ide_category_list_still_serves_the_default(system, monkeypatch):
    """A tick too early to list categories must not break the default."""
    monkeypatch.setattr(system, "get_message_categories", lambda: [])

    result = plc_handlers._cmd_read_log({})

    assert result["ok"] is True
    assert result["data"]["category"]["guid"].strip("{}").lower() == BUILD
    assert result["data"]["category"]["description"] == "Build"


def test_a_broken_category_list_degrades_instead_of_raising(system, monkeypatch):
    def _boom():
        raise RuntimeError("storage not ready")

    monkeypatch.setattr(system, "get_message_categories", _boom)

    result = plc_handlers._cmd_read_log({})

    assert result["ok"] is True
    assert result["data"]["available_categories"] == []


def test_last_keeps_the_tail(system):
    system._messages[BUILD] = ["one", "two", "three"]

    result = plc_handlers._cmd_read_log({"last": "2"})

    assert result["data"]["messages"] == ["two", "three"]
    assert result["data"]["count"] == 2


def test_clear_gets_a_real_guid_of_the_chosen_category(system, monkeypatch):
    class _Guid(object):
        def __init__(self, text):
            self.text = text

    monkeypatch.setitem(sys.modules, "System", types.SimpleNamespace(Guid=_Guid))

    plc_handlers._cmd_read_log({"category": "Export/Import", "clear": True})

    assert len(system.clear_calls) == 1
    assert system.clear_calls[0].text.strip("{}").lower() == EXPORT


def test_the_response_names_the_categories_it_could_have_used(system):
    result = plc_handlers._cmd_read_log({})

    names = [c["description"] for c in result["data"]["available_categories"]]
    assert names == ["Build", "Export/Import", "Precompile"]
