# -*- coding: utf-8 -*-
"""
xml_helpers.py - Shared XML helpers for the visu module.

These are generic XML-format helpers used by multiple visu modules.
They have no visualization-specific policy; they exist only to
de-duplicate common patterns (namespace stripping, named-child lookup).
"""


def strip_ns(tag):
    """Strip the XML namespace prefix from a tag like ``{urn}tag`` -> ``tag``."""
    return tag.split("}")[-1] if "}" in str(tag) else tag


def find_named(parent, tag_name, name):
    """Find the first child of *parent* with *tag_name* and ``Name=name``."""
    for child in list(parent):
        if strip_ns(child.tag) == tag_name and child.attrib.get("Name") == name:
            return child
    return None


def named_text(parent, name):
    """Return the text content of a named ``<Single Name=name>`` child, or ``""``."""
    child = find_named(parent, "Single", name)
    return (child.text or "").strip() if child is not None and child.text else ""
