# -*- coding: utf-8 -*-
"""
test_object_selector_precedence.py — guid beats path beats name, always.

A CODESYS project can hold several objects under one name: a task and a POU
called ProgrammTask3 is the case that exposed this. The selector used to test
guid, then path, then name against each object in turn, so whichever object the
scan reached first won on whatever criterion happened to match — a name match
on an early object beat an exact guid match on a later one.

`cts import` hit exactly that and tried to write a POU body into a task, which
failed only because a task has no textual_declaration to write to. Two
same-named objects that are both writable would have swallowed the edit into
the wrong one, and reported success.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)
STATE_KEY = "_codesys_daemon_loop"


class _FakeObject:
    """Enough of a ScriptObject for the selector: a name, a guid, a parent."""

    def __init__(self, name, guid=None, parent=None):
        self._name = name
        self.parent = parent
        if guid is not None:
            self.Guid = guid

    def get_name(self):
        return self._name

    def __repr__(self):
        return "<_FakeObject {0}>".format(self._name)


@pytest.fixture(scope="module")
def helpers():
    if str(BRIDGE_DIR) not in sys.path:
        sys.path.insert(0, str(BRIDGE_DIR))
    spec = importlib.util.spec_from_file_location(
        "ide_daemon_helpers", BRIDGE_DIR / "ide_daemon_helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_daemon_state():
    saved = getattr(sys, STATE_KEY, None)
    setattr(sys, STATE_KEY, {})
    yield
    if saved is None:
        delattr(sys, STATE_KEY)
    else:
        setattr(sys, STATE_KEY, saved)


def _with_objects(helpers, objects):
    """Seed the TTL cache so the selector never touches a real project."""
    import time

    sys._codesys_daemon_loop["device_cache"] = objects
    sys._codesys_daemon_loop["device_cache_ts"] = time.time()


def test_guid_wins_over_an_earlier_name_match(helpers):
    """The regression: the task comes first in the scan, the POU is the target."""
    task = _FakeObject("ProgrammTask3", guid="11111111-1111-1111-1111-111111111111")
    pou = _FakeObject("ProgrammTask3", guid="b7269014-81bd-490c-9bc9-7086d8f3ddce")
    _with_objects(helpers, [task, pou])

    found = helpers._find_object_by_selector(
        None,
        {"guid": "b7269014-81bd-490c-9bc9-7086d8f3ddce", "name": "ProgrammTask3"},
    )
    assert found is pou


def test_guid_match_is_case_insensitive(helpers):
    pou = _FakeObject("Pou", guid="B7269014-81BD-490C-9BC9-7086D8F3DDCE")
    _with_objects(helpers, [pou])

    assert (
        helpers._find_object_by_selector(
            None, {"guid": "b7269014-81bd-490c-9bc9-7086d8f3ddce"}
        )
        is pou
    )


def test_path_wins_over_an_earlier_name_match(helpers, monkeypatch):
    """With no guid to go on, the path still outranks a bare name."""
    wrong = _FakeObject("Shared")
    right = _FakeObject("Shared")
    _with_objects(helpers, [wrong, right])
    monkeypatch.setattr(
        helpers,
        "_build_path",
        lambda obj: "App/Right/Shared" if obj is right else "App/Wrong/Shared",
    )

    found = helpers._find_object_by_selector(
        None, {"path": "App/Right/Shared", "name": "Shared"}
    )
    assert found is right


def test_backslash_paths_are_normalised(helpers, monkeypatch):
    obj = _FakeObject("Shared")
    _with_objects(helpers, [obj])
    monkeypatch.setattr(helpers, "_build_path", lambda o: "App/Sub/Shared")

    assert (
        helpers._find_object_by_selector(None, {"path": "\\App\\Sub\\Shared\\"}) is obj
    )


def test_name_is_still_used_when_it_is_all_there_is(helpers):
    other = _FakeObject("Other")
    wanted = _FakeObject("Wanted")
    _with_objects(helpers, [other, wanted])

    assert helpers._find_object_by_selector(None, {"name": "Wanted"}) is wanted


def test_unresolvable_selector_returns_none(helpers):
    _with_objects(helpers, [_FakeObject("Something")])

    assert helpers._find_object_by_selector(None, {"name": "Absent"}) is None


def test_a_stale_guid_falls_back_only_after_every_guid_was_checked(helpers):
    """Guid churn is normal, so a miss may fall back — but never early.

    CODESYS assigns a new guid when an object is recreated, so a compare report
    can name an object by a guid that no longer exists; refusing to resolve it
    would break the ordinary recreate case. The fallback is fine. What is not
    fine is reaching it while an object further down the scan still holds the
    guid that was asked for — that was the original bug, and it is what the
    ordering guarantees against.
    """
    impostor = _FakeObject("ProgrammTask3", guid="00000000-0000-0000-0000-000000000000")
    _with_objects(helpers, [impostor])

    found = helpers._find_object_by_selector(
        None,
        {"guid": "b7269014-81bd-490c-9bc9-7086d8f3ddce", "name": "ProgrammTask3"},
    )
    assert found is impostor


def test_an_unmatched_guid_with_nothing_else_resolves_to_nothing(helpers):
    _with_objects(helpers, [_FakeObject("Something", guid="aaaa")])

    assert (
        helpers._find_object_by_selector(
            None, {"guid": "b7269014-81bd-490c-9bc9-7086d8f3ddce"}
        )
        is None
    )
