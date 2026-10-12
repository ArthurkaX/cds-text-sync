# -*- coding: utf-8 -*-
"""
_git_ignore.py - The objects a user's git ignore rules leave out of the sync.

In a team the lead exports the whole project, and a teammate who does not
own part of it (the alarm configuration, the task configuration, the
libraries, the devices) lists those paths in ``.git/info/exclude``, or the
team in ``.gitignore``. The engine then leaves such an object alone: export
neither writes nor removes its files, import does not apply them, and compare
and the dirty check do not report them. The files the lead committed stay
as they are.

An object is ignored when git's rules match the path of its xml file in the
view (a folder object's is ``<folder>/.cds-object.xml``, so a ``folder/``
pattern takes the folder with everything below it). ``--no-index`` matches
the rules against tracked files too: the lead commits these files, and a
tracked file is never "ignored" to plain ``git check-ignore``.

Outside a git work tree, or without git, nothing is ignored.
"""

import os
import subprocess

from ._manifest_bookkeeper import entries as manifest_entries
from ._view_paths import manifest_path, xml_view_path
from .xml_helpers import normalize_guid

_APPLICATION_TYPE = "639b491f-5557-464c-af91-1471bac9f549"
_NAMED_LIMIT = 5
# A git started from the engine, which itself runs without a console on
# Windows, would otherwise open a console window of its own.
_CREATE_NO_WINDOW = 0x08000000


def ignored_paths(view_root, relative_paths):
    """The ones of ``relative_paths`` (relative to ``view_root``, "/" form)
    that git's ignore rules match."""
    paths = sorted(set(path for path in relative_paths if path))
    if not paths or not os.path.isdir(view_root or ""):
        return set()
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            ["git", "-C", view_root, "check-ignore", "--no-index", "-z", "--stdin"],
            input="\0".join(paths).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs
        )
    except OSError:
        return set()
    # 0: some paths are ignored, 1: none is; anything else (128: not a work
    # tree) means there are no rules to apply.
    if completed.returncode not in (0, 1):
        return set()
    return set(
        part.decode("utf-8") for part in completed.stdout.split(b"\0") if part
    )


def ignored_guids(view_root, ide_model, folder_model=None, manifest=None):
    """The guids of the objects git's rules leave out.

    The path comes from the IDE when it has the object, else from the folder
    or the manifest. Raises RuntimeError when the rules cover an application,
    or an object but not everything below it: the export would then leave a
    hole in the tree, and the import would apply children without their
    parent.
    """
    path_by_guid = {}
    for guid, node in ide_model.nodes.items():
        path_by_guid[guid] = xml_view_path(ide_model, node)
    if folder_model is not None:
        for guid, node in folder_model.nodes.items():
            path_by_guid.setdefault(guid, manifest_path(node.metadata.get("view_path")))
    for entry in manifest_entries(manifest) if manifest else []:
        path_by_guid.setdefault(
            normalize_guid(entry.get("guid")),
            manifest_path(entry.get("xml_path") or entry.get("view_path")),
        )
    ignored = ignored_paths(view_root, path_by_guid.values())
    guids = set(guid for guid, path in path_by_guid.items() if path in ignored)
    _refuse_holes(ide_model, guids, path_by_guid)
    return guids


def _refuse_holes(ide_model, guids, path_by_guid):
    for guid in sorted(guids):
        node = ide_model.get_node(guid)
        if node is not None and normalize_guid(node.type) == _APPLICATION_TYPE:
            raise RuntimeError(
                "the git ignore rules cover the application {0}; nothing was "
                "done. Ignore the folders inside it instead (alarm configuration, "
                "task configuration, ...).".format(path_by_guid[guid])
            )
    kept_below = []
    for guid, node in ide_model.nodes.items():
        if guid in guids:
            continue
        if _has_ancestor_in(ide_model, node, guids):
            kept_below.append(path_by_guid[guid])
    if kept_below:
        kept_below.sort()
        more = len(kept_below) - _NAMED_LIMIT
        raise RuntimeError(
            "the git ignore rules leave out an object but not what is below it: "
            "{0}{1}; nothing was done. Ignore the whole folder (a pattern ending "
            "in /) or a pattern that also matches the nested files.".format(
                ", ".join(kept_below[:_NAMED_LIMIT]),
                " and {0} more".format(more) if more > 0 else "",
            )
        )


def _has_ancestor_in(ide_model, node, guids):
    seen = set([node.guid])
    parent = ide_model.get_node(node.parent_guid) if node.parent_guid else None
    while parent is not None and parent.guid not in seen:
        if parent.guid in guids:
            return True
        seen.add(parent.guid)
        parent = ide_model.get_node(parent.parent_guid) if parent.parent_guid else None
    return False
