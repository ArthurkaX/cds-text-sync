# -*- coding: utf-8 -*-
"""Pure manifest indexing and loading helpers for folder orchestration."""

import json


def load(path):
    """Load a manifest, returning ``None`` for a missing/invalid file."""
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError):
        return None


def entries(manifest):
    """Return manifest entries as a stable list."""
    return (manifest or {}).get("entries", []) or []


def hash_by_path(manifest):
    """Index XML and projection hashes by normalized relative path."""
    result = {}
    for entry in entries(manifest):
        xml_path = entry.get("xml_path") or entry.get("view_path")
        if xml_path and entry.get("hash"):
            result[str(xml_path).replace("\\", "/")] = entry.get("hash")
        for projection_path, value in (entry.get("projection_hashes") or {}).items():
            if value:
                result[str(projection_path).replace("\\", "/")] = value
    return result
