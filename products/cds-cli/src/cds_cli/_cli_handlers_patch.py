# -*- coding: utf-8 -*-
"""
_cli_handlers_patch.py - ``cts patch save``.

Packages the text files a user changed on disk so a colleague working on the
same project can copy them in. It runs a real compare against the live IDE, so
the result reflects the current difference rather than a stale report, then
copies only the hand-authored text (.st, .csv, and the visualization XML the
project keeps in the view) into a folder that mirrors the project structure.

The receiving side needs no tooling beyond cds-text-sync itself: copy the
view folder from the patch over the sync folder root, then run ``cts import``.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from cds_cli._cli_handlers_vars import _resolve_sync_folder
from cds_cli._cli_io import (
    _format_output,
    _print_error,
    _print_info,
    _print_warn,
    send_command_reverse,
)

PATCH_DIRNAME = "patch"
PATCH_PREFIX = "patch_"
MANIFEST_FILENAME = "patch.json"
README_FILENAME = "README.txt"


def resolve_patch_path(relative_str: str, root_dir: str | Path) -> Path:
    """Resolve and validate that relative_str stays safely within root_dir.

    Rejects empty paths, paths without filename, absolute drive paths, UNC
    paths, rooted paths, and directory traversal outside root_dir. Resolves
    existing symlinks and junctions.
    """
    if not relative_str or not str(relative_str).strip():
        raise ValueError("Patch path cannot be empty")
    s = str(relative_str).replace("/", os.sep)
    # Reject absolute drive, UNC, or root-prefixed paths before Path normalization
    p = Path(s)
    if p.is_absolute() or p.drive or s.startswith(("\\\\", os.sep, "/")):
        raise ValueError(f"Unsafe absolute, rooted, or UNC patch path: {relative_str}")

    root_resolved = Path(root_dir).resolve()
    # Resolve against explicit root
    target = (root_resolved / p).resolve()
    if not target.is_relative_to(root_resolved) or target == root_resolved:
        raise ValueError(f"Patch path escapes allowed root: {relative_str}")
    if not target.name or target.name in (".", ".."):
        raise ValueError(f"Patch path contains no file name: {relative_str}")
    return target


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _relative_to_view(view_root, sync_root):
    """Name of the view directory inside the patch, '' for a root-view layout."""
    if os.path.normcase(os.path.normpath(view_root)) == os.path.normcase(
        os.path.normpath(sync_root)
    ):
        return ""
    return os.path.basename(os.path.normpath(view_root))


def _run_compare(timeout):
    """Ask the daemon for a fresh compare report."""
    try:
        response = send_command_reverse("sync_compare_text", {}, timeout=timeout)
    except Exception as error:
        _print_error("Compare failed: {0}".format(error))
        sys.exit(1)
    if not response.get("ok"):
        _print_error(
            "Compare failed: {0}".format(response.get("error") or "unknown error")
        )
        sys.exit(1)
    return response.get("data") or {}


def _readme_text(view_dirname, changeset, report):
    where = "{0}/".format(view_dirname) if view_dirname else "the files next to this README"
    lines = [
        "cds-text-sync patch",
        "",
        "This folder contains only the text files that changed on the sender's",
        "disk: .st and .csv projections and hand-edited visualization XML.",
        "Nothing else from the project is included, so device descriptions, task",
        "configuration and library resolution stay as they are on your machine.",
        "",
        "How to apply:",
        "  1. Close the project in CODESYS, or at least stop any running sync.",
        "  2. Copy {0} over your own sync folder root, replacing files.".format(where),
        "  3. Run:  cts compare      - the copied objects show up as modified",
        "  4. Run:  cts import       - the changes go into the IDE",
        "",
        "Files in this patch: {0}".format(len(changeset.get("files") or [])),
    ]
    deleted = changeset.get("deleted") or []
    if deleted:
        lines.extend(
            [
                "",
                "Deleted objects ({0}) are NOT part of this patch - a patch can only".format(
                    len(deleted)
                ),
                "carry files, not removals. Delete them by hand if you need to:",
            ]
        )
        lines.extend(
            "  - {0}".format(item.get("path") or item.get("name") or item.get("guid"))
            for item in deleted
        )
    resolution = report.get("library_resolution") or {}
    if resolution.get("drift"):
        lines.extend(
            [
                "",
                "Note: the sender's project-view was exported under a different",
                "library resolution than their IDE currently uses:",
            ]
        )
        lines.extend(
            "  - {0}: disk {1} -> IDE {2}".format(
                row.get("library"),
                ", ".join(row.get("disk") or []) or "(absent)",
                ", ".join(row.get("ide") or []) or "(absent)",
            )
            for row in resolution.get("drift") or []
        )
    lines.append("")
    return "\n".join(lines)


def _patch_manifest(sync_root, settings, changeset, report, files):
    manifest = {
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": "cts patch save",
        "project": os.path.basename(os.path.normpath(sync_root)),
        "sync_mode": settings.get("sync_mode"),
        "files": files,
        "deleted": changeset.get("deleted") or [],
        "skipped_non_text": changeset.get("skipped_non_text", 0),
    }
    if report.get("library_resolution"):
        manifest["library_resolution"] = report["library_resolution"]
    return manifest


def cmd_patch_save(
    out="",
    sync_folder="",
    make_zip=False,
    dry_run=False,
    bare=False,
    timeout=120,
    output_fmt="json",
):
    """Run a compare and write the changed text files as a copy-over patch."""
    from _changeset import select_changeset
    from _manifest_bookkeeper import load as load_manifest
    from _project_layout import resolve_layout
    from _project_profiles import load_profile
    from _project_settings import load_project_settings

    sync_root = _resolve_sync_folder(sync_folder, timeout=timeout)
    settings = load_project_settings(sync_root)
    layout = resolve_layout(
        sync_root,
        view_root=settings.get("view_root"),
        layout_mode=settings.get("layout"),
    )
    manifest = load_manifest(os.path.join(layout.dump_root, "manifest.json"))
    if manifest is None:
        _print_warn(
            "No .dump/manifest.json under {0}; falling back to compare-report "
            "paths only.".format(sync_root)
        )
    profile = load_profile(settings.get("profile"))

    report = _run_compare(timeout)
    changeset = select_changeset(report, manifest, settings, profile)

    view_dirname = _relative_to_view(layout.view_root, layout.sync_root)
    out_dir = out or os.path.join(
        layout.dump_root, PATCH_DIRNAME, PATCH_PREFIX + _timestamp()
    )
    out_dir = os.path.abspath(out_dir)
    target_root = os.path.join(out_dir, view_dirname) if view_dirname else out_dir

    files = []
    missing = []
    for item in changeset.get("files") or []:
        relative_path = item["path"]
        try:
            source_path = resolve_patch_path(relative_path, layout.view_root)
            resolve_patch_path(relative_path, target_root)
        except ValueError as err:
            _print_error(f"Unsafe patch path rejected: {err}")
            sys.exit(1)

        if not source_path.is_file():
            missing.append(relative_path)
            continue
        files.append(item)

    summary = {
        "output": out_dir,
        "files": len(files),
        "deleted_objects": len(changeset.get("deleted") or []),
        "skipped_non_text": changeset.get("skipped_non_text", 0),
        "dry_run": bool(dry_run),
        "paths": [item["path"] for item in files],
    }
    if missing:
        summary["missing"] = missing
        _print_warn(
            "{0} changed file(s) are listed by compare but absent on disk; "
            "skipped.".format(len(missing))
        )

    if not files:
        summary["output"] = None
        _print_info("Nothing to package: no changed .st, .csv or visualization files.")
        print(_format_output(summary, fmt=output_fmt, title="patch_save"))
        return

    if dry_run:
        print(_format_output(summary, fmt=output_fmt, title="patch_save"))
        return

    for item in files:
        relative_path = item["path"]
        try:
            source_path = resolve_patch_path(relative_path, layout.view_root)
            dest_path = resolve_patch_path(relative_path, target_root)
        except ValueError as err:
            _print_error(f"Unsafe patch path rejected: {err}")
            sys.exit(1)

        parent = dest_path.parent
        if not parent.is_dir():
            parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_path), str(dest_path))

    if not bare:
        with open(
            os.path.join(out_dir, MANIFEST_FILENAME), "w", encoding="utf-8"
        ) as handle:
            json.dump(
                _patch_manifest(sync_root, settings, changeset, report, files),
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.write("\n")
        with open(
            os.path.join(out_dir, README_FILENAME), "w", encoding="utf-8"
        ) as handle:
            handle.write(_readme_text(view_dirname, changeset, report))

    if make_zip:
        summary["zip"] = shutil.make_archive(out_dir, "zip", out_dir)

    print(_format_output(summary, fmt=output_fmt, title="patch_save"))


def dispatch_patch(args, output_fmt="json"):
    """Handle ``cts patch <action>``. Returns True when the command was ours."""
    if getattr(args, "command", None) != "patch":
        return False
    action = getattr(args, "patch_action", None) or "save"
    if action != "save":
        _print_error("Unknown patch action: {0}".format(action))
        sys.exit(1)
    cmd_patch_save(
        out=getattr(args, "out", ""),
        sync_folder=getattr(args, "sync_folder", ""),
        make_zip=getattr(args, "zip", False),
        dry_run=getattr(args, "dry_run", False),
        bare=getattr(args, "bare", False),
        timeout=getattr(args, "timeout", 120),
        output_fmt=output_fmt,
    )
    return True


__all__ = ["cmd_patch_save", "dispatch_patch"]
