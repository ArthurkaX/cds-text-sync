# -*- coding: utf-8 -*-
"""
_view_paths.py - Shared path/manifest helpers for the folder reader and writer.

These encode the on-disk manifest and entry schemas (which keys hold a view
root, which hold managed file paths). Keeping them in one place stops the reader
and writer copies from drifting apart when that schema changes.
"""

import os


def normalize_fs_path(path):
    """Case-fold + absolutize a filesystem path for reliable comparison."""
    return os.path.normcase(os.path.abspath(os.path.normpath(path or "")))


def manifest_view_root(manifest, project_root):
    """Resolve the view root recorded in a manifest, relative to ``project_root``.

    Returns ``None`` when the manifest records no view root.
    """
    value = manifest.get("view_root") or manifest.get("views_path")
    if not value:
        return None
    text = str(value)
    if text == ".":
        return project_root
    if os.path.isabs(text):
        return os.path.abspath(os.path.normpath(text))
    return os.path.abspath(os.path.normpath(os.path.join(project_root, text)))


def managed_relative_paths(entry):
    """Return every project-relative path a manifest entry owns on disk."""
    relative_paths = []
    if entry.get("xml_path") or entry.get("view_path"):
        relative_paths.append(entry.get("xml_path") or entry.get("view_path"))
    for projection_path in entry.get("projection_paths") or []:
        relative_paths.append(projection_path)
    return relative_paths
