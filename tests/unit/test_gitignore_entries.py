# -*- coding: utf-8 -*-
"""The recommended ``.gitignore`` entries cover every generated directory.

The sync folder is a user's project folder first and a sync root second, so a
directory the tool generates there is noise in their repository unless it is
ignored. ``cts docs`` writes ``.cts-docs/`` beside the view root by default,
and it was missing from the recommended set.
"""

import importlib.util
import sys
from pathlib import Path

BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)


def _stub(name, **attributes):
    module = type(sys)(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_options_operation():
    """Load the bridge module with its sibling imports stubbed out.

    The module reaches ``codesys_runtime``/``codesys_utils`` at import time,
    which only exist inside CODESYS; here only the ``.gitignore`` helper is
    under test.
    """
    saved = {}
    stubs = {
        "codesys_runtime": _stub("codesys_runtime", resolve_runtime=lambda *a, **k: None),
        "codesys_utils": _stub(
            "codesys_utils",
            load_base_dir=lambda *a, **k: ("", None),
            init_logging=lambda *a, **k: None,
            resolve_projects=lambda *a, **k: None,
        ),
    }
    for name, module in stubs.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    try:
        spec = importlib.util.spec_from_file_location(
            "codesys_options_operation_under_test",
            BRIDGE_DIR / "codesys_options_operation.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


options = _load_options_operation()


def test_the_docs_bundle_is_in_the_recommended_entries():
    assert ".cts-docs/" in options.RECOMMENDED_GITIGNORE_ENTRIES


def test_ensure_gitignore_writes_the_docs_bundle_entry(tmp_path):
    result = options._ensure_gitignore_entries(str(tmp_path))

    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".cts-docs/" in text
    assert ".cts-docs/" in result["added"]


def test_running_twice_adds_nothing(tmp_path):
    options._ensure_gitignore_entries(str(tmp_path))
    second = options._ensure_gitignore_entries(str(tmp_path))

    assert second["added"] == []
    assert second["migrated"] == []


def test_an_existing_docs_entry_is_left_alone(tmp_path):
    (tmp_path / ".gitignore").write_text(".cts-docs/\n", encoding="utf-8")

    result = options._ensure_gitignore_entries(str(tmp_path))

    assert ".cts-docs/" not in result["added"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count(".cts-docs/") == 1
