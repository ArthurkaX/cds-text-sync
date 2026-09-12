# -*- coding: utf-8 -*-
"""
test_no_shadowed_import_use.py — Static guard against UnboundLocalError from a
function-level import that shadows a module-level one.

A function-level ``from x import y`` makes ``y`` local for the *whole* function
body, even at lines that run before the import. If the module also imports
``y`` at the top, every earlier use inside that function raises
UnboundLocalError instead of reaching the module-level name.

This actually shipped: ``cds_cli/main.py`` imported ``_print_error`` again
inside ``main()`` for the ``docs --daemon`` branch, which made every ``visu``
error path several hundred lines above it crash with
``UnboundLocalError: cannot access local variable '_print_error'`` -- so real
error messages arrived buried in a traceback.

Duplicate imports that sit before every use in their function are merely
redundant, not broken, so this guard flags only the use-before-local-import
shape. The fix is always the same: delete the redundant local import.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PRODUCTS = Path(__file__).parent.parent.parent / "products"
assert _PRODUCTS.is_dir(), f"products/ not found at {_PRODUCTS}"


def _module_level_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _shadowing_imports(func: ast.AST, module_names: set[str]) -> dict[str, int]:
    """Names imported inside *func* that the module already imports -> line."""
    found: dict[str, int] = {}
    for node in ast.walk(func):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if name in module_names:
                    found.setdefault(name, node.lineno)
    return found


def _loads_before(func: ast.AST, name: str, line: int) -> list[int]:
    lines = [
        node.lineno
        for node in ast.walk(func)
        if isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Load)
        and node.lineno < line
    ]
    lines += [
        node.value.lineno
        for node in ast.walk(func)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == name
        and node.value.lineno < line
    ]
    return sorted(set(lines))


def test_no_function_uses_a_name_before_its_own_shadowing_import():
    offenders = []
    for path in sorted(_PRODUCTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue  # IronPython-only syntax; the daemon guards cover those
        module_names = _module_level_names(tree)
        if not module_names:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for name, line in _shadowing_imports(func, module_names).items():
                uses = _loads_before(func, name, line)
                if uses:
                    offenders.append(
                        "{0}:{1} {2}() reads {3!r} at line(s) {4} but imports it "
                        "locally below -- delete the local import".format(
                            path.relative_to(_PRODUCTS.parent),
                            line,
                            func.name,
                            name,
                            uses,
                        )
                    )
    assert not offenders, "UnboundLocalError waiting to happen:\n" + "\n".join(
        offenders
    )
