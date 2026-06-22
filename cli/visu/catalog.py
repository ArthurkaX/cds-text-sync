# -*- coding: utf-8 -*-
"""
catalog.py - Data-driven loader for visu element catalogs.

Each element type is described by a JSON file under ``cli/visu/catalog/``.
Adding a new element type later = adding a JSON file, no code change here.
See ``cli/visu/DESIGN.md`` for the schema.
"""

from __future__ import print_function

import json
import os

_CATALOG_DIR = os.path.join(os.path.dirname(__file__), "catalog")
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
SCREEN_TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "screen.xml.tmpl")


class CatalogError(Exception):
    pass


def catalog_dir():
    return _CATALOG_DIR


def list_types():
    """Return the sorted list of available element type names."""
    types = []
    if not os.path.isdir(_CATALOG_DIR):
        return types
    for name in os.listdir(_CATALOG_DIR):
        if name.endswith(".json"):
            types.append(name[: -len(".json")])
    return sorted(types)


def load_catalog(type_name):
    """Load and return the catalog dict for ``type_name``.

    Raises CatalogError if the type is unknown.
    """
    if not type_name:
        raise CatalogError("No element type given")
    path = os.path.join(_CATALOG_DIR, "{0}.json".format(type_name))
    if not os.path.isfile(path):
        available = ", ".join(list_types()) or "(none)"
        raise CatalogError(
            "Unknown element type '{0}'. Available: {1}".format(type_name, available)
        )
    with open(path, "r") as handle:
        data = json.load(handle)
    _validate_catalog(data, type_name)
    return data


def load_screen_template():
    """Return the screen envelope template text."""
    with open(SCREEN_TEMPLATE_PATH, "r") as handle:
        return handle.read()


def _validate_catalog(data, type_name):
    required = ["type", "visualElementTypeName", "base_members", "params"]
    for key in required:
        if key not in data:
            raise CatalogError(
                "Catalog '{0}' missing required key '{1}'".format(type_name, key)
            )


def shape_value(catalog, shape_name):
    """Resolve a friendly shape name to its VISU_ST_* value.

    Returns None if the shape is not a known variant.
    """
    variants = catalog.get("shape_variants") or {}
    return variants.get(shape_name)
