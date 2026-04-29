# -*- coding: utf-8 -*-
"""
ide_resources.pyw - Export a safe snapshot and run resource diagnostics.
Must be compatible with IronPython 2.7.
"""
from __future__ import print_function
import os

import ide_runtime_common
import ide_export_snapshot


def analyze_resources(system, project, project_root, view_root=None, layout_mode=None, limit=None):
    project_layout = ide_runtime_common.layout(project_root, view_root=view_root, layout_mode=layout_mode)
    dump_root = project_layout.dump_root
    _, log_path = ide_runtime_common.project_logging_config(project_root, dump_root)
    detailed_log = ide_runtime_common.make_detailed_logger(log_path)
    if not os.path.exists(dump_root):
        os.makedirs(dump_root)

    snapshot_path = os.path.join(dump_root, "IDE.resources.xml")
    report_path = os.path.join(dump_root, "resources_report.json")
    log_path = os.path.join(dump_root, "resources_top.log")

    if not ide_export_snapshot.export_snapshot(system, project, snapshot_path, log_fn=detailed_log):
        ide_runtime_common.log_error("Failed to export native IDE snapshot.")
        return False

    args = [
        "resources",
        "--project-root", project_root,
        "--snapshot", snapshot_path,
        "--report", report_path,
        "--log", log_path,
    ]
    if limit is not None:
        args.extend(["--limit", str(limit)])

    if not ide_runtime_common.run_external_engine(args, project_root=project_root, dump_root=dump_root):
        ide_runtime_common.log_error("External resources analysis failed.")
        return False

    ide_runtime_common.log_info("Resources analysis completed successfully.")
    return True
