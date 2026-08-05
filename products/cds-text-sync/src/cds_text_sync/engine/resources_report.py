# -*- coding: utf-8 -*-
"""
resources_report.py - Snapshot-based project resource diagnostics.
"""
from __future__ import print_function
import json

from _project_profiles import kind_for_type_guid, load_profile
from _project_settings import load_project_settings
from snapshot_reader import SnapshotReader


TEXTUAL_KINDS = set([
    "pou",
    "gvl",
    "dut",
    "itf",
    "method",
    "action",
    "property",
    "property_accessor",
    "itf_method",
    "persistent_gvl",
    "task_local_gvl",
])

RESOURCE_LIKE_KINDS = set([
    "image",
    "imagepool",
    "imagepool_variant",
    "file_object",
])


def _byte_len(value):
    if value is None:
        return 0
    if not isinstance(value, str):
        value = str(value)
    return len(value.encode("utf-8"))


def _display_path(node):
    parts = [part for part in (node.display_path or []) if part]
    if node.output_name:
        parts.append(node.output_name)
    elif node.name:
        parts.append(node.name)
    return "/".join(parts)


def _category(kind, node):
    if kind in RESOURCE_LIKE_KINDS:
        return "resource-like"
    if kind in TEXTUAL_KINDS or node.code:
        return "text"
    if kind:
        return "xml"
    return "unknown"


def _node_size(node, category):
    if category == "text":
        return _byte_len(node.code or "")
    return _byte_len(node.xml_text or "")


def _format_size(size):
    return "{:,}".format(int(size or 0))


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def _write_log(path, lines):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _summary_by_category(rows):
    summary = {}
    for row in rows:
        category = row["category"]
        item = summary.setdefault(category, {"count": 0, "bytes": 0})
        item["count"] += 1
        item["bytes"] += row["size_bytes"]
    return summary


def _top_by_category(rows, limit):
    result = {}
    for row in rows:
        result.setdefault(row["category"], []).append(row)
    for category, items in result.items():
        result[category] = sorted(items, key=lambda item: item["size_bytes"], reverse=True)[:limit]
    return result


def _profile(project_root):
    settings = load_project_settings(project_root)
    return settings, load_profile(settings.get("profile"))


def build_resources_report(project_root, snapshot_path, report_path, log_path=None, limit=50):
    settings, profile = _profile(project_root)
    model = SnapshotReader(snapshot_path).read()
    if model is None:
        raise RuntimeError("Could not read snapshot: {0}".format(snapshot_path))

    rows = []
    for guid, node in sorted(model.nodes.items(), key=lambda item: (item[1].display_path, item[1].name)):
        kind = kind_for_type_guid(profile, node.type)
        category = _category(kind, node)
        size = _node_size(node, category)
        rows.append({
            "guid": guid,
            "name": node.name,
            "path": _display_path(node),
            "type_guid": node.type or "",
            "kind": kind or "unknown",
            "category": category,
            "size_bytes": size,
            "xml_bytes": _byte_len(node.xml_text or ""),
            "text_bytes": _byte_len(node.code or ""),
            "implementation_kind": node.metadata.get("implementation_kind", ""),
            "exclude_from_build": node.metadata.get("exclude_from_build"),
        })

    rows.sort(key=lambda item: item["size_bytes"], reverse=True)
    total_bytes = sum(item["size_bytes"] for item in rows)
    summary = {
        "object_count": len(rows),
        "total_bytes": total_bytes,
        "profile": profile.get("_profile_id") or settings.get("profile") or "default",
        "snapshot_path": snapshot_path,
        "by_category": _summary_by_category(rows),
    }
    report = {
        "summary": summary,
        "top": rows[:limit],
        "top_by_category": _top_by_category(rows, limit),
        "objects": rows,
    }
    _write_json(report_path, report)

    if log_path:
        lines = []
        lines.append("=== CODESYS Project Resource Analysis ===")
        lines.append("Snapshot: " + snapshot_path)
        lines.append("Profile: " + summary["profile"])
        lines.append("Objects: " + str(summary["object_count"]))
        lines.append("Total measured size: " + _format_size(total_bytes) + " bytes")
        lines.append("")
        lines.append("By category:")
        for category, item in sorted(summary["by_category"].items()):
            lines.append(
                " - {0}: {1} objects, {2} bytes".format(
                    category, item["count"], _format_size(item["bytes"])
                )
            )
        lines.append("")
        lines.append("{:<12} | {:>12} | {:<22} | {:<40} | {}".format(
            "Category", "Size", "Kind", "Name", "Path"
        ))
        lines.append("-" * 120)
        for row in rows[:limit]:
            lines.append("{:<12} | {:>12} | {:<22} | {:<40} | {}".format(
                row["category"][:12],
                _format_size(row["size_bytes"]),
                row["kind"][:22],
                row["name"][:40],
                row["path"],
            ))
        _write_log(log_path, lines)

    print("Resources report generated at:", report_path)
    if log_path:
        print("Resources log generated at:", log_path)
    return report
