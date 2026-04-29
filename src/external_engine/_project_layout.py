# -*- coding: utf-8 -*-
"""
_project_layout.py - Central path contract for sync roots and generated state.

Keep this module compatible with both Python 3 and the CODESYS IronPython 2.7
bridge. The active default writes editable views to project-view\\ while the
legacy .dump\\views layout remains available for explicit compatibility use.
"""
from __future__ import print_function
import os


DUMP_DIRNAME = ".dump"
BACKUP_DIRNAME = ".backup"
DIFF_DIRNAME = ".diff"
DEFAULT_VIEW_DIRNAME = "project-view"
LEGACY_DUMP_VIEW_DIRNAME = "views"
LAYOUT_LEGACY_DUMP_VIEWS = "legacy-dump-views"
LAYOUT_PROJECT_VIEW = "project-view"
LAYOUT_ROOT_VIEW = "root-view"


def normalize_layout_mode(value):
    normalized = (value or LAYOUT_PROJECT_VIEW).strip().lower()
    aliases = {
        "legacy": LAYOUT_LEGACY_DUMP_VIEWS,
        "dump": LAYOUT_LEGACY_DUMP_VIEWS,
        "dump-views": LAYOUT_LEGACY_DUMP_VIEWS,
        "legacy-dump": LAYOUT_LEGACY_DUMP_VIEWS,
        "legacy-dump-views": LAYOUT_LEGACY_DUMP_VIEWS,
        "project": LAYOUT_PROJECT_VIEW,
        "project-view": LAYOUT_PROJECT_VIEW,
        "root": LAYOUT_ROOT_VIEW,
        "root-view": LAYOUT_ROOT_VIEW,
    }
    mode = aliases.get(normalized)
    if not mode:
        raise ValueError("Unknown layout mode: {0}".format(value))
    return mode


class ProjectLayout(object):
    def __init__(self, sync_root, view_root, dump_root, backup_root, diff_root):
        self.sync_root = sync_root
        self.view_root = view_root
        self.dump_root = dump_root
        self.backup_root = backup_root
        self.diff_root = diff_root


def _absolute(path):
    return os.path.abspath(os.path.normpath(path))


def resolve_layout(project_root, view_root=None, layout_mode=None, use_legacy_dump_views=None):
    sync_root = _absolute(project_root)
    dump_root = os.path.join(sync_root, DUMP_DIRNAME)
    backup_root = os.path.join(sync_root, BACKUP_DIRNAME)
    diff_root = os.path.join(sync_root, DIFF_DIRNAME)
    if use_legacy_dump_views is not None and layout_mode is None:
        layout_mode = LAYOUT_LEGACY_DUMP_VIEWS if use_legacy_dump_views else LAYOUT_PROJECT_VIEW
    layout_mode = normalize_layout_mode(layout_mode)

    if view_root:
        resolved_view_root = _absolute(view_root)
    elif layout_mode == LAYOUT_LEGACY_DUMP_VIEWS:
        resolved_view_root = os.path.join(dump_root, LEGACY_DUMP_VIEW_DIRNAME)
    elif layout_mode == LAYOUT_ROOT_VIEW:
        resolved_view_root = sync_root
    else:
        resolved_view_root = os.path.join(sync_root, DEFAULT_VIEW_DIRNAME)

    return ProjectLayout(
        sync_root=sync_root,
        view_root=resolved_view_root,
        dump_root=dump_root,
        backup_root=backup_root,
        diff_root=diff_root,
    )


def is_reserved_root_child(name):
    return bool(name) and name.startswith(".")
