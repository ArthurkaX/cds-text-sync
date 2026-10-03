# -*- coding: utf-8 -*-
"""
_dirty_scan.py - Detects locally-modified managed files before an export.

An export regenerates every managed view file from the IDE snapshot. Any file
whose on-disk content diverged from the hashes recorded in ``manifest.json``
would be silently overwritten by that regeneration; the same is true for
unmanaged projection files, which orphan removal deletes outright. This module
finds both groups so callers can confirm, skip, or overwrite deliberately.

Hashing must stay byte-identical to the read-side change detection in
``folder_reader``: both go through ``_view_text.read_view_text`` + ``sha1_hex``,
so a file is "dirty" here exactly when the reader would consider it changed.
"""

import os

from ._project_layout import is_reserved_root_child
from ._view_paths import join_view_path, managed_relative_paths, normalize_fs_path
from ._view_text import ViewEncodingError, read_view_text
from .xml_helpers import normalize_guid, sha1_hex


def _hash_file(full_path):
    """Return ``(hash, unreadable_reason)`` -- one of the two is always set.

    A file whose bytes cannot be read has no hash to compare against the
    manifest, and it must never be treated as clean: the export would then
    overwrite content we were unable to read, destroying whatever the editor
    saved. So every failure names the file unreadable, with the reason. The
    encoding case is the common one and keeps its specific wording; anything
    else (a locked or permission-denied file, a bug in the reader) is reported
    as it is rather than quietly dropping the file from the dirty list.
    """
    try:
        return sha1_hex(read_view_text(full_path)), None
    except ViewEncodingError:
        return None, "not valid UTF-8"
    except Exception as error:
        return None, "could not be read: {0}".format(error)


def _entry_xml_in_dump(entry):
    return (entry.get("xml_root") or "").lower() == "dump"


def scan_dirty(manifest, views_path, enabled_extensions=None, selected_guids=None):
    """Return ``{"dirty": [...], "orphans": [...]}`` for an export preflight.

    ``dirty``: managed view files whose current hash differs from the manifest
    (``hash`` for the entry xml, ``projection_hashes`` for projections), plus
    files that could not be read at all - those carry ``unreadable`` with the
    reason and a null ``current_hash``. A file we cannot read counts as dirty
    because the export would otherwise overwrite content we never saw. Missing
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
            full_path = join_view_path(views_path, relative_path)
            if not os.path.isfile(full_path):
                continue
            current_hash, unreadable_reason = _hash_file(full_path)
            if unreadable_reason is None and current_hash == expected_hash:
                continue
            item = {
                "guid": guid,
                "path": str(relative_path).replace("\\", "/"),
                "file_kind": file_kind,
                "expected_hash": expected_hash,
                "current_hash": None if unreadable_reason else current_hash,
            }
            if unreadable_reason:
                item["unreadable"] = unreadable_reason
            dirty.append(item)

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
