# -*- coding: utf-8 -*-
"""Guards for how bridge modules are found and loaded.

**Order.** Bridge modules used to be loaded by explicit file path, so sys.path
order was irrelevant. They are imported by name now, which makes the order
load-bearing: the repository root holds ``Project_snapshooter.py`` and
``src/ide_bridge`` holds ``project_snapshooter.py``. Those two differ only by
case, and Windows filesystems are case-insensitive. CPython's importer applies
a case check and refuses the mismatch, but IronPython 2.7 -- the interpreter
that actually runs this code inside CODESYS -- is not covered by that
guarantee. So do not rely on the case check: keep ``src/ide_bridge`` ahead of
the root.

**Failure reporting.** The loaders return None for a module that is absent,
because callers probe for optional modules. They must *not* return None for a
module that exists and fails to import: that turns "broken" into "missing" and
the caller degrades silently instead of surfacing the real error.
"""

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_IDE_BRIDGE = _PROJECT_ROOT / "src" / "ide_bridge"


def _load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cds_bootstrap():
    return _load_by_path("_cds_bootstrap_under_test", _PROJECT_ROOT / "cds_bootstrap.py")


def _index_of(paths, target):
    target = os.path.normcase(os.path.normpath(str(target)))
    for position, candidate in enumerate(paths):
        if os.path.normcase(os.path.normpath(candidate)) == target:
            return position
    return None


def test_ensure_runtime_path_puts_bridge_ahead_of_root(cds_bootstrap, monkeypatch):
    monkeypatch.setattr(sys, "path", [])
    cds_bootstrap.ensure_runtime_path(str(_PROJECT_ROOT / "Project_export.py"))

    bridge_at = _index_of(sys.path, _IDE_BRIDGE)
    root_at = _index_of(sys.path, _PROJECT_ROOT)

    assert bridge_at is not None, "src/ide_bridge was never added to sys.path"
    assert root_at is not None, "the body root was never added to sys.path"
    assert bridge_at < root_at, (
        "src/ide_bridge must outrank the body root on sys.path, "
        "otherwise `import project_snapshooter` can reach the root's "
        "Project_snapshooter.py on a case-insensitive filesystem"
    )


def test_runtime_ensure_sys_path_puts_bridge_ahead_of_root(monkeypatch):
    runtime = _load_by_path(
        "_codesys_runtime_under_test", _IDE_BRIDGE / "codesys_runtime.py"
    )
    monkeypatch.setattr(sys, "path", [])
    runtime._ensure_sys_path(str(_PROJECT_ROOT))

    bridge_at = _index_of(sys.path, _IDE_BRIDGE)
    root_at = _index_of(sys.path, _PROJECT_ROOT)

    assert bridge_at is not None and root_at is not None
    assert bridge_at < root_at


def test_no_bridge_module_collides_with_a_root_script():
    """Names that differ only by case are a trap on Windows.

    One collision exists on purpose (Project_snapshooter.py is the menu entry
    for project_snapshooter.py) and is handled by sys.path order. This test
    fails if a *new* one appears, so that the next case gets a deliberate
    decision rather than a silent wrong import.
    """
    known = {"project_snapshooter"}

    root_stems = {
        path.stem.lower(): path.name
        for path in _PROJECT_ROOT.glob("*.py")
    }
    collisions = {}
    for module in _IDE_BRIDGE.glob("*.py"):
        stem = module.stem.lower()
        if stem in root_stems and stem not in known:
            collisions[module.name] = root_stems[stem]

    assert not collisions, (
        "bridge modules whose names collide with a root script on a "
        "case-insensitive filesystem: %r" % (collisions,)
    )


# ---------------------------------------------------------------------------
# A broken module must not be reported as a missing one
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_body(tmp_path, monkeypatch):
    """A minimal tree with one importable, one broken and no absent module."""
    body = tmp_path / "body"
    bridge = body / "src" / "ide_bridge"
    bridge.mkdir(parents=True)
    shutil.copy(str(_PROJECT_ROOT / "cds_bootstrap.py"), str(body / "cds_bootstrap.py"))

    (bridge / "codesys_fine.py").write_text("VALUE = 'fine'\n", encoding="utf-8")
    (bridge / "codesys_broken.py").write_text(
        "import a_module_that_does_not_exist_anywhere\n", encoding="utf-8"
    )

    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in ("codesys_fine", "codesys_broken"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return body


def test_loader_returns_none_for_an_absent_module(fake_body):
    boot = _load_by_path("_boot_absent", fake_body / "cds_bootstrap.py")
    anchor = str(fake_body / "Project_export.py")
    assert boot.import_runtime_module("codesys_fine", script_file=anchor) is not None
    assert boot.import_runtime_module("codesys_absent", script_file=anchor) is None


def test_loader_reraises_when_the_module_exists_but_is_broken(fake_body):
    boot = _load_by_path("_boot_broken", fake_body / "cds_bootstrap.py")
    anchor = str(fake_body / "Project_export.py")
    with pytest.raises(ImportError):
        boot.import_runtime_module("codesys_broken", script_file=anchor)


def test_runtime_loader_reraises_when_the_module_exists_but_is_broken(fake_body):
    runtime = _load_by_path(
        "_runtime_broken", _IDE_BRIDGE / "codesys_runtime.py"
    )
    anchor = str(fake_body / "Project_export.py")
    assert runtime.load_hidden_module("codesys_absent", script_file=anchor) is None
    with pytest.raises(ImportError):
        runtime.load_hidden_module("codesys_broken", script_file=anchor)
