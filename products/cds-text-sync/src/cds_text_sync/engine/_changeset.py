# -*- coding: utf-8 -*-
"""
_changeset.py - Which authored text files a compare result would hand over.

``cts patch save`` packages the files a user edited on disk so a colleague with
the same project can copy them in. "Files a user edited" is a narrower set than
"files the project view owns": it is the hand-authored text, i.e. the ``.st`` and
``.csv`` projections plus the visualization XML that stays in the view by
``xml_in_view_kinds``.

Everything else the view carries is IDE-generated serialization that encodes the
sending machine's state - device descriptions, task configuration, the library
manager - and must not travel between two machines. Shipping it would recreate
the library re-resolution drift that makes dozens of untouched visu objects look
modified.

Pure selection logic: no filesystem access, no daemon. The caller supplies the
compare report, the manifest, the project settings and the profile.
"""

import os

from _project_profiles import kind_for_type_guid
from _view_paths import managed_relative_paths

#: Projection formats a human edits directly. Projections are always
#: view-rooted (``folder_writer._write_projection_files``), so no extra
#: location check is needed for these.
PROJECTION_EXTENSIONS = (".st", ".csv")

#: Report buckets that describe something present on disk. ``deleted`` means
#: "in the IDE, missing on disk" - there is no file to hand over.
SHIPPABLE_STATUSES = ("modified", "added")


def _guid_key(value):
    return str(value or "").strip().strip("{}").lower()


def _path_key(value):
    return str(value or "").replace("\\", "/").strip("/").lower()


def _entries_by_guid(manifest):
    result = {}
    for entry in (manifest or {}).get("entries") or []:
        key = _guid_key(entry.get("guid"))
        if key:
            result[key] = entry
    return result


def authored_paths_for_entry(entry, xml_in_view_kinds, kind):
    """Split the paths an entry owns into (authored, skipped).

    ``kind`` is the entry's profile kind (``visu``, ``pou``, ...) as returned by
    ``_project_profiles.kind_for_type_guid``; ``xml_in_view_kinds`` is the
    project setting of the same name. XML counts as authored only for a kind
    that keeps its XML in the view and whose XML is not in the ``.dump/xml``
    mirror.
    """
    kinds = [str(item).strip().lower() for item in (xml_in_view_kinds or [])]
    xml_in_dump = str(entry.get("xml_root") or "").strip().lower() == "dump"
    xml_authored = bool(kind) and str(kind).lower() in kinds and not xml_in_dump

    authored = []
    skipped = []
    for relative_path in managed_relative_paths(entry):
        if not relative_path:
            continue
        extension = os.path.splitext(str(relative_path))[1].lower()
        if extension in PROJECTION_EXTENSIONS:
            authored.append(relative_path)
        elif extension == ".xml" and xml_authored:
            authored.append(relative_path)
        else:
            skipped.append(relative_path)
    return authored, skipped


def _entry_from_report(info):
    """Build a manifest-shaped entry for an object the manifest does not know.

    Freshly added objects have no manifest entry until the next export, but the
    compare report already carries everything needed: the view path of the XML
    and the projection the diff was taken on.
    """
    projection_diff = info.get("projection_diff") or {}
    projection_paths = []
    if projection_diff.get("path"):
        projection_paths.append(projection_diff.get("path"))
    return {
        "view_path": info.get("view_path") or "",
        "projection_paths": projection_paths,
    }


def select_changeset(report, manifest=None, settings=None, profile=None):
    """Return the authored files a compare report says have changed on disk.

    ``{"files": [{path, guid, name, kind, status}], "deleted": [...],
      "skipped_non_text": N}``

    Files are project-view-relative and deduplicated: two objects that project
    into the same file yield one row.
    """
    xml_in_view_kinds = (settings or {}).get("xml_in_view_kinds") or []
    entries_by_guid = _entries_by_guid(manifest)
    objects = (report or {}).get("objects") or {}

    files = []
    seen = set()
    skipped_non_text = 0

    for status in SHIPPABLE_STATUSES:
        for info in objects.get(status) or []:
            entry = entries_by_guid.get(_guid_key(info.get("guid")))
            type_guid = (entry or {}).get("type_guid") or info.get("type_guid")
            kind = kind_for_type_guid(profile, type_guid)
            authored, skipped = authored_paths_for_entry(
                entry if entry is not None else _entry_from_report(info),
                xml_in_view_kinds,
                kind,
            )
            skipped_non_text += len(skipped)
            for relative_path in authored:
                key = _path_key(relative_path)
                if not key or key in seen:
                    continue
                seen.add(key)
                files.append(
                    {
                        "path": str(relative_path).replace("\\", "/"),
                        "guid": info.get("guid") or "",
                        "name": info.get("name") or "",
                        "kind": kind or "",
                        "status": status,
                    }
                )

    deleted = [
        {
            "guid": info.get("guid") or "",
            "name": info.get("name") or "",
            "path": info.get("path") or info.get("view_path") or "",
        }
        for info in objects.get("deleted") or []
    ]

    return {
        "files": files,
        "deleted": deleted,
        "skipped_non_text": skipped_non_text,
    }
