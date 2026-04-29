# -*- coding: utf-8 -*-
"""
ide_backup_regression.py - Fast checks for pre-import binary backup behavior.
"""
import os
import shutil
import tempfile

from ide_backup import create_pre_import_backup, patch_has_ide_changes


class RegressionFailure(Exception):
    pass


class FakeProject(object):
    def __init__(self, path):
        self.path = path
        self.saved = 0

    def save(self):
        self.saved += 1


def _write(path, text):
    with open(path, "w") as handle:
        handle.write(text)


def _assert(condition, message):
    if not condition:
        raise RegressionFailure(message)


def main():
    work_dir = tempfile.mkdtemp(prefix="ide-backup-regression-")
    try:
        project_path = os.path.join(work_dir, "Sample.project")
        backup_root = os.path.join(work_dir, ".backup")
        _write(project_path, "binary")

        project = FakeProject(project_path)
        backup_path = create_pre_import_backup(project, backup_root, 1)
        _assert(backup_path and os.path.exists(backup_path), "backup file was not created")
        _assert(project.saved == 1, "project was not saved before backup")
        _assert(os.path.basename(backup_path).endswith("_Sample.project.bak"), "backup name was unexpected")

        _write(os.path.join(backup_root, "20000101_000000_old.project.bak"), "old")
        second_path = create_pre_import_backup(project, backup_root, 1)
        _assert(second_path and os.path.exists(second_path), "second backup file was not created")
        backups = [name for name in os.listdir(backup_root) if name.endswith(".bak")]
        _assert(len(backups) == 1, "retention did not keep exactly one timestamped backup")

        empty_patch = os.path.join(work_dir, "empty.xml")
        changed_patch = os.path.join(work_dir, "changed.xml")
        _write(empty_patch, "<Project />")
        _write(changed_patch, '<Project><CreateTextObjects><CreateTextObject Name="X" /></CreateTextObjects></Project>')
        _assert(not patch_has_ide_changes(empty_patch), "empty patch was reported as changed")
        _assert(patch_has_ide_changes(changed_patch), "changed patch was not detected")
    finally:
        shutil.rmtree(work_dir)

    print("ide_backup_regression: PASS")


if __name__ == "__main__":
    main()
