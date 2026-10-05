# -*- coding: utf-8 -*-
"""Content fingerprint of the workspace an export writes and an import reads.

``cts verify`` sends this digest with its build request and the daemon compares
it with the folder it can see before the compiler's verdict is credited, so the
two sides must agree on *what* is fingerprinted as well as on how. That is why
this module exists: the CLI (CPython) and the bridge (IronPython 2.7) both
import it instead of carrying a copy each. The copies had already drifted, and
a fingerprint that disagrees with itself can only ever read as ``stale_ide``.

The scope is the *view root* the engine exports to and imports from --
``project-view/`` by default -- not the sync folder around it. A CODESYS
project kept in the same folder as its own sync root rewrites ``*.~u``,
``*.project``, ``*.opt`` and ``*.precompilecache`` whenever the IDE runs and
whenever the user saves. None of that is workspace content, but hashing the
whole root made every call see a different workspace and masked the real
compiler verdict.

Inside that scope the rule is the engine's own: an entry whose first path
component is dotted (``.git``, ``.dump``, ``.backup``) is generated or
tool-owned state rather than content, in every layout the engine supports.

IronPython 2.7 compatible: no f-strings, no annotations, no pathlib.
"""

from __future__ import print_function

import hashlib
import os

from ._project_layout import is_reserved_root_child, resolve_layout
from ._project_settings import read_project_settings

#: Stream size for file contents: a large view tree must not be pulled into
#: memory at once, least of all inside the CODESYS process.
_CHUNK_SIZE = 1024 * 1024


def workspace_root(project_root):
    """The directory whose content an export writes and an import reads.

    Resolved the way the engine resolves it, from the project's own settings
    (``cds-text-sync.json``): the default ``project-view/``, an explicit
    ``view_root``, or the sync root itself in root-view mode. A root whose view
    folder does not exist yet is its own workspace, so a folder that was never
    exported fingerprints as empty rather than as unreadable.

    Settings are read with warnings off on purpose: this runs inside ``cts
    verify``, whose stdout carries the JSON report.
    """
    root = os.path.abspath(str(project_root))
    try:
        settings = read_project_settings(root, warn=False)[0]
    except Exception:
        settings = {}
    view_root = resolve_layout(
        root,
        view_root=settings.get("view_root"),
        layout_mode=settings.get("layout"),
    ).view_root
    if view_root and os.path.isdir(view_root):
        return view_root
    return root


def _scan(root):
    """``[(relative_path, absolute_path)]`` under *root*, sorted.

    Sorted so the digest never depends on directory order, and with
    forward-slash relative names so it never depends on the host that produced
    it. Symlinks and non-files are skipped. Dotted entries are skipped at the
    top of the scope only -- that is where generated state lives; a dot-named
    directory further down is the project's own business.
    """
    root = os.path.abspath(str(root))
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        reserved = os.path.abspath(dirpath) == root
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not (reserved and is_reserved_root_child(name))
        )
        for name in sorted(filenames):
            if reserved and is_reserved_root_child(name):
                continue
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            found.append((os.path.relpath(path, root).replace(os.sep, "/"), path))
    found.sort()
    return found


def workspace_files(project_root):
    """Relative paths of the files the fingerprint covers, sorted.

    The membership of the scan, on its own: what a change to this file would
    (or would not) mean for the build handshake.
    """
    return [relative for relative, _path in _scan(workspace_root(project_root))]


def workspace_fingerprint(project_root):
    """Return ``(digest, complete, errors)`` for the workspace.

    ``complete`` is False when a file could not be read. The digest is still
    returned, but a caller must not treat it as evidence: the errors name what
    was missed, and an unreadable workspace must never look like a matching
    one.
    """
    digest = hashlib.sha256()
    errors = []
    for relative, path in _scan(workspace_root(project_root)):
        try:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
            digest.update(b"\0")
        except (IOError, OSError) as exc:
            errors.append("{0}: {1}".format(relative, exc))
    return digest.hexdigest(), not errors, errors


__all__ = ["workspace_fingerprint", "workspace_files", "workspace_root"]
