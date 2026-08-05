# -*- coding: utf-8 -*-
"""
test_ide_sync_apply.py — disk -> IDE application of modified .st projections.

Covers _apply_modified_st_objects: which objects are actually written, and —
just as important — which ones are allowed to appear in updated_text_objects.
Reporting an object as updated when nothing was written is worse than
reporting nothing: the user sees a green result and an unchanged IDE.

The daemon modules are IronPython-only, so their CODESYS/.NET dependencies are
stubbed before import.
"""

import importlib.machinery
import importlib.util
import json
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

_STUBBED = (
    "ide_runtime_common",
    "ide_daemon_state",
    "ide_daemon_helpers",
    "ide_apply_patch",
)

_HELPER_NAMES = (
    "_active_app_online_state",
    "_active_application_name",
    "_find_object_by_selector",
    "_find_object_in_project",
    "_get_sync_folder",
    "_invalidate_device_cache",
)


def _load_sync_module():
    """Import ide_handlers_sync with its CODESYS-only dependencies stubbed.

    sys.modules is restored afterwards: other test modules import the real
    ide_bridge modules and must not inherit these stubs.
    """
    saved = dict((name, sys.modules.get(name)) for name in _STUBBED)
    try:
        for name in _STUBBED:
            sys.modules[name] = types.ModuleType(name)

        state = sys.modules["ide_daemon_state"]
        state._log = lambda *args, **kwargs: None
        state._get_active_project = lambda: (None, None)
        state._read_text_utf8 = lambda path: ""

        helpers = sys.modules["ide_daemon_helpers"]
        for name in _HELPER_NAMES:
            setattr(helpers, name, lambda *args, **kwargs: None)

        loader = importlib.machinery.SourceFileLoader(
            "ide_handlers_sync_under_test",
            os.path.join(_BRIDGE, "ide_handlers_sync.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


sync = _load_sync_module()


ACTION_BODY = "nCount := 0;"
GVL_DECLARATION = "VAR_GLOBAL\n    bReset : BOOL;\nEND_VAR"


class _Document(object):
    def __init__(self, text=""):
        self.text = text


class _Target(object):
    """A CODESYS object exposing only the sections its kind really has."""

    def __init__(self, declaration=None, implementation=None):
        self.textual_declaration = (
            _Document(declaration) if declaration is not None else None
        )
        self.textual_implementation = (
            _Document(implementation) if implementation is not None else None
        )


def _report(tmp_path, disk_content, name="Obj"):
    path = tmp_path / "compare.json"
    path.write_text(
        json.dumps(
            {
                "objects": {
                    "modified": [
                        {
                            "name": name,
                            "guid": "g-1",
                            "path": "App/{0}".format(name),
                            "projection_diff": {
                                "format": "st",
                                "disk_content": disk_content,
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def apply_to(monkeypatch, tmp_path):
    """Run _apply_modified_st_objects against a single target object."""

    def run(disk_content, target):
        monkeypatch.setattr(
            sync, "_read_text_utf8", lambda path: open(path, encoding="utf-8").read()
        )
        monkeypatch.setattr(
            sync, "_find_object_by_selector", lambda project, selector: target
        )
        report_path = _report(tmp_path, disk_content)
        return sync._apply_modified_st_objects(None, report_path)

    return run


def test_action_edit_reaches_the_implementation(apply_to):
    target = _Target(implementation="old;")
    updated = apply_to(
        "ACTION Reset\n\n// --- implementation ---\n\n" + ACTION_BODY, target
    )
    assert updated == ["Obj"]
    assert target.textual_implementation.text.strip() == ACTION_BODY
    assert target.textual_declaration is None


def test_bare_action_body_is_not_written_into_the_declaration(apply_to):
    """A marker-less GVL/DUT body must stay a declaration, not become an impl."""
    target = _Target(declaration="old")
    updated = apply_to(GVL_DECLARATION, target)
    assert updated == ["Obj"]
    assert target.textual_declaration.text == GVL_DECLARATION
    assert target.textual_implementation is None


def test_full_pou_writes_both_sections(apply_to):
    target = _Target(declaration="old", implementation="old")
    updated = apply_to(
        "PROGRAM Main\nVAR\nEND_VAR\n\n// --- implementation ---\n\nx := 1;", target
    )
    assert updated == ["Obj"]
    assert target.textual_declaration.text == "PROGRAM Main\nVAR\nEND_VAR"
    assert target.textual_implementation.text == "x := 1;"


@pytest.mark.parametrize("content", ["", "   \n\n", "\r\n"])
def test_empty_projection_is_never_reported_as_updated(apply_to, content):
    target = _Target(declaration="keep", implementation="keep")
    assert apply_to(content, target) == []
    assert target.textual_declaration.text == "keep"
    assert target.textual_implementation.text == "keep"


def test_write_failure_is_not_reported_as_updated(apply_to):
    """Implementation text against an object that has none must not claim success."""
    target = _Target(declaration="old")
    updated = apply_to(
        "PROGRAM Main\nVAR\nEND_VAR\n\n// --- implementation ---\n\nx := 1;", target
    )
    assert updated == []


def test_legacy_bare_action_file_still_applies(apply_to):
    """.st exported before the ACTION header existed: bare body, no marker.

    The object has no declaration, so the body can only be the implementation.
    Without this the fix would need a re-export before it took effect.
    """
    target = _Target(implementation="old;")
    updated = apply_to(ACTION_BODY, target)
    assert updated == ["Obj"]
    assert target.textual_implementation.text.strip() == ACTION_BODY


def test_declaration_only_object_is_never_re_routed(apply_to):
    """A GVL exposes a declaration — its body must not slide into an impl."""
    target = _Target(declaration="old", implementation="keep")
    updated = apply_to(GVL_DECLARATION, target)
    assert updated == ["Obj"]
    assert target.textual_declaration.text == GVL_DECLARATION
    assert target.textual_implementation.text == "keep"
