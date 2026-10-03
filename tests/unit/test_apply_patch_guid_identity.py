# -*- coding: utf-8 -*-
"""
test_apply_patch_guid_identity.py — an unreadable guid must not read as "absent".

``apply_patch`` matches the patch against the live project through a guid map,
and a miss in that map means "this object does not exist yet". ``_build_guid_map``
built the map with a per-object ``except: pass``, so an object whose guid could
not be read vanished from it and became indistinguishable from an object that is
genuinely not there -- its edits were then skipped silently, or it was created a
second time.

The map may be incomplete (that is a property of the live project, not a bug),
but the caller has to *know* it is: a miss is only evidence of absence when
every guid was read.
"""

from __future__ import annotations

import os
import sys

import pytest

_BRIDGE_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

try:
    import ide_apply_patch as patch_module
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(
        "ide_apply_patch not importable under CPython: %s" % exc,
        allow_module_level=True,
    )


PATCH_GUID = "b7269014-81bd-490c-9bc9-7086d8f3ddce"

MINIMAL_PATCH = """<?xml version="1.0" encoding="utf-8"?>
<Single Name="Export">
  <Single Name="MetaObject">
    <Single Name="Guid">{0}</Single>
  </Single>
</Single>
""".format(PATCH_GUID)


class _FakeObject(object):
    def __init__(self, name, guid=None, guid_error=None):
        self._name = name
        self._guid = guid
        self._guid_error = guid_error

    def get_name(self):
        return self._name

    @property
    def guid(self):
        if self._guid_error is not None:
            raise self._guid_error
        return self._guid


class _FakeProject(object):
    def __init__(self, children):
        self._children = children
        self.native_imports = []

    def get_children(self, recursive=False):
        return list(self._children)

    def import_native(self, path):
        self.native_imports.append(path)


# ---------------------------------------------------------------------------
# _build_guid_map
# ---------------------------------------------------------------------------


def test_an_object_with_an_unreadable_guid_is_reported_not_dropped():
    unreadable = _FakeObject("Broken", guid_error=RuntimeError("object is stale"))
    healthy = _FakeObject("Main", guid="b7269014-81bd-490c-9bc9-7086d8f3ddce")

    guid_map, unreadable_objects = patch_module._build_guid_map(
        _FakeProject([unreadable, healthy])
    )

    assert list(guid_map) == ["b7269014-81bd-490c-9bc9-7086d8f3ddce"]
    assert len(unreadable_objects) == 1
    assert "Broken" in unreadable_objects[0]
    assert "object is stale" in unreadable_objects[0]


def test_a_walkable_project_reports_no_unreadable_objects():
    healthy = _FakeObject("Main", guid="b7269014-81bd-490c-9bc9-7086d8f3ddce")

    guid_map, unreadable_objects = patch_module._build_guid_map(
        _FakeProject([healthy])
    )

    assert list(guid_map) == ["b7269014-81bd-490c-9bc9-7086d8f3ddce"]
    assert unreadable_objects == []


def test_an_object_without_a_guid_is_not_an_error():
    """``guid`` returning None/"" is normal and stays out of the report."""

    class _NoGuid(object):
        @property
        def guid(self):
            return None

        def get_name(self):
            return "Container"

    guid_map, unreadable_objects = patch_module._build_guid_map(
        _FakeProject([_NoGuid()])
    )

    assert guid_map == {}
    assert unreadable_objects == []


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------


def _write_patch(tmp_path):
    patch_path = tmp_path / "IMPORT.xml"
    patch_path.write_text(MINIMAL_PATCH, encoding="utf-8")
    return str(patch_path)


def test_an_unmatched_guid_is_refused_when_the_map_is_incomplete(tmp_path):
    """The patch names a guid the project cannot confirm; applying would guess."""
    project = _FakeProject(
        [_FakeObject("Broken", guid_error=RuntimeError("object is stale"))]
    )

    result = patch_module.apply_patch(None, project, _write_patch(tmp_path))

    assert not result
    assert "could not be read" in result.error
    assert "Broken" in result.error
    assert PATCH_GUID in result.error


def test_an_incomplete_map_with_no_unmatched_guid_still_applies(tmp_path):
    """A fully matched patch does not care that some other object was unreadable."""
    project = _FakeProject(
        [
            _FakeObject("Broken", guid_error=RuntimeError("object is stale")),
            _FakeObject("Main", guid=PATCH_GUID),
        ]
    )

    result = patch_module.apply_patch(None, project, _write_patch(tmp_path))

    assert result


# ---------------------------------------------------------------------------
# _create_child_with_guid
# ---------------------------------------------------------------------------


class _Target(object):
    def __init__(self, error=None, result=None):
        self._error = error
        self._result = result
        self.calls = []

    def create_child(self, name, guid):
        self.calls.append((name, guid))
        if self._error is not None:
            raise self._error
        return self._result


def test_every_failed_candidate_is_recorded_with_its_reason():
    target = _Target(error=RuntimeError("wrong type guid"))
    errors = []

    obj = patch_module._create_child_with_guid(
        target, "GVL_P", ["{11111111-1111-1111-1111-111111111111}", "{22222222-2222-2222-2222-222222222222}"],
        errors,
    )

    assert obj is None
    assert len(errors) == 2
    assert all("wrong type guid" in line for line in errors)
    assert "{11111111-1111-1111-1111-111111111111}" in errors[0]


def test_a_successful_candidate_returns_the_object_and_stops():
    created = object()
    target = _Target(result=created)
    errors = []

    obj = patch_module._create_child_with_guid(target, "GVL_P", ["{11111111-1111-1111-1111-111111111111}"], errors)

    assert obj is created
    assert errors == []
    assert len(target.calls) == 1


def test_a_failed_creation_reports_the_reason_not_an_unsupported_kind():
    class _Container(object):
        parent = None

        def create_child(self, name, guid):
            raise RuntimeError("CODESYS refused the type guid")

    with pytest.raises(Exception) as excinfo:
        patch_module._create_text_object(
            _Container(), {"kind": "persistent_gvl", "name": "GVL_P"}
        )

    message = str(excinfo.value)
    assert "CODESYS refused the type guid" in message
