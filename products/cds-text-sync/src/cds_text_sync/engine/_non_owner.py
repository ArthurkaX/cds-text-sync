# -*- coding: utf-8 -*-
"""
_non_owner.py - The git ignore rules of an engineer who is not the owner.

The owner of a project exports all of it; an engineer who is not the owner
leaves the alarm configuration, the task configuration, the library managers
and the hardware outside the application to the owner. Instead of writing
those rules by hand (folder names depend on the IDE language the project was
made in), the engine writes them from the project: a marked block in the
clone's ``.git/info/exclude``, one anchored pattern per object, found by its
kind in the profile. ``_git_ignore`` then leaves those objects out.

The block is the whole state: present means "not the owner". While it is
present, every command rewrites it from the current manifest, so an object
the owner adds later (a new device) is covered without a step of its own.
"""

import io
import os

from ._git_ignore import run_git
from ._manifest_bookkeeper import entries as manifest_entries
from ._project_profiles import kind_for_type_guid
from ._view_paths import manifest_path
from .xml_helpers import normalize_guid

# The block starts with the marker; the hint after it may change between
# releases and is not part of the match.
_MARKER = "# cds-text-sync: not the project owner"
_BEGIN = _MARKER + (
    " (generated; turn it off in Project Options or with: cts config non-owner off)"
)
_END = "# cds-text-sync: end"
_OWNER_KINDS = ("alarm_config", "task_config", "library_manager")
_HARDWARE_KINDS = ("device", "device_module", "softmotion_pool")
_FOLDER_FILE = "/.cds-object.xml"
_SPECIAL = "\\[]*?"


def non_owner_report(view_root, manifest, profile, turn=None):
    """Whether this clone is not the owner, after ``turn`` ("on"/"off") is
    applied, and the paths the owner keeps. Raises like ``_set_block``."""
    if turn:
        _set_block(view_root, manifest, profile, turn == "on")
    return {
        "git_work_tree": bool(_exclude_path(view_root)),
        "non_owner": _is_on(view_root),
        "owner_paths": _owner_paths(manifest, profile) if manifest else [],
    }


def _is_on(view_root):
    """Whether the clone's exclude file holds the block."""
    path = _exclude_path(view_root)
    return bool(path) and any(
        line.startswith(_MARKER) for line in _read(path).splitlines()
    )


def _set_block(view_root, manifest, profile, on):
    """Write the block from ``manifest`` (``on``) or remove it. Raises RuntimeError outside a git work tree, or when there
    is no manifest to take the objects from."""
    path = _exclude_path(view_root)
    if not path:
        raise RuntimeError(
            "{0} is not in a git work tree; the rules live in the clone's "
            ".git/info/exclude".format(view_root)
        )
    if on and not manifest:
        raise RuntimeError(
            "no .dump/manifest.json yet: export or import once, then try again"
        )
    _write_block(path, _rules(view_root, manifest, profile) if on else None)


def refresh_non_owner(view_root, manifest, profile):
    """Rewrite the block from ``manifest`` when it is there; a no-op otherwise."""
    if manifest and _is_on(view_root):
        _write_block(_exclude_path(view_root), _rules(view_root, manifest, profile))


def _owner_paths(manifest, profile):
    """View-relative paths of the objects the owner keeps, topmost only; a
    folder's ends in "/"."""
    entries = dict(
        (normalize_guid(entry.get("guid")), entry) for entry in manifest_entries(manifest)
    )
    kinds = dict(
        (guid, kind_for_type_guid(profile, entry.get("type_guid")))
        for guid, entry in entries.items()
    )
    holds_application = set()
    for guid, kind in kinds.items():
        if kind == "application":
            holds_application.update(_ancestors(entries, guid))
            holds_application.add(guid)
    owned = set(
        guid
        for guid, kind in kinds.items()
        if kind in _OWNER_KINDS
        or (kind in _HARDWARE_KINDS and guid not in holds_application)
    )
    paths = []
    for guid in owned:
        if owned.intersection(_ancestors(entries, guid)):
            continue
        path = manifest_path(entries[guid].get("xml_path") or entries[guid].get("view_path"))
        if path.endswith(_FOLDER_FILE):
            path = path[: -len(_FOLDER_FILE) + 1]
        if path:
            paths.append(path)
    return sorted(paths)


def _ancestors(entries, guid):
    result = []
    parent = normalize_guid(entries[guid].get("parent_guid"))
    while parent in entries and parent not in result and parent != guid:
        result.append(parent)
        parent = normalize_guid(entries[parent].get("parent_guid"))
    return result


def _rules(view_root, manifest, profile):
    """One pattern per owned object, anchored at the work tree's top."""
    completed = run_git(view_root, ["rev-parse", "--show-prefix"])
    prefix = completed.stdout.decode("utf-8").strip() if completed is not None else ""
    return ["/" + _escape(prefix + path) for path in _owner_paths(manifest, profile)]


def _escape(path):
    escaped = "".join("\\" + char if char in _SPECIAL else char for char in path)
    if escaped.endswith(" "):
        escaped = escaped[:-1] + "\\ "
    return escaped


def _exclude_path(view_root):
    if not os.path.isdir(view_root or ""):
        return None
    completed = run_git(view_root, ["rev-parse", "--git-path", "info/exclude"])
    if completed is None or completed.returncode != 0:
        return None
    path = completed.stdout.decode("utf-8").strip()
    return path if os.path.isabs(path) else os.path.join(view_root, path)


def _read(path):
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (IOError, OSError):
        return ""


def _write_block(path, rules):
    """Replace the block in the exclude file with ``rules`` (None: drop it);
    the lines outside the block are kept as they are."""
    kept = []
    inside = False
    for line in _read(path).splitlines():
        if line.startswith(_MARKER):
            inside = True
        elif inside and line == _END:
            inside = False
        elif not inside:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    if rules is not None:
        kept += ([""] if kept else []) + [_BEGIN] + rules + [_END]
    text = "\n".join(kept) + "\n" if kept else ""
    if text == _read(path):
        return
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
