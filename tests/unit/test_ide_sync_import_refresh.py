# -*- coding: utf-8 -*-
"""
test_ide_sync_import_refresh.py — the post-import manifest re-baseline gate.

manifest.json is the only record of which view files are managed, and only an
export writes it. So an import that does not refresh it leaves compare
reporting the very changes it just applied — forever — and every later import
re-applies them.

The refresh regenerates view files from the IDE, which is safe only once every
disk edit has actually reached the IDE. These tests pin the two halves of that
rule: refresh when the IDE is a valid baseline, and never when a file on disk
still holds the only copy of an edit.

Saving is deliberately not part of that rule — export reads the live in-memory
project, not the .project file, so an unsaved import is still a faithful
baseline. Whether to save is the user's call, which `_save_requested` pins.

The daemon modules are IronPython-only, so their CODESYS/.NET dependencies are
stubbed before import.
"""

import importlib.machinery
import importlib.util
import os
import sys
import types


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
            "ide_handlers_sync_refresh_under_test",
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


# ── _refresh_requested ─────────────────────────────────────────────────────


def test_refresh_is_on_by_default():
    """Convergence is the default; opting out has to be deliberate."""
    assert sync._refresh_requested({}) is True
    assert sync._refresh_requested(None) is True


def test_refresh_can_be_disabled():
    assert sync._refresh_requested({"refresh": False}) is False


def test_refresh_accepts_string_falsehoods():
    """Params cross a JSON pipe and a shell; "false" must not read as true."""
    for value in ("false", "False", "0", "no", "off"):
        assert sync._refresh_requested({"refresh": value}) is False
    for value in ("true", "1", "yes"):
        assert sync._refresh_requested({"refresh": value}) is True


# ── _save_requested ────────────────────────────────────────────────────────


def test_save_is_off_by_default():
    """Saving commits everything else open in the IDE: the user opts in."""
    assert sync._save_requested({}) is False
    assert sync._save_requested(None) is False


def test_save_can_be_requested():
    assert sync._save_requested({"save": True}) is True


def test_save_accepts_string_truths():
    """Params cross a JSON pipe and a shell; "false" must not read as true."""
    for value in ("true", "True", "1", "yes", "on"):
        assert sync._save_requested({"save": value}) is True
    for value in ("false", "False", "0", "no", "off", ""):
        assert sync._save_requested({"save": value}) is False


# ── _refresh_blockers ──────────────────────────────────────────────────────


def _blockers(**overrides):
    kwargs = {
        "mutated": True,
        "failed_text": [],
        "failed_native": [],
        "skipped_projection_objects": [],
    }
    kwargs.update(overrides)
    return sync._refresh_blockers(**kwargs)


def test_clean_import_is_refreshed():
    """Everything reached the IDE: the live project is a valid baseline.

    Notably without a save: export reads the in-memory project, so an
    unsaved-but-applied import is still something the manifest may record.
    """
    assert _blockers() == ""


def test_untouched_project_is_not_refreshed():
    """Nothing was applied, so there is nothing to re-baseline."""
    assert _blockers(mutated=False) == ""


def test_failed_text_create_blocks_refresh():
    """The .st of a failed create is the only copy of that code."""
    blockers = _blockers(failed_text=[{"name": "fcQueuePut", "error": "boom"}])
    assert "failed to be created" in blockers
    assert "1 object(s)" in blockers


def test_failed_native_create_blocks_refresh():
    blockers = _blockers(failed_native=[{"name": "Visu_Main", "error": "boom"}])
    assert "failed to be created" in blockers


def test_failed_counts_are_summed():
    blockers = _blockers(
        failed_text=[{"name": "a"}, {"name": "b"}],
        failed_native=[{"name": "c"}],
    )
    assert "3 object(s)" in blockers


def test_skipped_projection_blocks_refresh():
    """A projection that could not be applied still lives on disk alone."""
    blockers = _blockers(
        skipped_projection_objects=[{"name": "GVL_HMI", "format": "csv"}]
    )
    assert "not applied" in blockers


def test_failure_outranks_a_skipped_projection():
    """The most fundamental reason is the one worth reporting."""
    blockers = _blockers(
        failed_text=[{"name": "a"}],
        skipped_projection_objects=[{"name": "GVL_HMI"}],
    )
    assert "failed to be created" in blockers
