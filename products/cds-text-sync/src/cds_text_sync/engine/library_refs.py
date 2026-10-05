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

# Type GUID of a *concrete* library item - a library pinned directly by the
# project instead of named through a placeholder. It carries no
# ``DefaultResolution``: the whole ``name, version (vendor)`` string is in its
# single ``Name`` field. Read off the reference project's export.
CONCRETE_ITEM_TYPE_GUID = "51a11660-6c0d-4598-8c08-419c5845ea1f"

# Name of the dictionary that points a placeholder at the version actually
# used. ``Standard`` reaches a project only this way: the system pulls it in,
# so it has no ``Items`` entry at all.
REDIRECTION_TABLE_NAME = "PlaceholderRedirectionTable"

#: ``kind`` values carried by every reference.
KIND_PLACEHOLDER = "placeholder"
KIND_CONCRETE = "concrete"
KIND_REDIRECTED = "redirected"

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
    by file then document order within each file - plus one reference per
    ``PlaceholderRedirectionTable`` entry the items do not already carry.
    Keys: ``kind`` (one of ``placeholder``, ``concrete``, ``redirected``),
    ``placeholder``, ``name``, ``version``, ``vendor``, ``namespace``,
    ``system`` and ``container`` - the owning Library Manager's path relative
    to ``project_view`` with forward slashes. ``gap`` is ``None`` when at
    least one manager yielded entries (a partial read is not a failure), or a
    short human-readable reason. Never raises.
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
        _collect_item_references(root, container, references, seen)
        _apply_redirections(root, container, references, seen)
    if not references:
        return [], "Library Manager objects have no library entries"
    return references, None


def _collect_item_references(root, container, references, seen):
    """Append the deduplicated library references of one Library Manager."""
    for item in root.iter("Single"):
        kind = _item_kind(item)
        if not kind:
            continue
        reference = _item_reference(item, kind, container)
        if reference is None:
            continue
        key = (reference["name"].casefold(), reference["version"])
        if key in seen:
            continue
        seen.add(key)
        references.append(reference)


def _item_kind(item):
    """The reference kind of one ``Items`` element, or "" when it is neither."""
    guid = _normalise_guid(item.get("Type"))
    if guid == PLACEHOLDER_ITEM_TYPE_GUID:
        return KIND_PLACEHOLDER
    if guid == CONCRETE_ITEM_TYPE_GUID:
        return KIND_CONCRETE
    return ""


def _resolution_text(item, kind):
    """The ``name, version (vendor)`` string of one item, or None.

    A placeholder declares it in ``DefaultResolution``. A concrete item has no
    resolution field at all: the same string is its ``Name``, so a bare
    library name and a full resolution are told apart by ``parse_default_resolution``.
    """
    if kind == KIND_CONCRETE:
        return _single_text(item, "Name") or None
    return _single_text(item, "DefaultResolution") or None


def _item_reference(item, kind, container):
    """Build one reference dict from an ``Items`` element, or None if unnamed.

    ``parse_default_resolution`` supplies the name, version and vendor; a
    string without a version leaves the wildcard version and an empty vendor.
    """
    placeholder = _single_text(item, "PlaceholderName")
    name, version, vendor = parse_default_resolution(_resolution_text(item, kind))
    resolved_name = name or placeholder
    if not resolved_name:
        return None
    return {
        "kind": kind,
        "placeholder": placeholder,
        "name": resolved_name,
        "version": version,
        "vendor": vendor,
        "namespace": _single_text(item, "Namespace"),
        "system": _is_true(item.find("Single[@Name='SystemLibrary']")),
        "container": container,
    }


def _apply_redirections(root, container, references, seen):
    """Point every placeholder in the redirect table at its used version.

    A placeholder that already has an item keeps its place: the table only
    fixes the version, it does not add a second entry. A placeholder without
    one becomes a reference of its own - the system pulls it in, so the
    project does use it.
    """
    for placeholder_name, resolution in _redirections(root):
        name, version, vendor = parse_default_resolution(resolution)
        if not name:
            continue
        _apply_one_redirection(
            references, seen, placeholder_name, (name, version, vendor), container
        )


def _redirections(root):
    """Yield ``(placeholder, resolution)`` from every redirect table in *root*.

    The table is a ``Dictionary`` of ``Entry`` rows, each carrying a ``Key``
    and a ``Value`` element that wrap a single ``Single`` with the text.
    """
    for table in root.iter("Dictionary"):
        if (table.get("Name") or "").strip() != REDIRECTION_TABLE_NAME:
            continue
        for entry in table.iter("Entry"):
            key = _wrapped_text(entry, "Key")
            if key:
                yield key, _wrapped_text(entry, "Value")


def _wrapped_text(entry, name):
    """The text of ``<name><Single ...>text</Single></name>`` inside one entry."""
    holder = entry.find(name)
    if holder is None:
        return ""
    inner = holder.find("Single")
    if inner is not None:
        return (inner.text or "").strip()
    return (holder.text or "").strip()


def _apply_one_redirection(references, seen, placeholder_name, resolved, container):
    """Apply one table row, replacing a matching item or appending a new one."""
    name, version, vendor = resolved
    lowered = placeholder_name.casefold()
    for reference in references:
        if lowered in (
            str(reference.get("placeholder") or "").casefold(),
            str(reference.get("name") or "").casefold(),
        ):
            reference.update(
                {"kind": KIND_REDIRECTED, "name": name, "version": version, "vendor": vendor}
            )
            return
    _append_redirected(references, seen, placeholder_name, resolved, container)


def _append_redirected(references, seen, placeholder_name, resolved, container):
    """Add a redirect-only reference unless that name/version is already there."""
    name, version, vendor = resolved
    key = (name.casefold(), version)
    if key in seen:
        return
    seen.add(key)
    references.append(
        {
            "kind": KIND_REDIRECTED,
            "placeholder": placeholder_name,
            "name": name,
            "version": version,
            "vendor": vendor,
            "namespace": "",
            # The table carries no SystemLibrary flag; the only signal left is
            # the vendor it resolves to, which is "System" for the libraries
            # CODESYS pulls in itself.
            "system": vendor.strip().casefold() == "system",
            "container": container,
        }
    )


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