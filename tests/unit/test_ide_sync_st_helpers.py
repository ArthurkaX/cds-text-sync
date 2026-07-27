# -*- coding: utf-8 -*-
"""
test_ide_sync_st_helpers.py – Unit tests for the pure ST-splitting helpers in
``ide_handlers_sync.py``.

These helpers (``_split_st_update_content`` / ``_split_st_content``) are pure
string functions but live in a daemon module that imports the CODESYS .NET
runtime at module load. We import the module with the runtime stubbed out so
the helpers can be exercised without a live CODESYS instance.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locate ide_bridge directory
# ---------------------------------------------------------------------------

_IDE_BRIDGE = Path(__file__).parent.parent.parent / "src" / "ide_bridge"
assert _IDE_BRIDGE.is_dir(), f"ide_bridge not found at {_IDE_BRIDGE}"


# ---------------------------------------------------------------------------
# .NET / CODESYS runtime stubbing (mirrors test_daemon_name_resolution.py)
# ---------------------------------------------------------------------------


class _AutoStub:
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self

    def __iter__(self):
        return iter([])


_STUB = _AutoStub()


def _make_stub_module(name):
    mod = types.ModuleType(name)
    mod.__spec__ = None

    def _getattr(attr):
        return _STUB

    mod.__getattr__ = _getattr
    return mod


_STUB_NAMES = [
    "clr",
    "System",
    "scriptengine",
    "online",
    "projects",
    "scriptengine_events",
]


@pytest.fixture
def sync_module():
    """Import ide_handlers_sync with CODESYS runtime stubbed out."""
    saved = {}
    for name in _STUB_NAMES:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = _make_stub_module(name)

    if str(_IDE_BRIDGE) not in sys.path:
        sys.path.insert(0, str(_IDE_BRIDGE))

    # Evict any cached copy so we always import fresh.
    evicted = sys.modules.pop("ide_handlers_sync", None)
    evicted_common = sys.modules.pop("ide_runtime_common", None)
    evicted_state = sys.modules.pop("ide_daemon_state", None)
    evicted_helpers = sys.modules.pop("ide_daemon_helpers", None)

    try:
        mod = importlib.import_module("ide_handlers_sync")
        yield mod
    finally:
        for key in (
            "ide_handlers_sync",
            "ide_runtime_common",
            "ide_daemon_state",
            "ide_daemon_helpers",
        ):
            sys.modules.pop(key, None)
        # Restore prior module cache entries.
        if evicted is not None:
            sys.modules["ide_handlers_sync"] = evicted
        if evicted_common is not None:
            sys.modules["ide_runtime_common"] = evicted_common
        if evicted_state is not None:
            sys.modules["ide_daemon_state"] = evicted_state
        if evicted_helpers is not None:
            sys.modules["ide_daemon_helpers"] = evicted_helpers

        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


# ---------------------------------------------------------------------------
# _split_st_update_content
# ---------------------------------------------------------------------------


class TestSplitStUpdateContent:
    def test_marked_content_splits_into_decl_and_impl(self, sync_module):
        content = (
            "ACTION DoAct\n"
            "// --- implementation ---\n"
            "\n"
            "outVal := 999;"
        )
        decl, impl = sync_module._split_st_update_content(content)
        assert "ACTION DoAct" in decl
        assert impl == "outVal := 999;"

    def test_bare_implementation_goes_to_impl_not_decl(self, sync_module):
        """Regression: a bare implementation body (no marker, as produced by
        ``cts export`` for declaration-less POU children such as ACTIONs) used
        to be returned as the *declaration* with an empty implementation.
        That caused ``_apply_text_to_object`` to write the body into
        ``textual_declaration`` and skip the implementation entirely, so
        edits to an exported ACTION never reached the IDE. The body must be
        treated as the implementation when no marker is present."""
        content = "testVal := 2;"  # bare body, no marker
        decl, impl = sync_module._split_st_update_content(content)
        assert decl == ""
        assert impl == "testVal := 2;"

    def test_empty_content_returns_empty_pair(self, sync_module):
        decl, impl = sync_module._split_st_update_content("")
        assert decl == ""
        assert impl == ""

    def test_none_content_returns_empty_pair(self, sync_module):
        decl, impl = sync_module._split_st_update_content(None)
        assert decl == ""
        assert impl == ""


# ---------------------------------------------------------------------------
# _split_st_content (creation path)
# ---------------------------------------------------------------------------


class TestSplitStContent:
    def test_marked_content_splits_and_strips_end_keyword(self, sync_module):
        content = (
            "FUNCTION_BLOCK FB_X\n"
            "VAR_INPUT\n  in : INT;\nEND_VAR\n"
            "// --- implementation ---\n"
            "\n"
            "out := in;\n"
            "END_FUNCTION_BLOCK"
        )
        decl, impl = sync_module._split_st_content(content)
        assert "FUNCTION_BLOCK FB_X" in decl
        assert "END_FUNCTION_BLOCK" not in impl  # stripped (API re-adds it)
        assert "out := in;" in impl

    def test_bare_implementation_goes_to_impl_not_decl(self, sync_module):
        """Same regression class as the update path: a bare body must be
        treated as implementation, not declaration."""
        content = "testVal := 5;"
        decl, impl = sync_module._split_st_content(content)
        assert decl == ""
        assert impl == "testVal := 5;"
