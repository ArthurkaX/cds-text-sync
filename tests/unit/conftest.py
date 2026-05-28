# -*- coding: utf-8 -*-
"""
conftest.py - Shared fixtures for the unit-test tier.

Adds ``cli/external_engine`` to ``sys.path`` so that production modules
can be imported with their flat, non-package imports.
"""

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup – keep this local to the test layer; do NOT refactor production
# imports.
# ---------------------------------------------------------------------------
_EXTERNAL_ENGINE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "cli", "external_engine")
)

if _EXTERNAL_ENGINE_DIR not in sys.path:
    sys.path.insert(0, _EXTERNAL_ENGINE_DIR)


# ---------------------------------------------------------------------------
# Reusable XML snippet fixtures (used by at least two test modules)
# ---------------------------------------------------------------------------


@pytest.fixture
def namespaced_tag():
    """Return a tag string with a namespace prefix, e.g. ``{ns}Tag``."""
    return "{http://example.com/ns}Single"


@pytest.fixture
def plain_tag():
    """Return a plain tag string without a namespace prefix."""
    return "Single"


@pytest.fixture
def sample_entry_element():
    """Return a minimal ``xml.etree.ElementTree.Element`` with two text-blob
    children (declaration + implementation) suitable for ST projection tests.
    """
    import xml.etree.ElementTree as ET

    root = ET.Element("Single", {"Name": "Object"})
    declaration = ET.SubElement(root, "Single", {"Name": "TextBlobForSerialisation"})
    declaration.text = "PROGRAM MyPrg\nVAR\n  x : INT;\nEND_VAR"
    implementation = ET.SubElement(root, "Single", {"Name": "TextBlobForSerialisation"})
    implementation.text = "x := 1;"
    return root
