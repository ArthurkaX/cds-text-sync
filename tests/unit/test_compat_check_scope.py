# -*- coding: utf-8 -*-
"""test_compat_check_scope.py — the IronPython gate must cover the host tree.

``tools/compat_check.py`` is what stands between a Python-3-only construct and
a SyntaxError dialog on the CODESYS VM.  It used to lint a hand-maintained list
of 22 modules, which drifted: a daemon module importing a new shared helper
stayed unchecked, and the missing coding cookie in ``cts_shared/coerce.py``
only surfaced live.  These tests pin the replacement contract:

* the default set is *computed* -- every bridge module, everything they import
  from the repo, and the explicit entrypoints;
* a module dropped into ``ide_bridge/`` is covered with no edit to the tool;
* repo-local imports are followed, including relative ones inside a package;
* the documented exclusion hook keeps a deliberately CPython-only file out;
* the discovered set lints clean today.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPAT_CHECK = _ROOT / "tools" / "compat_check.py"
_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"


@pytest.fixture(scope="module")
def compat():
    spec = importlib.util.spec_from_file_location(
        "compat_check_under_test", str(_COMPAT_CHECK)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Modules that must be in the default set.  The daemon and apply-patch modules
# are the ones the old list missed entirely; the engine and shared modules are
# only reachable transitively; the entrypoints are only reachable by path.
REPRESENTATIVE = [
    "products/codesys-host/src/ide_bridge/ide_daemon_helpers.py",
    "products/codesys-host/src/ide_bridge/ide_apply_patch.py",
    "products/codesys-host/src/ide_bridge/ide_online_helpers.py",
    "products/codesys-host/src/ide_bridge/ide_handlers_project.py",
    "products/codesys-host/src/ide_bridge/ide_reverse_pipe_loop.py",
    "shared/src/cts_shared/coerce.py",
    "shared/src/cts_shared/st/blanking.py",
    "products/cds-text-sync/src/cds_text_sync/engine/_project_settings.py",
    "products/codesys-host/cds_bootstrap.py",
    "products/codesys-host/headless/plc_crc.py",
]


def test_representative_host_modules_are_gated(compat):
    missing = [rel for rel in REPRESENTATIVE if rel not in compat.DEFAULT_FILES]

    assert not missing, "no longer gated: {0}".format(missing)


def test_every_bridge_module_is_gated(compat):
    on_disk = {path.name for path in _BRIDGE.glob("*.py")}
    gated = {os.path.basename(path) for path in compat.discover_default_files()}

    assert on_disk <= gated, "bridge modules left out: {0}".format(
        sorted(on_disk - gated)
    )


def test_a_new_bridge_module_is_covered_without_an_edit(compat, tmp_path):
    """Dropping a file into the bridge directory is enough to gate it."""
    bridge = tmp_path / "ide_bridge"
    bridge.mkdir()
    (bridge / "dep.py").write_text("VALUE = 1\n", encoding="utf-8")
    (bridge / "new_thing.py").write_text("import dep\n", encoding="utf-8")

    found = compat.discover_default_files(
        bridge_dir=str(bridge), search_roots=(str(bridge),), entrypoints=[]
    )
    names = {os.path.basename(path) for path in found}

    assert names == {"new_thing.py", "dep.py"}


def test_repo_local_imports_are_followed(compat, tmp_path):
    bridge = tmp_path / "ide_bridge"
    bridge.mkdir()
    (bridge / "seed.py").write_text("import lookup.helper\n", encoding="utf-8")

    package = tmp_path / "lookup" / "lookup"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("HELP = 1\n", encoding="utf-8")

    found = compat.discover_default_files(
        bridge_dir=str(bridge),
        search_roots=(str(bridge), str(tmp_path / "lookup")),
        entrypoints=[],
    )

    assert {os.path.basename(path) for path in found} == {
        "seed.py",
        "helper.py",
        "__init__.py",
    }


def test_relative_imports_inside_a_package_are_followed(compat, tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "sibling.py").write_text("SIB = 1\n", encoding="utf-8")
    (package / "entry.py").write_text("from . import sibling\n", encoding="utf-8")

    found = compat.discover_default_files(
        bridge_dir=str(tmp_path / "absent"),
        search_roots=(str(tmp_path),),
        entrypoints=[str(package / "entry.py")],
    )

    assert str(package / "sibling.py") in found


def test_repo_relative_imports_are_absolute(compat):
    """``st/formatting.py`` imports ``.blanking``; the name must resolve."""
    names = compat._module_names_imported(
        str(_ROOT / "shared" / "src" / "cts_shared" / "st" / "formatting.py")
    )

    assert "cts_shared.st.blanking" in names


def test_a_documented_exclusion_keeps_a_file_out(compat, tmp_path):
    bridge = tmp_path / "ide_bridge"
    bridge.mkdir()
    keep = bridge / "keep.py"
    keep.write_text("VALUE = 1\n", encoding="utf-8")
    drop = bridge / "cpython_only.py"
    drop.write_text("VALUE = 2\n", encoding="utf-8")

    found = compat.discover_default_files(
        bridge_dir=str(bridge),
        search_roots=(str(bridge),),
        entrypoints=[],
        excluded={os.path.normpath(str(drop)): "runs under CPython only"},
    )

    assert found == [os.path.normpath(str(keep))]


def test_the_discovered_set_lints_clean(compat):
    paths = [os.path.join(compat.ROOT, rel) for rel in compat.DEFAULT_FILES]

    assert compat.lint(paths) == 0


# ---------------------------------------------------------------------------
# Python 3-only stdlib: imports and calls
# ---------------------------------------------------------------------------

_GUARDED_FILE = """\
try:
    import pathlib
except ImportError:
    pathlib = None
"""


def _errors(compat, tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    errors, _warnings = compat._findings(str(path))
    return errors


def test_a_py3_only_import_is_flagged(compat, tmp_path):
    errors = _errors(compat, tmp_path, "a.py", "import pathlib\n")

    assert any("pathlib" in error for error in errors)


def test_a_py3_only_from_import_is_flagged(compat, tmp_path):
    errors = _errors(compat, tmp_path, "a.py", "from concurrent.futures import ThreadPoolExecutor\n")

    assert any("concurrent" in error for error in errors)


def test_a_py3_only_attribute_is_flagged(compat, tmp_path):
    errors = _errors(compat, tmp_path, "a.py", "import subprocess\nsubprocess.run(['x'])\n")

    assert any("subprocess.run" in error for error in errors)


def test_a_py3_only_keyword_is_flagged(compat, tmp_path):
    errors = _errors(compat, tmp_path, "a.py", "import os\nos.makedirs('a', exist_ok=True)\n")

    assert any("exist_ok" in error for error in errors)


def test_a_guarded_import_is_not_flagged(compat, tmp_path):
    errors = _errors(compat, tmp_path, "a.py", _GUARDED_FILE)

    assert not errors


def test_plain_importlib_is_not_flagged(compat, tmp_path):
    """``importlib`` exists in 2.7; only ``importlib.resources`` does not."""
    errors = _errors(compat, tmp_path, "a.py", "import importlib\n")

    assert not errors
