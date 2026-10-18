# -*- coding: utf-8 -*-
"""test_compat_check_scope.py — the IronPython gate: what it flags and that the
headless CRC script CODESYS runs passes it.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPAT_CHECK = _ROOT / "tools" / "compat_check.py"


@pytest.fixture(scope="module")
def compat():
    spec = importlib.util.spec_from_file_location(
        "compat_check_under_test", str(_COMPAT_CHECK)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_host_set_lints_clean(compat):
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


# ---------------------------------------------------------------------------
# Aliased imports are resolved (T56)
# ---------------------------------------------------------------------------


def test_a_from_import_of_a_py3_only_attribute_is_flagged(compat, tmp_path):
    """``from subprocess import run`` raises ImportError on 2.7 by itself."""
    errors = _errors(compat, tmp_path, "a.py", "from subprocess import run\n")

    assert any("subprocess.run" in error for error in errors)


def test_a_from_import_of_os_scandir_is_flagged(compat, tmp_path):
    errors = _errors(compat, tmp_path, "a.py", "from os import scandir\n")

    assert any("os.scandir" in error for error in errors)


def test_an_aliased_module_call_is_flagged(compat, tmp_path):
    errors = _errors(
        compat, tmp_path, "a.py", "import subprocess as sp\nsp.run(['x'])\n"
    )

    assert any("subprocess.run" in error for error in errors)


def test_an_aliased_from_import_call_is_flagged(compat, tmp_path):
    errors = _errors(
        compat,
        tmp_path,
        "a.py",
        "from os import makedirs as mk\nmk('a', exist_ok=True)\n",
    )

    assert any("exist_ok" in error for error in errors)


def test_a_py3_only_import_is_reported_once(compat, tmp_path):
    """The from-import and its call must not both be flagged."""
    errors = _errors(
        compat, tmp_path, "a.py", "from subprocess import run\nrun(['x'])\n"
    )

    assert len([e for e in errors if "subprocess.run" in e]) == 1


def test_an_aliased_guarded_import_is_not_flagged(compat, tmp_path):
    text = "try:\n    import pathlib as pl\nexcept ImportError:\n    pl = None\n"

    assert not _errors(compat, tmp_path, "a.py", text)


def test_a_py3_safe_from_import_is_not_flagged(compat, tmp_path):
    """``os.makedirs`` exists in 2.7; only its ``exist_ok`` keyword does not."""
    errors = _errors(compat, tmp_path, "a.py", "from os import makedirs\n")

    assert not errors
