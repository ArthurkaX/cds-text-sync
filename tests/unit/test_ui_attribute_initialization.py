# -*- coding: utf-8 -*-
"""
test_ui_attribute_initialization.py — Static self-attribute guard for ide_bridge classes.

Catches the class of IronPython defect where a class READS ``self._foo`` but never
ASSIGNS it anywhere in the class body.  Under CPython this would be an obvious
AttributeError at first touch; inside a WinForms event handler under CODESYS it is
far worse — the handler dies mid-way, so the cleanup after the failing line never
runs.  The concrete incident this guards against: ``FmtPreviewForm._on_wizard_tick``
read ``self._is_closing`` before calling ``_stop_wizard_timer()``, and the attribute
was never initialized.  Every 15 ms tick raised AttributeError before stopping its
own timer, leaving the wizard dialog alive but permanently unable to advance.

Purely static: the guarded modules target IronPython 2.7 and need WinForms/CODESYS,
so they are parsed with ``ast`` and never imported.

Scope: every ``*.py`` directly under products/codesys-host/src/ide_bridge/.
Only underscore-prefixed attributes are checked — bare names like ``self.Text`` or
``self.IsDisposed`` are .NET base-class members that no Python source assigns.
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


def _module_files() -> list[Path]:
    return sorted(
        path
        for path in _IDE_BRIDGE.glob("*.py")
        if path.parent.name != "__pycache__"
    )


_MODULE_FILES = _module_files()
assert _MODULE_FILES, f"no modules discovered under {_IDE_BRIDGE}"


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _self_attributes(node: ast.AST) -> tuple[set[str], set[str]]:
    """Return (assigned, read) underscore-prefixed ``self.<attr>`` names in *node*.

    ``ast.Store`` covers plain assignment, augmented assignment, tuple targets,
    ``for`` targets and ``with ... as`` in one check, because the parser marks all
    of them the same way.  A ``getattr(self, "_x", default)`` call passes the name
    as a string constant rather than an Attribute node, so guarded reads never
    reach the read set — which is correct, they cannot raise.
    """
    assigned: set[str] = set()
    read: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute):
            continue
        if not isinstance(child.value, ast.Name) or child.value.id != "self":
            continue
        if not child.attr.startswith("_"):
            continue
        if isinstance(child.ctx, ast.Store):
            assigned.add(child.attr)
        elif isinstance(child.ctx, ast.Load):
            read.add(child.attr)
    return assigned, read


def _class_level_names(node: ast.ClassDef) -> set[str]:
    """Return underscore-prefixed names defined directly in the class body.

    Methods and class attributes are legitimate ``self._x`` reads that no
    ``self._x = ...`` statement ever produces.  Only the direct body counts —
    a ``def`` nested inside a method is a local, not a class member.
    """
    names: set[str] = set()
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if statement.name.startswith("_"):
                names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id.startswith("_"):
                    names.add(target.id)
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            if isinstance(target, ast.Name) and target.id.startswith("_"):
                names.add(target.id)
    return names


def _defined_in_class(node: ast.ClassDef) -> set[str]:
    assigned, _read = _self_attributes(node)
    return assigned | _class_level_names(node)


def _violations(source: str) -> list[tuple[str, str]]:
    """Return (class_name, attribute) pairs read but never assigned in the class."""
    tree = ast.parse(source)
    classes = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    found: list[tuple[str, str]] = []

    for name, node in classes.items():
        assigned, read = _self_attributes(node)
        assigned |= _class_level_names(node)
        # Fold in same-module base classes.  A base written as
        # ``Form if Form is not None else object`` is an ast.IfExp naming a .NET
        # type, not a class in this module; only plain names can be resolved.
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in classes:
                assigned |= _defined_in_class(classes[base.id])
        for attribute in sorted(read - assigned):
            found.append((name, attribute))

    return found


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path", _MODULE_FILES, ids=[path.name for path in _MODULE_FILES]
)
def test_read_self_attributes_are_assigned_in_the_class(module_path: Path) -> None:
    source = module_path.read_text(encoding="utf-8")
    violations = _violations(source)

    assert not violations, "\n".join(
        f"{module_path.name}: {class_name} reads self.{attribute} "
        f"but never assigns it"
        for class_name, attribute in violations
    )
