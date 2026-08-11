# -*- coding: utf-8 -*-
"""Daemon-owned timeout profile derived once from the exported ST blocks.

The CLI must choose a pipe timeout before submitting a command, while the
CODESYS daemon is the only side that has a stable view of the active project.
Calculate the project size once at daemon startup and publish per-operation
limits through ``status``/``ping``.
"""

from __future__ import print_function

import math
import os


# method -> (fixed startup seconds, seconds per ST block, minimum seconds)
_TIMEOUT_RULES = {
    # Online/session lifecycle is not proportional to project size, but it
    # must never fall through to the 30 s generic timeout: a CODESYS login may
    # wait for an IDE dialog or gateway response.
    "connect_to_device": (60, 0.0, 60),
    "disconnect_from_device": (15, 0.0, 15),
    "start_plc": (25, 0.0, 25),
    "stop_plc": (25, 0.0, 25),
    "application_state": (10, 0.0, 10),
    "read_variable": (25, 0.0, 25),
    "write_variable": (25, 0.0, 25),
    "read_log": (10, 0.0, 10),
    "project_info": (10, 0.0, 10),
    "permissions": (5, 0.0, 5),
    "build": (60, 0.55, 120),
    "sync_export_text": (30, 0.35, 60),
    "sync_compare_text": (20, 0.45, 60),
    "sync_import_text": (90, 0.80, 180),
    "download": (90, 0.55, 120),
    "plc_crc": (30, 0.25, 60),
    "cicd": (60, 0.55, 120),
    "project_tree": (10, 0.03, 30),
    "read_object": (5, 0.02, 20),
    "update_pou": (15, 0.10, 45),
    "delete_pou": (10, 0.05, 30),
}

_DEFAULT_TIMEOUT = 30


def count_st_blocks(sync_folder):
    """Count project-view ST files once. Return None if it is unavailable."""
    if not sync_folder:
        return None
    project_view = os.path.join(sync_folder, "project-view")
    if not os.path.isdir(project_view):
        return None
    try:
        return sum(
            1
            for root, _dirs, files in os.walk(project_view)
            for name in files
            if name.lower().endswith(".st")
        )
    except Exception:
        return None


def make_timeout_profile(block_count):
    """Return JSON-safe limits for every CLI daemon operation."""
    unknown_size = block_count is None
    count = int(block_count or 0)
    timeouts = {}
    for method, (startup, per_block, minimum) in _TIMEOUT_RULES.items():
        if unknown_size:
            # Never under-estimate when a sync folder has not yet been exported.
            value = max(minimum, 600)
        else:
            value = max(minimum, int(math.ceil(startup + count * per_block)))
        timeouts[method] = value
    return {
        "block_count": block_count,
        "source": "project-view/*.st" if not unknown_size else "unavailable",
        "timeouts": timeouts,
        "default": _DEFAULT_TIMEOUT if not unknown_size else 600,
    }
