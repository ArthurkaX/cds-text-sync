# -*- coding: utf-8 -*-
"""
ide_backup.py - Binary safety backups before IDE mutation.
Must be compatible with IronPython 2.7.
"""
from __future__ import print_function
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET

_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(
    os.path.join(
        _BRIDGE_DIR,
        "..",
        "..",
        "..",
        "..",
        "products",
        "cds-text-sync",
        "src",
        "cds_text_sync",
        "engine",
    )
)
if os.path.isdir(_ENGINE_DIR) and _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from _project_settings import load_project_settings


BACKUP_PATTERN = re.compile(r"^\d{8}_\d{6}_.*\.bak$")


def _safe_basename(path):
    name = os.path.basename(str(path or "").strip())
    if not name:
        return "CODESYS.project"
    return name


def _unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    index = 1
    while True:
        candidate = "{0}_{1}{2}".format(base, index, ext)
        if not os.path.exists(candidate):
            return candidate
        index += 1


def patch_has_ide_changes(patch_path):
    try:
        root = ET.parse(patch_path).getroot()
    except Exception:
        return False

    for elem in root.iter():
        if elem.attrib.get("Name") == "MetaObject":
            return True
        tag = elem.tag
        if "}" in tag:
            tag = tag.rsplit("}", 1)[1]
        if tag == "CreateTextObject":
            return True
    return False


def _cleanup_old_backups(backup_root, retention_count):
    if retention_count < 1 or not os.path.isdir(backup_root):
        return

    backups = []
    for filename in os.listdir(backup_root):
        if not BACKUP_PATTERN.match(filename):
            continue
        path = os.path.join(backup_root, filename)
        if os.path.isfile(path):
            backups.append(path)

    if len(backups) <= retention_count:
        return

    backups.sort(reverse=True)
    for path in backups[retention_count:]:
        try:
            os.remove(path)
            print("Deleted old backup: " + path)
        except Exception as error:
            print("Warning: failed to delete old backup {0}: {1}".format(path, error))


def create_pre_import_backup(project, backup_root, retention_count):
    if project is None:
        print("Pre-import backup failed: no active project.")
        return None

    try:
        project.save()
    except Exception as error:
        print("Pre-import backup failed: could not save project: " + str(error))
        return None

    project_path = getattr(project, "path", None)
    if not project_path or not os.path.exists(project_path):
        print("Pre-import backup failed: project has no saved binary path.")
        return None

    if not os.path.isdir(backup_root):
        os.makedirs(backup_root)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = "{0}_{1}.bak".format(timestamp, _safe_basename(project_path))
    target_path = _unique_path(os.path.join(backup_root, filename))

    try:
        shutil.copy2(project_path, target_path)
    except Exception as error:
        print("Pre-import backup failed: could not copy project binary: " + str(error))
        return None

    _cleanup_old_backups(backup_root, int(retention_count or 10))
    print("Pre-import backup created: " + target_path)
    return target_path


def ensure_pre_import_backup(project, project_root, backup_root, patch_path):
    settings = load_project_settings(project_root)
    if not settings.get("pre_import_backup_enabled", True):
        return True
    if not patch_has_ide_changes(patch_path):
        print("Pre-import backup skipped: IMPORT.xml has no IDE changes.")
        return True

    retention_count = settings.get("backup_retention_count") or 10
    backup_path = create_pre_import_backup(project, backup_root, retention_count)
    return bool(backup_path)
