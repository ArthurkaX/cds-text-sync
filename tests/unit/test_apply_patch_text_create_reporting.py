# -*- coding: utf-8 -*-
"""
test_apply_patch_text_create_reporting.py — a text create that merely finds an
object already there must not be reported as a creation.

T49: the two VM runs contradicted each other over whether a persistent GVL had
really been created. The contradiction turned out to be an unsaved in-memory
import that a daemon restart discarded, not a lying report -- but tracing the
create path found one place that does lie: apply_patch's text-create loop counts
a pre-existing object (found by name) as created. The daemon's own path
(_apply_text_create_entry) already keeps the two apart and says which happened;
this pins the same honesty onto apply_patch.
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


class _FakeObject(object):
    def __init__(self, name, parent=None, children=None):
        self.name = name
        self.parent = parent
        self.children = list(children or [])

    def get_name(self):
        return self.name

    def get_children(self, recursive=False):
        if not recursive:
            return list(self.children)
        result = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_children(recursive=True))
        return result

    def add(self, child):
        self.children.append(child)
        child.parent = self
        return child

    def create_gvl(self, name):
        return self.add(_FakeObject(name))


def _project_with(existing_names):
    project = _FakeObject("Project")
    device = project.add(_FakeObject("Device"))
    application = device.add(_FakeObject("Application"))
    for name in existing_names:
        application.add(_FakeObject(name))
    return project


def _write_patch(tmp_path, path, name, kind="gvl"):
    patch_path = os.path.join(str(tmp_path), "IMPORT.xml")
    with open(patch_path, "w", encoding="utf-8") as handle:
        handle.write(
            '<?xml version="1.0" encoding="utf-8"?>'
            "<Project><CreateTextObjects>"
            '<CreateTextObject Path="{path}" Name="{name}" Kind="{kind}">'
            "<Declaration>VAR_GLOBAL\n    value : BOOL;\nEND_VAR</Declaration>"
            "</CreateTextObject>"
            "</CreateTextObjects></Project>".format(
                path=path, name=name, kind=kind
            )
        )
    return patch_path


def test_pre_existing_object_is_not_reported_as_created(tmp_path):
    """The object is already in the application: apply_patch reused it, so it
    belongs in reused_paths -- reporting it created is the exact misreport T49
    asked to rule out."""
    project = _project_with(["ExistingGvl"])
    patch_path = _write_patch(tmp_path, "Device/Application/ExistingGvl.st", "ExistingGvl")

    result = patch_module.apply_patch(None, project, patch_path)

    assert result
    assert result.created_paths == []
    assert result.reused_paths == ["Device/Application/ExistingGvl.st"]


def test_new_object_is_still_reported_as_created(tmp_path):
    """The other side of the same coin: a real creation stays a creation."""
    project = _project_with([])
    patch_path = _write_patch(tmp_path, "Device/Application/BrandNewGvl.st", "BrandNewGvl")

    result = patch_module.apply_patch(None, project, patch_path)

    assert result
    assert result.created_paths == ["Device/Application/BrandNewGvl.st"]
    assert result.reused_paths == []


def test_summary_names_the_reuse_not_a_creation(tmp_path):
    """summary() is what the import popup and a failed apply show; it must not
    claim a creation for a patch that only found its objects already present."""
    project = _project_with(["ExistingGvl"])
    patch_path = _write_patch(tmp_path, "Device/Application/ExistingGvl.st", "ExistingGvl")

    result = patch_module.apply_patch(None, project, patch_path)

    summary = result.summary()
    assert "reused=1" in summary
    assert "created=" not in summary
