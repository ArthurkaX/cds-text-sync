# -*- coding: utf-8 -*-
"""
test_daemon_partial_reads.py — a partial read must not read as a complete one.

Two daemon helpers turn "I could not look" into "there is nothing there", which
is the same failure mode in two different commands:

* ``_build_tree`` wrapped its whole child loop in ``try/except: pass``, so a
  child whose ``get_children`` raised came back as a leaf with no children and
  no mark of any kind -- and if the iteration itself failed partway, the
  children already collected were dropped as well. ``cts project-tree`` then
  showed a truncated subtree as if it were the whole thing.

* ``_read_text_member`` returned None on any error, so ``cts read-object``
  reported an object as having no declaration or no implementation when it
  simply could not read it.

The distinction both fixes turn on: a *section that does not exist* (GVL/DUT
have no textual_implementation, and the getter raises for those) is still a
normal None/no-children answer. A section that exists but cannot be read is an
error and has to say so.
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


@pytest.fixture
def logged(helpers, monkeypatch):
    """Collect what the helper logs, without a daemon log file."""
    messages = []
    monkeypatch.setattr(helpers, "_log", messages.append)
    return messages


class _FakeObject(object):
    def __init__(self, name, children=None, children_error=None):
        self._name = name
        self._children = children if children is not None else []
        self._children_error = children_error

    def get_name(self):
        return self._name

    def get_children(self):
        if self._children_error is not None:
            raise self._children_error
        return list(self._children)


class _FailingIterable(object):
    """Children that arrive and then break, as a live project walk can."""

    def __init__(self, items, error):
        self._items = items
        self._error = error

    def __iter__(self):
        for item in self._items:
            yield item
        raise self._error


class _IterableObject(_FakeObject):
    def __init__(self, name, iterable):
        _FakeObject.__init__(self, name)
        self._iterable = iterable

    def get_children(self):
        return self._iterable


# ---------------------------------------------------------------------------
# _build_tree
# ---------------------------------------------------------------------------


def test_a_child_that_cannot_be_walked_is_marked_not_presented_as_a_leaf(helpers, logged):
    broken = _FakeObject("Broken", children_error=RuntimeError("device not ready"))
    leaf = _FakeObject("Leaf")
    root = _FakeObject("Application", children=[broken, leaf])

    tree = helpers._build_tree(root)

    assert [child["name"] for child in tree["children"]] == ["Broken", "Leaf"]
    assert "children" not in tree["children"][0]
    assert "could not list children" in tree["children"][0]["_error"]
    assert "device not ready" in tree["children"][0]["_error"]
    assert any("Broken" in message for message in logged)


def test_children_collected_before_a_failure_are_kept(helpers, logged):
    """Half a subtree is still worth reporting; it is not worth inventing."""
    keep = _FakeObject("Keep")
    root = _IterableObject(
        "Application",
        _FailingIterable([keep], RuntimeError("walk aborted")),
    )

    tree = helpers._build_tree(root)

    assert [child["name"] for child in tree["children"]] == ["Keep"]
    assert "walk aborted" in tree["_error"]


def test_a_walkable_project_is_unchanged(helpers):
    grandchild = _FakeObject("Leaf")
    child = _FakeObject("Folder", children=[grandchild])
    root = _FakeObject("Application", children=[child])

    tree = helpers._build_tree(root)

    assert tree["name"] == "Application"
    assert tree["children"][0]["children"][0]["name"] == "Leaf"
    assert "_error" not in tree


def test_depth_limit_still_truncates_the_same_way(helpers):
    child = _FakeObject("Folder", children=[_FakeObject("Leaf")])
    root = _FakeObject("Application", children=[child])

    tree = helpers._build_tree(root, depth=1, current_depth=0)

    assert tree["children"][0]["name"] == "Folder"
    assert "children" not in tree["children"][0]


# ---------------------------------------------------------------------------
# _read_text_member
# ---------------------------------------------------------------------------


class _RaisingText(object):
    def __init__(self, error):
        self._error = error

    @property
    def text(self):
        raise self._error


class _TextObject(object):
    def __init__(self, name, declaration=None, implementation="MISSING"):
        self._name = name
        self.textual_declaration = declaration
        if implementation != "MISSING":
            self.textual_implementation = implementation

    def get_name(self):
        return self._name


def test_a_member_whose_text_will_not_read_raises(helpers):
    obj = _TextObject("MAIN", declaration=_RaisingText(RuntimeError("engine busy")))

    with pytest.raises(RuntimeError) as excinfo:
        helpers._read_text_member(obj, "textual_declaration")

    message = str(excinfo.value)
    assert "textual_declaration" in message
    assert "MAIN" in message
    assert "engine busy" in message


def test_a_member_the_object_type_does_not_have_is_still_none(helpers):
    """GVL/DUT raise for textual_implementation; that is "no section", not an error."""

    class _GvlLike(object):
        textual_declaration = None

        @property
        def textual_implementation(self):
            raise RuntimeError("Implementation is not available for this object type")

        def get_name(self):
            return "GVL_Config"

    gvl = _GvlLike()
    assert helpers._read_text_member(gvl, "textual_implementation") is None
    assert helpers._read_text_member(gvl, "textual_declaration") is None


def test_a_readable_member_is_returned_as_before(helpers):
    obj = _TextObject("MAIN", declaration="PROGRAM MAIN\nEND_PROGRAM", implementation="x := 1;")

    assert helpers._read_text_member(obj, "textual_declaration") == "PROGRAM MAIN\nEND_PROGRAM"
    assert helpers._read_text_member(obj, "textual_implementation") == "x := 1;"
