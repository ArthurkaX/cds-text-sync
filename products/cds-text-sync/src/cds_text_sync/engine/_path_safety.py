# -*- coding: utf-8 -*-
"""Shared safety checks for paths managed by the folder engine."""

import os

from _view_paths import normalize_fs_path


def safe_path_in_root(relative_path, root_path, is_reserved=None, reject_hidden=False):
    """Resolve a relative path under ``root_path`` or return ``None``.

    ``is_reserved`` and ``reject_hidden`` keep the reader/writer-specific
    policy at the call site while sharing the traversal protection.
    """
    if not relative_path:
        return None
    parts = relative_path.replace("\\", os.sep).split(os.sep)
    first = parts[0] if parts else ""
    if reject_hidden and first.startswith("."):
        return None
    if is_reserved is not None and is_reserved(first):
        return None
    full_path = os.path.abspath(os.path.normpath(os.path.join(root_path, relative_path)))
    normalized_root = normalize_fs_path(root_path)
    normalized_full = normalize_fs_path(full_path)
    if normalized_full == normalized_root:
        return None
    if not normalized_full.startswith(normalized_root + os.sep):
        return None
    return full_path


def replace_extension(relative_path, extension):
    """Replace a path's final extension while preserving its directories."""
    base, _old_extension = os.path.splitext(relative_path)
    return base + extension
