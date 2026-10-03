# -*- coding: utf-8 -*-
"""
test_apply_patch_persistent_guard.py — a second Persistent Variables object
must be refused before CODESYS is asked to create it.

CODESYS accepts exactly one Persistent Variables object per application. When a
patch asked for a second one, the create went through to CODESYS, which raised a
modal "one or more objects to be imported are already existing" dialog — and a
modal blocks the single-threaded daemon, so every later command timed out
(T46). The engine refuses such a patch up front; this is the host-side
backstop for a patch that still carries the create.
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


PERSISTENT_GUID = "{3183921b-cc91-4712-9781-c3b6555122b5}"
OTHER_PERSISTENT_GUID = "{261bd6e6-249c-4232-bb6f-84c2fbeef430}"
# A normal GVL's type GUID (verified on the test VM, 3.5.22.30).
GVL_GUID = "{ffbfa93a-b94d-45fc-a329-229860183b1d}"


class _FakeObject(object):
    def __init__(self, name, type_guid=None, parent=None, children=None):
        self.name = name
        self.parent = parent
        self.children = list(children or [])
        self.created = []
        self._type_guid = type_guid

    def get_name(self):
        return self.name

    @property
    def type(self):
        """The real CODESYS API exposes the type as a ``type`` property
        (a System.Guid); it has no ``get_type()``."""
        if self._type_guid is None:
            # Some live objects expose no type at all.
            raise AttributeError("type")
        return self._type_guid

    def _add(self, child):
        self.children.append(child)
        child.parent = self
        return child

    def get_children(self, recursive=False):
        if not recursive:
            return list(self.children)
        result = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_children(recursive=True))
        return result

    def create_child(self, name, type_guid):
        created = _FakeObject(name, type_guid=self)
        self.created.append(name)
        return self._add(created)


def _application(name, children=None):
    return _FakeObject(name, children=children)


def _project_with_application(app_children, project_name="Project", app_name="Application"):
    app = _FakeObject(app_name, children=app_children)
    device = _FakeObject("Device", children=[app])
    project = _FakeObject(project_name, children=[device])
    return project, app, [project, device, app]


def test_existing_persistent_list_is_found_by_type_guid():
    existing = _FakeObject("FirstPersistent", type_guid=PERSISTENT_GUID)
    project, app, chain = _project_with_application([existing])

    found = patch_module._find_existing_persistent_gvl(app, chain)

    assert found is existing


def test_existing_persistent_list_is_found_behind_a_transparent_container():
    existing = _FakeObject("FirstPersistent", type_guid=OTHER_PERSISTENT_GUID)
    plc_logic = _FakeObject("PLC Logic", children=[existing])
    project, app, chain = _project_with_application([plc_logic])

    assert patch_module._find_existing_persistent_gvl(app, chain) is existing


def test_unreadable_type_falls_back_to_the_default_codesys_name():
    existing = _FakeObject("PersistentVars")
    project, app, chain = _project_with_application([existing])

    assert patch_module._find_existing_persistent_gvl(app, chain) is existing


def test_a_plain_gvl_is_not_mistaken_for_a_persistent_list():
    plain = _FakeObject("GVL_Plain", type_guid=GVL_GUID)
    project, app, chain = _project_with_application([plain])

    assert patch_module._find_existing_persistent_gvl(app, chain) is None


def test_a_readable_type_wins_over_a_persistent_sounding_name():
    """The old code mixed the object name into the type candidates, so a POU
    or GVL literally called "PersistentVars" matched even with a known type."""
    named = _FakeObject("PersistentVars", type_guid=GVL_GUID)
    project, app, chain = _project_with_application([named])

    assert patch_module._find_existing_persistent_gvl(app, chain) is None


def test_another_applications_persistent_list_is_not_a_match():
    """Two applications in one project: only the resolved application counts."""
    other_app = _application(
        "App_A_Application",
        children=[_FakeObject("FirstPersistent", type_guid=PERSISTENT_GUID)],
    )
    target_app = _application("App_B_Application")
    device = _FakeObject("Device", children=[other_app, target_app])
    project = _FakeObject("Project", children=[device])
    chain = [project, device, target_app]

    assert patch_module._find_existing_persistent_gvl(target_app, chain) is None


def test_creating_a_second_persistent_list_is_refused_by_name():
    existing = _FakeObject("FirstPersistent", type_guid=PERSISTENT_GUID)
    project, app, chain = _project_with_application([existing])

    with pytest.raises(Exception) as excinfo:
        patch_module._create_text_object(
            app,
            {
                "kind": "persistent_gvl",
                "name": "SecondPersistent",
                "path": "Device/Application/SecondPersistent.st",
            },
            container_chain=chain,
        )

    message = str(excinfo.value)
    assert "SecondPersistent" in message
    assert "FirstPersistent" in message
    assert app.created == [], "CODESYS create_child must not be reached"


def test_the_first_persistent_list_is_still_created():
    project, app, chain = _project_with_application([])

    obj = patch_module._create_text_object(
        app,
        {
            "kind": "persistent_gvl",
            "name": "FirstPersistent",
            "path": "Device/Application/FirstPersistent.st",
            "declaration": "VAR_GLOBAL PERSISTENT\nEND_VAR",
        },
        container_chain=chain,
    )

    assert obj is not None
    assert app.created == ["FirstPersistent"]


def test_a_task_local_gvl_is_not_guarded_as_persistent():
    existing = _FakeObject("FirstPersistent", type_guid=PERSISTENT_GUID)
    project, app, chain = _project_with_application([existing])

    obj = patch_module._create_text_object(
        app,
        {
            "kind": "task_local_gvl",
            "name": "TaskLocal",
            "path": "Device/Application/TaskLocal.st",
            "declaration": "VAR_GLOBAL\nEND_VAR",
        },
        container_chain=chain,
    )

    assert obj is not None
    assert app.created == ["TaskLocal"]
