# -*- coding: utf-8 -*-
"""Filesystem iteration helpers for pending project objects."""

import os


def iter_files(root_path, extension):
    """Yield ``(relative_path, full_path)`` for non-hidden matching files."""
    if not os.path.exists(root_path):
        return
    suffix = extension.lower()
    for current_root, dirs, files in os.walk(root_path):
        if os.path.abspath(current_root) == os.path.abspath(root_path):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
        for filename in files:
            if filename.startswith(".") or not filename.lower().endswith(suffix):
                continue
            full_path = os.path.join(current_root, filename)
            relative_path = os.path.relpath(full_path, root_path).replace(os.sep, "/")
            yield relative_path, full_path
