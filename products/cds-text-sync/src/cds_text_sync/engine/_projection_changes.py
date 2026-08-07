# -*- coding: utf-8 -*-
"""Detect locally changed projection files."""

import codecs
import os

from xml_helpers import sha1_hex


def detect(paths, root_path, expected_hashes=None, missing_hash_is_change=False):
    """Return ``(changed, current_hashes, current_contents)`` for projections."""
    changed = []
    current_hashes = {}
    current_contents = {}
    expected_hashes = expected_hashes or {}
    for relative_path in paths or []:
        full_path = os.path.join(root_path, relative_path)
        if not os.path.exists(full_path):
            continue
        with codecs.open(full_path, "r", "utf-8") as handle:
            content = handle.read()
        current_hash = sha1_hex(content)
        current_hashes[relative_path] = current_hash
        current_contents[relative_path] = content
        expected_hash = expected_hashes.get(relative_path)
        if expected_hash and expected_hash != current_hash:
            changed.append(relative_path)
        elif not expected_hash and missing_hash_is_change:
            changed.append(relative_path)
    return changed, current_hashes, current_contents
