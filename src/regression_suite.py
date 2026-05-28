# -*- coding: utf-8 -*-
"""
regression_suite.py - Runs the local regression checks that do not require CODESYS.
"""
import os
import subprocess
import sys


ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _run(relative_path):
    script_path = os.path.join(ROOT_DIR, relative_path)
    cmd = [sys.executable, script_path]
    print("Running: {0}".format(" ".join(cmd)))
    completed = subprocess.run(cmd, cwd=ROOT_DIR)
    if completed.returncode != 0:
        return completed.returncode
    return 0


def main():
    checks = [
        os.path.join("cli", "external_engine", "offline_regression.py"),
        os.path.join("src", "ide_bridge", "ide_apply_patch_regression.py"),
        os.path.join("src", "ide_bridge", "ide_backup_regression.py"),
    ]
    for check in checks:
        code = _run(check)
        if code:
            return code
    print("regression_suite: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
