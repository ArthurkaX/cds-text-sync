# -*- coding: utf-8 -*-
"""
library_refs.py - Explicit library references declared by a project's Library Managers.

A CODESYS project exports every Library Manager object as one XML file under
the project-view tree (``project-view/.../Library Manager.xml``): a
project-level one under the POUs view (visualization libraries) and one per
application under the device tree, plus one per additional PLC device. Each
``Items`` entry is a library placeholder: the ``DefaultResolution`` string
carries the declared default as ``name, version (vendor)``,
``PlaceholderName`` and ``Namespace`` name it, and ``SystemLibrary`` flags
framework libraries.

This module reads all of those declarations straight from the export, merged
across every Library Manager found. They are matched by type GUID, not by
file name, and nothing here raises on a malformed, unreadable or absent
export - the caller gets whatever entries were read plus a short gap string.
"""

from __future__ import annotations

import os
import pathlib
import re
import xml.etree.ElementTree as ET

# Type GUID of the Library Manager object itself. Must match
# ``guid_aliases.library_manager`` in ``profiles/default.json``.
LIBRARY_MANAGER_TYPE_GUID = "adb5cb65-8e1d-4a00-b70a-375ea27582f3"

# Type GUID of one per-library item element inside the Library Manager.
PLACEHOLDER_ITEM_TYPE_GUID = "4723ebe7-5bfc-43c6-be6b-5097002ef6b4"

# ``name, version (vendor)`` - the full DefaultResolution form. The version is
# ``*`` or a dotted number; the vendor may contain spaces, hyphens and dots.
_DEFAULT_RESOLUTION_RE = re.compile(
    r"""^\s*([^,]+?),\s*(\*|[0-9][0-9.]*)\s*\(([^()]*?)\)\s*$"""
)


def parse_default_resolution(value):
    """Split a ``DefaultResolution`` string into ``(name, version, vendor)``.

    The full form is ``name, version (vendor)``; a bare name such as
    ``CmpDynamicText`` has no version and no vendor and comes back with the
    placeholder version ``*`` and an empty vendor. Never raises: ``None`` or
    an empty string yields ``("", "*", "")``.
    """
    if value is None:
        return "", "*", ""
    text = str(value).strip()
    match = _DEFAULT_RESOLUTION_RE.match(text)
    if match is None:
        return text, "*", ""
    return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()


def find_library_managers(project_view):
    """Locate every Library Manager object XML under ``project_view``.

    Walks the tree recursively for ``*.xml`` files and matches by type GUID,
    not by file name. A project legitimately carries several Library Manager
    objects - a project-level one for the visualization libraries and one per
    application (per PLC device) - and all of them hold real references, so
    all are returned. The paths are sorted by their string form
    (case-insensitive) so the result is deterministic across runs and
    filesystems. Unreadable or unparseable files are skipped. Returns an
    empty list when no Library Manager object is found.
    """
    if project_view is None:
        return []
    found = []
    for dirpath, _dirnames, filenames in os.walk(os.fspath(project_view)):
        for filename in filenames:
            if not filename.lower().endswith(".xml"):
                continue
            path = pathlib.Path(dirpath) / filename
            try:
                root = ET.parse(os.fspath(path)).getroot()
            except (ET.ParseError, OSError):
                continue
            if _is_library_manager_root(root):
                found.append(path)
    return sorted(found, key=lambda p: str(p).lower())


def explicit_library_references(project_view):
    """Return ``(references, gap)`` across every Library Manager under ``project_view``.

    ``references`` holds one dict per library entry, deduplicated on
    ``(name.casefold(), version)`` with the first occurrence winning, ordered
    by file then document order within each file. Keys: ``placeholder``,
    ``name``, ``version``, ``vendor``, ``namespace``, ``system`` and
    ``container`` - the owning Library Manager's path relative to
    ``project_view`` with forward slashes. ``gap`` is ``None`` when at least
    one manager yielded entries (a partial read is not a failure), or a short
    human-readable reason. Never raises.
    """
    roots = []
    for path in find_library_managers(project_view):
        try:
            roots.append((path, ET.parse(os.fspath(path)).getroot()))
        except (ET.ParseError, OSError):
            continue
    if not roots:
        return [], "no Library Manager object found under {0}".format(project_view)

    project_root = _project_root(os.fspath(project_view))
    references = []
    seen = set()
    for path, root in roots:
        container = pathlib.Path(os.path.relpath(os.fspath(path), project_root)).as_posix()
        for item in root.iter("Single"):
            if _normalise_guid(item.get("Type")) != PLACEHOLDER_ITEM_TYPE_GUID:
                continue
            placeholder = _single_text(item, "PlaceholderName")
            resolution = item.find("Single[@Name='DefaultResolution']")
            if resolution is None:
                name, version, vendor = placeholder, "*", ""
            else:
                name, version, vendor = parse_default_resolution(resolution.text)
            if not name:
                continue
            key = (name.casefold(), version)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "placeholder": placeholder,
                    "name": name,
                    "version": version,
                    "vendor": vendor,
                    "namespace": _single_text(item, "Namespace"),
                    "system": _is_true(item.find("Single[@Name='SystemLibrary']")),
                    "container": container,
                }
            )
    if not references:
        return [], "Library Manager objects have no library entries"
    return references, None


def _project_root(project_view):
    """Return ``project_view`` as an absolute path, for relative containers.

    A relative ``project_view`` argument is anchored at the current working
    directory, matching how ``os.walk`` explored it.
    """
    return os.path.abspath(project_view)


def _is_library_manager_root(root):
    """True when a parsed root is the Library Manager sync-node.

    The GUID appears both bare (``TypeGuid`` text) and brace-wrapped (the
    ``Object`` element's ``Type`` attribute), so both are checked after
    normalisation.
    """
    meta = root.find(".//Single[@Name='MetaObject']")
    if meta is not None:
        type_guid = meta.find("Single[@Name='TypeGuid']")
        if type_guid is not None:
            if _normalise_guid(type_guid.text) == LIBRARY_MANAGER_TYPE_GUID:
                return True
    obj = root.find(".//Single[@Name='Object']")
    if obj is not None:
        if _normalise_guid(obj.get("Type")) == LIBRARY_MANAGER_TYPE_GUID:
            return True
    return False


def _normalise_guid(value):
    """Lower-case a GUID and strip surrounding whitespace and braces."""
    return str(value or "").strip().strip("{}").strip().lower()


def _single_text(parent, name):
    """Return the stripped text of a direct ``<Single Name=...>`` child, or ""."""
    if parent is None:
        return ""
    element = parent.find("Single[@Name='{0}']".format(name))
    if element is None:
        return ""
    return (element.text or "").strip()


def _is_true(element):
    """True when a ``<Single>`` element's text case-insensitively equals "true"."""
    if element is None:
        return False
    return (element.text or "").strip().lower() == "true"


__all__ = [
    "LIBRARY_MANAGER_TYPE_GUID",
    "PLACEHOLDER_ITEM_TYPE_GUID",
    "parse_default_resolution",
    "find_library_managers",
    "explicit_library_references",
]