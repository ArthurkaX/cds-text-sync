# -*- coding: utf-8 -*-
"""
codesys_discover_operation.pyw - Diagnose CODESYS object tree and profile coverage.

Forward-mode entry point. The report itself is built by the shared
discover_report.build_discovery_report (reused by the reverse-pipe daemon's
_cmd_discover); this module wraps it with base-dir resolution, the .dump/
tree+report file output, and CODESYS UI messages.
"""
from __future__ import print_function
import codecs
import json
import os

from codesys_runtime import resolve_runtime
from codesys_utils import (
    init_logging,
    load_base_dir,
    resolve_projects,
    safe_str,
)

from discover_report import build_discovery_report


def _dump_root(base_dir):
    path = os.path.join(base_dir, ".dump")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _write_text(path, lines):
    with codecs.open(path, "w", "utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _write_json(path, data):
    with codecs.open(path, "w", "utf-8") as handle:
        handle.write(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")


def _system_version(runtime):
    system = runtime.system
    if system is None:
        return ""
    for attr in ("version", "Version", "build_version", "BuildVersion"):
        try:
            value = getattr(system, attr)
            if value:
                return safe_str(value)
        except Exception:
            pass
    return ""


def _format_tree_lines(report, base_dir):
    """Render the human-readable tree log from a discovery report dict."""
    lines = []
    lines.append("=== CODESYS Project Discovery ===")
    lines.append("Project: " + report["project_name"])
    lines.append("CODESYS version: " + (report["codesys_version"] or "unknown"))
    lines.append("Sync root: " + base_dir)
    lines.append("Profile: " + report["profile"])
    lines.append("Objects: " + str(report["object_count"]))
    lines.append("Unknown type GUIDs: " + str(report["unknown_type_count"]))
    enabled = report.get("enabled_projections") or []
    if enabled:
        lines.append("Enabled projections: " + ", ".join(enabled))
    lines.append("")
    for obj in report["objects"]:
        prefix = "[!] " if obj["unknown"] else ""
        parts = [obj["kind"], obj["type_guid"]]
        if obj["sync_profile"]:
            parts.append(obj["sync_profile"])
        parts.append(obj["class"])
        lines.append(
            "  " * obj["level"]
            + "|-- "
            + prefix
            + obj["name"]
            + " ("
            + " | ".join(parts)
            + ")"
        )
    unknown_types = report.get("unknown_types") or {}
    if unknown_types:
        lines.append("")
        lines.append("!!! UNKNOWN OBJECT TYPES FOUND !!!")
        for type_guid, example in sorted(unknown_types.items()):
            lines.append(" - {0} (Example: {1})".format(type_guid, example))
        lines.append("")
        lines.append("Suggested profile JSON is included in discover_report.json.")
    return lines


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}
    init_logging(base_dir)

    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    project = projects_obj.primary
    report = build_discovery_report(project, base_dir, _system_version(runtime))
    if report.get("status") != "success":
        message = safe_str(report.get("error"))
        runtime.ui.error("Could not enumerate project objects: " + message)
        return {"status": "error", "error": report.get("error")}

    lines = _format_tree_lines(report, base_dir)

    dump_dir = _dump_root(base_dir)
    tree_path = os.path.join(dump_dir, "discover_tree.log")
    report_path = os.path.join(dump_dir, "discover_report.json")
    try:
        _write_text(tree_path, lines)
        _write_json(report_path, report)
    except Exception as error:
        runtime.ui.error("Error saving discovery diagnostics: " + safe_str(error))
        return {"status": "error", "error": safe_str(error)}

    print("\n".join(lines))
    runtime.ui.info(
        "Discovery complete.\nObjects: {0}\nUnknown types: {1}\nTree: {2}\nReport: {3}".format(
            report["object_count"],
            report["unknown_type_count"],
            tree_path,
            report_path,
        )
    )
    return {"status": "success", "report": report_path, "tree": tree_path}
