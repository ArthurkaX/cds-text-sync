# -*- coding: utf-8 -*-
"""
test_engine_single_import.py -- one canonical name per engine module.

The engine modules used to be importable both flat (``import xml_helpers``,
with ``engine/`` on sys.path) and as a package (``cds_text_sync.engine.xml_helpers``).
Two names meant two module objects for one file, so a monkeypatch on one did
not reach the other and module state could diverge. The CLI entry point and the
engine CLI both reach the engine through the package now; this test fails if a
second, flat copy ever comes back into ``sys.modules``.

Only the import side is asserted. Whether the process that runs
``python -m cds_text_sync.engine.engine_cli`` re-imports anything is not
observable from here -- that is a separate process.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ENGINE_DIR = (
    Path(__file__).resolve().parents[2]
    / "products"
    / "cds-text-sync"
    / "src"
    / "cds_text_sync"
    / "engine"
)
ENGINE_MODULE_NAMES = sorted(
    path.stem for path in ENGINE_DIR.glob("*.py") if path.stem != "__init__"
)


def test_cli_and_engine_load_each_engine_module_once():
    # The CLI entry point pulls in the engine package; engine_cli is also the
    # module the host and `cts engine` launch by package path.
    import cds_cli.main  # noqa: F401
    importlib.import_module("cds_text_sync.engine.engine_cli")

    duplicated = []
    for name in ENGINE_MODULE_NAMES:
        canonical = "cds_text_sync.engine." + name
        if name in sys.modules and canonical in sys.modules:
            duplicated.append(name)
        if canonical in sys.modules:
            loaded = Path(sys.modules[canonical].__file__).resolve()
            assert loaded == (ENGINE_DIR / (name + ".py")).resolve()

    assert duplicated == []


def test_engine_cli_is_importable_as_a_package_module():
    module = importlib.import_module("cds_text_sync.engine.engine_cli")
    assert module.__name__ == "cds_text_sync.engine.engine_cli"
    assert callable(module.main)
