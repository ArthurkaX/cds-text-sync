# -*- coding: utf-8 -*-
"""
test_daemon_deferred_imports.py — AST guard for deferred cross-module imports.

Catches `from <sibling> import <name>` where the sibling module does not
actually define or re-export <name>, including imports written inside function
bodies.  Pure AST: parse only, never import, so WinForms-only UI modules are
covered too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locate ide_bridge directory
# ---------------------------------------------------------------------------

_IDE_BRIDGE = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)
assert _IDE_BRIDGE.is_dir(), f"ide_bridge not found at {_IDE_BRIDGE}"

# ---------------------------------------------------------------------------
# Module discovery
# ---------------------------------------------------------------------------

SIBLING_STEMS = {p.stem for p in _IDE_BRIDGE.glob("*.py")}


# ---------------------------------------------------------------------------
# AST export analysis
# ---------------------------------------------------------------------------

_EXPORT_CACHE: dict[Path, tuple[set[str], bool]] = {}


def _module_exports(path: Path) -> tuple[set[str], bool]:
    """Return ``(exported_names, has_star_import)`` for *path*.

    Collects top-level names (functions, classes, variables, re-imports)
    without descending into function/class bodies.  Descends into
    ``if``/``try``/``with`` bodies since those commonly guard optional
    imports.
    """
    if path in _EXPORT_CACHE:
        return _EXPORT_CACHE[path]

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    has_star = _visit_nodes(tree.body, names)
    _EXPORT_CACHE[path] = (names, has_star)
    return names, has_star


def _visit_nodes(nodes, names: set[str]) -> bool:
    """Walk *nodes* collecting exported names; return True if a star import was seen.

    Traverses into ``if``/``try``/``with`` bodies but not into function/class defs.
    """
    has_star = False
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                _collect_names_from_target(target, names)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name.split(".")[0]
                names.add(name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    has_star = True
                else:
                    name = alias.asname if alias.asname else alias.name
                    names.add(name)

        # Descend into if/try/with bodies, but NOT into function/class defs
        if isinstance(node, ast.If):
            has_star |= _visit_nodes(node.body, names)
            has_star |= _visit_nodes(node.orelse, names)
        elif isinstance(node, ast.Try):
            has_star |= _visit_nodes(node.body, names)
            for handler in node.handlers:
                has_star |= _visit_nodes(handler.body, names)
            has_star |= _visit_nodes(node.orelse, names)
            has_star |= _visit_nodes(node.finalbody, names)
        elif isinstance(node, ast.With):
            has_star |= _visit_nodes(node.body, names)
    return has_star


def _collect_names_from_target(target, names: set[str]) -> None:
    """Recursively extract ``ast.Name`` ids from an assignment target."""
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_names_from_target(elt, names)


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------

_ALL_FILES = sorted(_IDE_BRIDGE.glob("*.py"))


@pytest.mark.parametrize("path", _ALL_FILES, ids=[p.stem for p in _ALL_FILES])
def test_deferred_cross_module_imports(path: Path) -> None:
    """Every ``from <sibling> import <name>`` must reference a defined or re-exported name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue

        # Skip relative imports and module-internal
        if node.level != 0:
            continue
        if node.module is None:
            continue
        if node.module not in SIBLING_STEMS:
            continue
        if node.module == path.stem:
            continue

        # Load the target module's exports
        target_path = _IDE_BRIDGE / f"{node.module}.py"
        target_exports, has_star = _module_exports(target_path)
        if has_star:
            continue

        for alias in node.names:
            if alias.name == "*":
                continue
            if alias.name not in target_exports:
                violations.append(
                    f"{path.name}:{node.lineno}: from {node.module} import {alias.name} "
                    f"-- {node.module}.py does not define or re-export {alias.name}"
                )

    assert not violations, "\n".join(violations)
