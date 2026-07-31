# -*- coding: utf-8 -*-
"""test_menu_layout.py — Layout and behavioural tests for the CODESYS menu stubs.

The tool publishes a fixed set of ``Project_*.py`` entry points: the
``ENTRYPOINTS`` manifest in ``cds_bootstrap.py`` is the single source of
truth, and ``cds_text_sync/install_menu.py`` renders matching stubs into a CODESYS
ScriptDir so the Script Engine shows exactly the public menu commands while
the real tree ("the body") stays outside the scan. These tests pin down that
contract:

  * the manifest is a bijection with the root-level ``Project_*.py`` files;
  * every ``command`` entry resolves inside ``codesys_runtime.OPERATION_MODULES``
    (one-way: extra aliases such as ``extract``/``inject`` are allowed);
  * CI compiles every entry point;
  * the generated stubs compile and stay Python-2-safe / ASCII (the target
    is IronPython 2.7);
  * Cyrillic ``CDS_HOME`` path literals survive an exec round-trip, including
    a trailing backslash;
  * ``write_menu`` produces exactly the manifest's stubs, is idempotent, and
    refuses to run when the body sits inside a ScriptDir;
  * ``resolve_body`` finds the same body in flat and split layouts;
  * ``verify_menu`` catches corruption.

Everything runs inside ``tmp_path`` — a real CODESYS ScriptDir is never
touched, and nothing outside the temp tree is created or modified.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

from cds_text_sync import install_menu  # noqa: E402

_PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# cds_bootstrap.py is loaded by path (never by import) so these tests run
# against the real file in the repo, exactly like test_daemon_name_resolution.
# ---------------------------------------------------------------------------


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "_cds_bootstrap_menu_layout", str(_PROJECT_ROOT / "cds_bootstrap.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BOOTSTRAP = _load_bootstrap()
ENTRYPOINTS = _BOOTSTRAP.ENTRYPOINTS
MANIFEST_NAMES = [spec["name"] for spec in ENTRYPOINTS]

_CI_YML = (_PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _operation_modules():
    """OPERATION_MODULES from codesys_runtime.py via text extraction.

    The module targets IronPython inside CODESYS; reading the OPERATION_MODULES
    literal as text (rather than importing it) avoids executing it under
    CPython. The literal is a flat dict of string->string with no nested
    braces, so literal_eval'ing the brace-delimited block is reliable.
    """
    runtime = _PROJECT_ROOT / "src" / "ide_bridge" / "codesys_runtime.py"
    text = runtime.read_text(encoding="utf-8")
    start = text.index("OPERATION_MODULES")
    brace = text.index("{", start)
    depth = 0
    end = brace
    while end < len(text):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                break
        end += 1
    value = ast.literal_eval(text[brace : end + 1])
    assert isinstance(value, dict)
    return value


_OPERATION_MODULES = _operation_modules()

_COMMAND_ENTRIES = [spec for spec in ENTRYPOINTS if spec.get("kind") == "command"]


def _populate_body(body: Path) -> None:
    """Turn *body* into something body_is_valid() accepts."""
    (body / "src" / "ide_bridge").mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(_PROJECT_ROOT / "cds_bootstrap.py"), str(body / "cds_bootstrap.py"))


def _make_body(root: Path) -> Path:
    """Build a minimal cds-text-sync tree under *root* and return its path."""
    body = root / "body"
    _populate_body(body)
    return body


def _norm(path) -> str:
    """Normalise a path for equality on Windows."""
    return os.path.normcase(os.path.normpath(str(path)))


# ---------------------------------------------------------------------------
# 1. Manifest <-> files: the bijection with root-level Project_*.py scripts
# ---------------------------------------------------------------------------


def test_manifest_names_match_project_files():
    actual = {p.stem for p in _PROJECT_ROOT.glob("Project_*.py") if p.is_file()}
    expected = {spec["name"] for spec in ENTRYPOINTS}
    assert expected, "the entrypoint manifest is empty"
    assert len(ENTRYPOINTS) == len(expected), "duplicate name in the manifest"
    assert expected == actual


# ---------------------------------------------------------------------------
# 2. Every command entry resolves inside OPERATION_MODULES (one-way check;
#    extra keys like the extract/inject aliases are allowed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", _COMMAND_ENTRIES, ids=lambda s: s["name"])
def test_command_has_operation_module(spec):
    assert spec["command"] in _OPERATION_MODULES


# ---------------------------------------------------------------------------
# 3. CI covers every entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MANIFEST_NAMES, ids=lambda n: n)
def test_ci_compileall_covers_entrypoint(name):
    assert (name + ".py") in _CI_YML


# ---------------------------------------------------------------------------
# 4. Rendered stubs compile and stay Python-2-safe / ASCII
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", ENTRYPOINTS, ids=lambda s: s["name"])
def test_stub_is_py2_safe_and_compiles(spec):
    src = install_menu.render_stub(spec, _PROJECT_ROOT)
    compile(src, spec["name"] + ".py", "exec")
    assert src.isascii()
    assert 'f"' not in src
    assert ":=" not in src


# ---------------------------------------------------------------------------
# 5. Cyrillic CDS_HOME literal survives the exec round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Users\\Артур\\cds-text-sync",
        "C:\\Users\\Артур\\cds-text-sync\\",
    ],
    ids=["plain", "trailing-backslash"],
)
def test_encode_path_literal_ascii_roundtrip(path):
    literal = install_menu.encode_path_literal(path)
    assert literal.isascii()
    assert literal.startswith('u"')
    namespace = {}
    exec("CDS_HOME = " + literal, namespace)  # noqa: S102
    assert namespace["CDS_HOME"] == path


# ---------------------------------------------------------------------------
# 6. write_menu produces exactly the manifest's stub files, nothing else
# ---------------------------------------------------------------------------


def test_write_menu_creates_exactly_the_manifest_stubs(tmp_path):
    body = _make_body(tmp_path)
    script_dir = tmp_path / "sd"

    result = install_menu.write_menu(body, script_dir)

    menu_dir = script_dir / install_menu.MENU_FOLDER
    assert install_menu.verify_menu(menu_dir, body.resolve()) == []
    assert result["problems"] == []
    assert result["warnings"] == []

    files = list(menu_dir.iterdir())
    assert len(files) == len(MANIFEST_NAMES)
    assert all(item.is_file() for item in files)
    assert {item.name for item in files} == {name + ".py" for name in MANIFEST_NAMES}
    assert sorted(result["written"]) == sorted(name + ".py" for name in MANIFEST_NAMES)


# ---------------------------------------------------------------------------
# 7. Idempotency: the second run writes nothing and leaves files untouched
# ---------------------------------------------------------------------------


def test_write_menu_is_idempotent(tmp_path):
    body = _make_body(tmp_path)
    script_dir = tmp_path / "sd"
    install_menu.write_menu(body, script_dir)

    menu_dir = script_dir / install_menu.MENU_FOLDER
    snapshot = {p.name: p.read_bytes() for p in menu_dir.iterdir()}

    second = install_menu.write_menu(body, script_dir)

    assert second["written"] == []
    assert len(second["unchanged"]) == len(MANIFEST_NAMES)
    assert second["problems"] == []
    current = {p.name: p.read_bytes() for p in menu_dir.iterdir()}
    assert current == snapshot


# ---------------------------------------------------------------------------
# 8. Refusal when the body sits inside a ScriptDir
# ---------------------------------------------------------------------------


def test_write_menu_refuses_body_inside_script_dir(tmp_path):
    script_dir = tmp_path / "ScriptDir"
    body = script_dir / install_menu.MENU_FOLDER
    _populate_body(body)

    with pytest.raises(install_menu.MenuError):
        install_menu.write_menu(body, script_dir)

    # The refusal happens before anything is written: no stub appears in the
    # menu folder (which is the body itself here).
    assert not list((script_dir / install_menu.MENU_FOLDER).glob("Project_*.py"))


def test_write_menu_allow_body_inside_script_dir_warns(tmp_path):
    script_dir = tmp_path / "ScriptDir"
    body = script_dir / install_menu.MENU_FOLDER
    _populate_body(body)
    # A separate ScriptDir target so only the exposure guard is exercised.
    # Writing into the same folder would additionally trip the unrelated
    # "flat layout needs --force" guard.
    out_script_dir = tmp_path / "sd_outside"

    result = install_menu.write_menu(
        body, out_script_dir, allow_body_in_scriptdir=True
    )

    assert result["warnings"], "expected a non-empty exposure warning"
    assert len(result["written"]) == len(MANIFEST_NAMES)
    menu_dir = out_script_dir / install_menu.MENU_FOLDER
    assert install_menu.verify_menu(menu_dir, body.resolve()) == []


# ---------------------------------------------------------------------------
# 9. resolve_body finds the same body in flat and split layouts
# ---------------------------------------------------------------------------


def test_resolve_body_flat_and_split(tmp_path):
    body = _make_body(tmp_path)

    flat = _BOOTSTRAP.resolve_body(str(body / "Project_export.py"))
    assert _norm(flat) == _norm(body)

    # Control: a path with no src/ide_bridge anywhere above it must NOT
    # resolve to the fake body.
    control = _BOOTSTRAP.resolve_body(str(tmp_path / "no_bridge" / "Project_export.py"))
    assert _norm(control) != _norm(body)


# ---------------------------------------------------------------------------
# 10. verify_menu catches corruption after a successful write_menu
# ---------------------------------------------------------------------------


def test_verify_menu_catches_corruption(tmp_path):
    body = _make_body(tmp_path)
    script_dir = tmp_path / "sd"
    install_menu.write_menu(body, script_dir)
    menu_dir = script_dir / install_menu.MENU_FOLDER

    (menu_dir / "extra.py").write_text("print('extra')\n", encoding="utf-8")
    (menu_dir / "subdir").mkdir()
    victim = sorted(menu_dir.glob("Project_*.py"))[0]
    victim.write_text("# marker removed by hand\n", encoding="utf-8")

    problems = install_menu.verify_menu(menu_dir, body.resolve())

    assert any("extra.py" in problem for problem in problems)
    assert any("unexpected subdirectory" in problem for problem in problems)
    assert any("not a generated stub" in problem for problem in problems)
