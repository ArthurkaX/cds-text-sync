"""Workspace access: source root, file index, snapshot freshness, safe paths.

Port of the workspace pieces of ``fsm_search`` and
``codesys_fsm_operation``: the source-root rule, the ``.st`` file index, the
export-manifest snapshot classification, and path resolution that rejects
traversal.  No CODESYS dependency.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

SNAPSHOT_FRESH_SECONDS = 300


def source_root(workspace: Path) -> Path:
    """Prefer the exported view, but accept a project-view path directly."""
    if workspace.name.casefold() == "project-view" and workspace.is_dir():
        return workspace
    candidate = workspace / "project-view"
    return candidate if candidate.is_dir() else workspace


def iter_source_files(root: Path) -> list[Path]:
    """All ``*.st`` files under *root*, recursively, case-insensitively sorted.

    Files are ordered by their forward-slash relative path with a deterministic
    tie-breaker, so case-only siblings keep a stable order across platforms.
    """

    def key(path: Path):
        rel = path.relative_to(root).as_posix()
        return (rel.casefold(), rel)

    return sorted(
        (path for path in root.rglob("*.st") if path.is_file()),
        key=key,
    )


def relative_path(root: Path, path: Path) -> str:
    """Forward-slash relative path of *path* beneath *root*."""
    return path.relative_to(root).as_posix()


def read_source(path: Path) -> str:
    """Read an ST file as UTF-8, replacing malformed bytes."""
    return path.read_text(encoding="utf-8", errors="replace")


def fingerprint(path: Path) -> dict:
    """Size and mtime used to invalidate cached scan results."""
    stat = os.stat(path)
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def resolve_in_root(root: Path, relative: str) -> Path | None:
    """Resolve *relative* beneath *root*, or None when it escapes.

    Both sides are resolved before comparing, so ``..`` components and symlinked
    escapes are rejected exactly like ``search_workspace`` does.  Returns None
    on any exception.
    """
    try:
        root_resolved = root.resolve()
        candidate = (root_resolved / relative).resolve()
        candidate.relative_to(root_resolved)
        return candidate
    except Exception:
        return None


def _parse_export_time(created):
    """Parse the manifest stamp, which folder_writer writes in local time."""
    try:
        return time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def _plural_age(count, unit):
    return "{0} {1}{2} ago".format(count, unit, "" if count == 1 else "s")


def _describe_age(seconds):
    """Age of the export in the largest unit that still reads clearly."""
    if seconds < 90:
        return "moments ago"
    if seconds < 3600:
        return _plural_age(int(round(seconds / 60.0)), "minute")
    if seconds < 86400:
        return _plural_age(int(round(seconds / 3600.0)), "hour")
    return _plural_age(int(seconds // 86400), "day")


def snapshot(workspace: Path) -> dict:
    """Classify the exported-workspace snapshot into a JSON-safe payload.

    ``state`` is one of ``missing`` (no ``project-view``), ``unknown`` (the
    ``.dump/manifest.json`` cannot be read, is not a dict, has no ``created``,
    or the stamp does not parse), ``fresh``, or ``stale`` against
    SNAPSHOT_FRESH_SECONDS.  The manifest timestamp is written in LOCAL time,
    so it is parsed with ``time.mktime(time.strptime(created,
    "%Y-%m-%dT%H:%M:%S"))`` exactly as the original codesys_fsm_operation does.
    The live-project comparison (_project_saved_after) is deliberately NOT
    ported: it needs a CODESYS project handle that CPython does not have.
    """
    # ``source_root`` accepts a path pointing straight at ``project-view``, so
    # the same input must resolve the sync folder here too - otherwise the
    # manifest is looked for one level too deep and every such workspace
    # reports "missing".
    sync_folder = Path(workspace)
    if sync_folder.name.casefold() == "project-view" and sync_folder.is_dir():
        sync_folder = sync_folder.parent
    project_view = sync_folder / "project-view"
    manifest = sync_folder / ".dump" / "manifest.json"
    if not project_view.is_dir():
        return {
            "state": "missing",
            "created": None,
            "age_seconds": None,
            "message": "project-view is missing. Run a fresh project export.",
        }
    try:
        with open(manifest, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except Exception as error:
        return {
            "state": "unknown",
            "created": None,
            "age_seconds": None,
            "message": (
                "Could not read exported workspace metadata ({0}). "
                "Run a fresh project export."
            ).format(error),
        }
    created = payload.get("created") if isinstance(payload, dict) else None
    if not created:
        return {
            "state": "unknown",
            "created": None,
            "age_seconds": None,
            "message": "Export metadata has no snapshot timestamp. Run a fresh project export.",
        }
    exported_at = _parse_export_time(created)
    if exported_at is None:
        return {
            "state": "unknown",
            "created": created,
            "age_seconds": None,
            "message": (
                "Workspace snapshot from {0}. "
                "Re-export the project if it has changed since then."
            ).format(created),
        }
    age = max(0.0, time.time() - exported_at)
    hint = " Re-export the project if it has changed since then."
    if age < SNAPSHOT_FRESH_SECONDS:
        hint = ""
    return {
        "state": "fresh" if age < SNAPSHOT_FRESH_SECONDS else "stale",
        "created": created,
        "age_seconds": age,
        "message": "Workspace snapshot exported {0} ({1}).{2}".format(
            _describe_age(age), created, hint
        ),
    }


def bootstrap(workspace) -> dict:
    """The section 8.1 workspace payload: metadata plus the file index."""
    workspace_path = Path(workspace).expanduser().resolve()
    root = source_root(workspace_path)
    if not root.is_dir():
        raise ValueError("Workspace/project-view does not exist: " + str(root))
    files = []
    for path in iter_source_files(root):
        stat = os.stat(path)
        files.append({
            "path": relative_path(root, path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return {
        "workspace": str(workspace_path),
        "source_root": str(root),
        "snapshot": snapshot(workspace_path),
        "files": files,
    }
