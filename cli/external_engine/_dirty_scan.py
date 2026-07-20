# -*- coding: utf-8 -*-
"""
_dirty_scan.py - Detects locally-modified managed files before an export.

An export regenerates every managed view file from the IDE snapshot. Any file
whose on-disk content diverged from the hashes recorded in ``manifest.json``
would be silently overwritten by that regeneration; the same is true for
unmanaged projection files, which orphan removal deletes outright. This module
finds both groups so callers can confirm, skip, or overwrite deliberately.

Hashing must stay byte-identical to the read-side change detection in
``folder_reader`` (``codecs.open(..., "utf-8")`` + ``sha1_hex``): a file is
"dirty" here exactly when the reader would consider it changed.
"""

import codecs
import os

from _project_layout import is_reserved_root_child
from _view_paths import managed_relative_paths, normalize_fs_path
from xml_helpers import normalize_guid, sha1_hex


def _hash_file(full_path):
    try:
        with codecs.open(full_path, "r", "utf-8") as f:
            return sha1_hex(f.read())
    except Exception:
        return None


def _entry_xml_in_dump(entry):
    return (entry.get("xml_root") or "").lower() == "dump"


def scan_dirty(manifest, views_path, enabled_extensions=None, selected_guids=None):
    """Return ``{"dirty": [...], "orphans": [...]}`` for an export preflight.

    ``dirty``: managed view files whose current hash differs from the manifest
    (``hash`` for the entry xml, ``projection_hashes`` for projections). Missing
    files are not dirty - the writer simply recreates them.

    ``orphans``: files with a projection extension inside the view root that no
    manifest entry owns; a full export's orphan removal would delete them.
    Pass ``enabled_extensions=None`` (or empty) to skip orphan detection - e.g.
    in text-first mode, where unmanaged ``.st`` files are preserved.
    """
    dirty = []
    orphans = []
    if not manifest:
        return {"dirty": dirty, "orphans": orphans}

    selected = None
    if selected_guids:
        selected = set(
            normalize_guid(guid) for guid in selected_guids if normalize_guid(guid)
        )

    managed = set()
    for entry in manifest.get("entries", []) or []:
        for relative_path in managed_relative_paths(entry):
            managed.add(str(relative_path).replace("\\", "/"))

        guid = normalize_guid(entry.get("guid"))
        if selected is not None and guid not in selected:
            continue

        expected_hashes = {}
        xml_path = entry.get("xml_path") or entry.get("view_path")
        if xml_path and entry.get("hash") and not _entry_xml_in_dump(entry):
            expected_hashes[xml_path] = ("xml", entry.get("hash"))
        projection_hashes = entry.get("projection_hashes") or {}
        for projection_path in entry.get("projection_paths") or []:
            expected_hash = projection_hashes.get(projection_path)
            if expected_hash:
                extension = os.path.splitext(str(projection_path))[1].lower()
                file_kind = extension.lstrip(".") or "projection"
                expected_hashes[projection_path] = (file_kind, expected_hash)

        for relative_path, (file_kind, expected_hash) in expected_hashes.items():
            full_path = os.path.join(views_path, relative_path)
            if not os.path.isfile(full_path):
                continue
            current_hash = _hash_file(full_path)
            if current_hash is not None and current_hash != expected_hash:
                dirty.append(
                    {
                        "guid": guid,
                        "path": str(relative_path).replace("\\", "/"),
                        "file_kind": file_kind,
                        "expected_hash": expected_hash,
                        "current_hash": current_hash,
                    }
                )

    if enabled_extensions and os.path.isdir(views_path):
        view_root = normalize_fs_path(views_path)
        for root, dirs, files in os.walk(views_path):
            if normalize_fs_path(root) == view_root:
                dirs[:] = [name for name in dirs if not is_reserved_root_child(name)]
            for filename in files:
                extension = os.path.splitext(filename)[1].lower()
                if extension not in enabled_extensions:
                    continue
                full_path = os.path.join(root, filename)
                relative_path = os.path.relpath(full_path, views_path).replace(
                    os.sep, "/"
                )
                if relative_path not in managed:
                    orphans.append({"path": relative_path})

    dirty.sort(key=lambda item: item["path"])
    orphans.sort(key=lambda item: item["path"])
    return {"dirty": dirty, "orphans": orphans}


def dirty_view_paths(manifest, views_path, selected_guids=None):
    """View-relative paths of dirty managed files (no orphan scan)."""
    report = scan_dirty(
        manifest, views_path, enabled_extensions=None, selected_guids=selected_guids
    )
    return set(item["path"] for item in report["dirty"])
