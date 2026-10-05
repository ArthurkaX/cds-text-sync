# -*- coding: utf-8 -*-
"""ide_tree_cache.py -- the edit marker that keeps the Snapshooter tree fresh.

The Snapshooter variable tree is built from the IDE project and cached under
``<sync-folder>/.dump/snapshots/variable_tree.json``. File mtimes cannot
invalidate it: ``cts import`` without ``--save`` changes the project only in
memory, so nothing the Snapshooter can stat moves. The live symptom was a
``tree`` of the eight objects just imported still reporting count 0.

So every daemon command that edits the project touches
``<sync-folder>/.dump/project_edited``; the tree cache is treated as stale when
that marker is newer than the cache. A plain ``cts export`` or an offline
``cts new`` does not touch it, so neither forces a needless rebuild (the tree
takes ~70 s on a project of tens of thousands of leaves).

IronPython 2.7: no f-strings, no annotations, no pathlib.
"""

from __future__ import print_function

import os
import time

MARKER_NAME = "project_edited"


def marker_path(sync_folder):
    """``<sync-folder>/.dump/project_edited``, or "" without a sync folder."""
    if not sync_folder:
        return ""
    return os.path.join(str(sync_folder), ".dump", MARKER_NAME)


def mark_project_edited(sync_folder):
    """Record that the IDE project was just edited. Best-effort.

    Returns True when the marker was written. A failure never fails the edit
    that triggered it -- the worst case is a stale tree the user clears with
    ``--refresh``.
    """
    path = marker_path(sync_folder)
    if not path:
        return False
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, "wb") as handle:
            handle.write(str(time.time()).encode("ascii"))
        return True
    except Exception:
        return False


def marker_mtime(sync_folder):
    """mtime of the edit marker, or 0.0 when there is none."""
    path = marker_path(sync_folder)
    if not path:
        return 0.0
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


__all__ = ["MARKER_NAME", "marker_path", "mark_project_edited", "marker_mtime"]
