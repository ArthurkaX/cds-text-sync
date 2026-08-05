# -*- coding: utf-8 -*-
"""
ide_export_snapshot.py - Export entire project to a native IDE.xml snapshot.
Must be compatible with IronPython 2.7.
"""
from __future__ import print_function
import os
import tempfile
import time

import ide_runtime_common


RESOURCE_EXTENSIONS = set([
    ".bmp",
    ".cfg",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".json",
    ".png",
    ".sh",
    ".svg",
    ".txt",
    ".xml",
])


def _missing_external_path_from_name(name):
    if "|" not in name:
        return None
    candidate = name.split("|", 1)[1].strip()
    if not candidate:
        return None
    extension = os.path.splitext(candidate)[1].lower()
    if extension in RESOURCE_EXTENSIONS:
        return candidate
    if not (os.path.isabs(candidate) or (len(candidate) > 2 and candidate[1] == ":")):
        return None
    if os.path.exists(candidate):
        return None
    return candidate


def _exportable_snapshot_objects(project):
    objects = []
    skipped = []
    try:
        candidates = project.get_children(recursive=True)
    except Exception:
        return project.get_children(), skipped, True

    for obj in candidates:
        name = ide_runtime_common.object_name(obj)
        missing_path = _missing_external_path_from_name(name)
        if missing_path:
            skipped.append((name, missing_path))
            continue
        objects.append(obj)
    return objects, skipped, False


def _replace_file(source_path, target_path):
    if os.path.exists(target_path):
        os.remove(target_path)
    os.rename(source_path, target_path)


def _print_skipped_external_resources(skipped, log_fn=None):
    unique = []
    seen = set()
    for name, missing_path in skipped:
        key = name + "\n" + missing_path
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, missing_path))

    limit = 10
    for name, missing_path in unique[:limit]:
        message = "Skipping missing external resource during snapshot export: " + name + " -> " + missing_path
        if log_fn:
            log_fn(message)
        else:
            print(message)
    if len(unique) > limit:
        message = "Skipped {0} more missing external resources during snapshot export.".format(len(unique) - limit)
        if log_fn:
            log_fn(message)
        else:
            print(message)


def export_snapshot(system, project, output_path, log_fn=None):
    """
    Exports the entire project into a single native XML file.
    Uses a temporary target to avoid CODESYS overwrite prompts.
    """
    if log_fn:
        log_fn("Exporting snapshot to: " + output_path)
    else:
        print("Exporting snapshot to: " + output_path)
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    fd, tmp_path = tempfile.mkstemp(prefix="cds_ide_snapshot_", suffix=".xml", dir=output_dir or None)
    os.close(fd)
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    try:
        _t0 = time.time()
        objects, skipped, use_recursive = _exportable_snapshot_objects(project)
        _log = log_fn or (lambda m: None)
        _log("[export_snapshot] collected {0} objects, {1} skipped in {2:.2f}s".format(
            len(objects), len(skipped), time.time() - _t0))
        _print_skipped_external_resources(skipped, log_fn=log_fn)
        _t1 = time.time()
        if use_recursive:
            _log("[export_snapshot] calling export_native(recursive=True)...")
            project.export_native(objects, tmp_path, recursive=True)
        else:
            _log("[export_snapshot] calling export_native(recursive=False) with {0} objects...".format(len(objects)))
            project.export_native(objects, tmp_path, recursive=False)
        _log("[export_snapshot] export_native done in {0:.2f}s".format(time.time() - _t1))
        _replace_file(tmp_path, output_path)
        _log("[export_snapshot] file renamed to {0}".format(output_path))
        return True
    except Exception as e:
        if log_fn:
            log_fn("Error exporting snapshot: " + str(e))
        else:
            print("Error exporting snapshot: " + str(e))
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False


def export_selected_snapshot(project, objects, output_path, log_fn=None):
    """
    Export a caller-provided object list into a native XML snapshot.

    This is used by tools that need a narrow snapshot, e.g. textual declaration
    analysis, and must not export resources or the full project tree.
    """
    if log_fn:
        log_fn("Exporting selected snapshot to: " + output_path)
    else:
        print("Exporting selected snapshot to: " + output_path)
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    fd, tmp_path = tempfile.mkstemp(prefix="cds_ide_snapshot_", suffix=".xml", dir=output_dir or None)
    os.close(fd)
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    try:
        _log = log_fn or (lambda m: None)
        _t0 = time.time()
        _log("[export_selected_snapshot] calling export_native(recursive=False) with {0} objects...".format(len(objects or [])))
        project.export_native(list(objects or []), tmp_path, recursive=False)
        _log("[export_selected_snapshot] export_native returned in {0:.2f}s".format(time.time() - _t0))
        _replace_file(tmp_path, output_path)
        _log("[export_selected_snapshot] file renamed to {0}".format(output_path))
        return True
    except Exception as e:
        if log_fn:
            log_fn("Error exporting selected snapshot: " + str(e))
        else:
            print("Error exporting selected snapshot: " + str(e))
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False
