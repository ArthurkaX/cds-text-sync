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


def manifest_path(path):
    """A project-relative path in the portable manifest form ("/" separators).

    Manifests are written with "/" on every platform, so the same sync folder
    can be exported on Windows and read back on Linux (or the other way round).
    Storing ``os.path.join`` output verbatim made the separators host-specific:
    a Windows-produced manifest carried backslashes, which on Linux are ordinary
    filename characters, so every managed path failed to resolve. Applying this
    to a path read from an older manifest normalizes that too.
    """
    return str(path if path is not None else "").replace("\\", "/")


def join_view_path(root, relative_path):
    """Join a view root with a manifest-relative path of either separator."""
    return os.path.join(root, manifest_path(relative_path))


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


def flat_nested_path(project_model, node, extension):
    """The flat file name of an object nested under a collapsed one
    (``FB_Valve.M_Toggle.xml`` beside ``FB_Valve.xml``), or None for an object
    that gets a path of its own."""
    parent = project_model.collapsed_parent_for(node)
    if parent is None:
        return None

    parent_parts = parent.get_output_parts(project_model)
    if not parent_parts:
        return None

    node_path = [
        project_model.safe_component(part)
        for part in (node.display_path or [])
        if part
    ]
    tail_parts = (
        node_path[len(parent_parts) :]
        if node_path[: len(parent_parts)] == parent_parts
        else []
    )
    name = project_model.safe_component(node.output_name or node.name)
    flat_name = ".".join(parent_parts[-1:] + tail_parts + [name])
    return os.path.join(*(parent_parts[:-1] + [flat_name])) + extension


def xml_view_path(project_model, node):
    """The view-relative path of ``node``'s xml file, as the export writes it."""
    path = flat_nested_path(project_model, node, ".xml") or node.get_view_path(
        project_model, extension=".xml"
    )
    return manifest_path(path) if path else path


def managed_relative_paths(entry):
    """Return every project-relative path a manifest entry owns on disk."""
    relative_paths = []
    view_path = entry.get("xml_path") or entry.get("view_path")
    if view_path:
        relative_paths.append(manifest_path(view_path))
    for projection_path in entry.get("projection_paths") or []:
        relative_paths.append(manifest_path(projection_path))
    return relative_paths
