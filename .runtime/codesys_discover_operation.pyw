# -*- coding: utf-8 -*-
"""
codesys_discover_operation.pyw - Diagnose CODESYS object tree and profile coverage.
"""
from __future__ import print_function
import codecs
import json
import os

from codesys_runtime import resolve_runtime
from codesys_utils import load_base_dir, init_logging, resolve_projects, safe_str


def _utility_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_engine_path():
    import sys
    engine_dir = os.path.join(_utility_root(), "cli", "external_engine")
    if not os.path.isdir(engine_dir):
        engine_dir = os.path.join(_utility_root(), "src", "external_engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    return engine_dir


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


def _load_settings_profile(base_dir):
    _ensure_engine_path()
    from _project_profiles import kind_for_type_guid, load_profile, projection_options
    from _project_settings import load_project_settings
    settings = load_project_settings(base_dir)
    profile = load_profile(settings.get("profile"))
    return settings, profile, kind_for_type_guid, projection_options


def _type_guid(obj):
    return safe_str(getattr(obj, "type", "")).strip().lower()


def _guid(obj):
    return safe_str(getattr(obj, "guid", "")).strip().lower()


def _name(obj):
    try:
        return safe_str(obj.get_name())
    except Exception:
        return safe_str(getattr(obj, "name", ""))


def _class_name(obj):
    try:
        return obj.__class__.__name__
    except Exception:
        return ""


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


def _project_name(project):
    try:
        if hasattr(project, "get_name"):
            return safe_str(project.get_name())
        if hasattr(project, "name"):
            return safe_str(project.name)
        if hasattr(project, "path"):
            return os.path.basename(safe_str(project.path))
    except Exception:
        pass
    return "Unknown Project"


def _direct_kind(profile, kind_for_type_guid, obj):
    try:
        return kind_for_type_guid(profile, _type_guid(obj))
    except Exception:
        return None


def _apply_context_rules(profile, direct_kind, parent_kind, obj_name):
    rules = profile.get("context_rules")
    if not isinstance(rules, list):
        return direct_kind
    result = direct_kind
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        when_kind = rule.get("when_kind")
        if when_kind and when_kind != result:
            continue
        when_parent_kind = rule.get("when_parent_kind")
        if when_parent_kind and when_parent_kind != parent_kind:
            continue
        when_name_suffix = rule.get("when_name_suffix")
        if when_name_suffix and not safe_str(obj_name).lower().endswith(safe_str(when_name_suffix).lower()):
            continue
        if rule.get("then_kind"):
            result = rule.get("then_kind")
    return result


def _sync_profile(profile, kind):
    overrides = profile.get("sync_profile_overrides")
    if isinstance(overrides, dict) and kind in overrides:
        return overrides.get(kind)
    directions = profile.get("sync_direction_overrides")
    if isinstance(directions, dict) and kind in directions:
        return directions.get(kind)
    return ""


def _suggest_profile(unknown_types, profile_id):
    aliases = {}
    lines = []
    for type_guid, example in sorted(unknown_types.items()):
        kind = "unknown_kind_" + type_guid[:8]
        aliases[kind] = [type_guid]
        lines.append("# Unknown GUID found in: {0}".format(example))
        lines.append("#   GUID: {0}".format(type_guid))
        lines.append("#   Kind: {0}".format(kind))
        lines.append("")
    return {
        "name": profile_id + "_custom",
        "label": profile_id + " (Custom)",
        "description": "Custom profile extending " + profile_id + " with unknown GUIDs found in project",
        "extends": profile_id,
        "guid_aliases": aliases,
        "_notes": lines,
    }


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
    settings, profile, kind_for_type_guid, projection_options = _load_settings_profile(base_dir)
    profile_id = profile.get("_profile_id") or settings.get("profile") or "default"

    try:
        all_objects = list(project.get_children(recursive=True))
    except Exception as error:
        runtime.ui.error("Could not enumerate project objects: " + safe_str(error))
        return {"status": "error", "error": safe_str(error)}

    by_guid = {}
    children_map = {}
    root_children = []
    for obj in all_objects:
        obj_guid = _guid(obj)
        if obj_guid:
            by_guid[obj_guid] = obj
    for obj in all_objects:
        parent_guid = ""
        try:
            parent = getattr(obj, "parent", None)
            if parent:
                parent_guid = _guid(parent)
        except Exception:
            parent_guid = ""
        if parent_guid and parent_guid in by_guid:
            children_map.setdefault(parent_guid, []).append(obj)
        else:
            root_children.append(obj)

    kind_by_guid = {}
    for obj in all_objects:
        parent_kind = None
        try:
            parent = getattr(obj, "parent", None)
            if parent:
                parent_kind = _direct_kind(profile, kind_for_type_guid, parent)
        except Exception:
            pass
        direct = _direct_kind(profile, kind_for_type_guid, obj)
        kind_by_guid[_guid(obj)] = _apply_context_rules(profile, direct, parent_kind, _name(obj))

    tree_lines = []
    objects = []
    unknown_types = {}

    def append_node(obj, level):
        obj_guid = _guid(obj)
        type_guid = _type_guid(obj)
        kind = kind_by_guid.get(obj_guid)
        is_unknown = not kind
        if is_unknown:
            kind = "UNKNOWN_" + type_guid[:8]
            if type_guid:
                unknown_types[type_guid] = _name(obj)
        sync_profile = _sync_profile(profile, kind)
        prefix = "[!] " if is_unknown else ""
        parts = [kind, type_guid]
        if sync_profile:
            parts.append(sync_profile)
        parts.append(_class_name(obj))
        line = "  " * level + "|-- " + prefix + _name(obj) + " (" + " | ".join(parts) + ")"
        tree_lines.append(line)
        objects.append({
            "guid": obj_guid,
            "parent_guid": _guid(getattr(obj, "parent", None)),
            "name": _name(obj),
            "type_guid": type_guid,
            "kind": kind,
            "sync_profile": sync_profile,
            "class": _class_name(obj),
            "level": level,
            "unknown": is_unknown,
        })
        for child in children_map.get(obj_guid, []):
            append_node(child, level + 1)

    for obj in root_children:
        append_node(obj, 0)

    enabled_projection_ids = []
    selected = settings.get("projections") or {}
    for projection in projection_options(profile):
        projection_id = projection.get("id")
        if projection_id and selected.get(projection_id):
            enabled_projection_ids.append(projection_id)

    report = {
        "status": "success",
        "project_name": _project_name(project),
        "codesys_version": _system_version(runtime),
        "sync_root": base_dir,
        "profile": profile_id,
        "object_count": len(all_objects),
        "unknown_type_count": len(unknown_types),
        "unknown_types": unknown_types,
        "enabled_projections": enabled_projection_ids,
        "objects": objects,
    }
    if unknown_types:
        report["suggested_profile"] = _suggest_profile(unknown_types, profile_id)

    lines = []
    lines.append("=== CODESYS Project Discovery ===")
    lines.append("Project: " + report["project_name"])
    lines.append("CODESYS version: " + (report["codesys_version"] or "unknown"))
    lines.append("Sync root: " + base_dir)
    lines.append("Profile: " + profile_id)
    lines.append("Objects: " + str(len(all_objects)))
    lines.append("Unknown type GUIDs: " + str(len(unknown_types)))
    if enabled_projection_ids:
        lines.append("Enabled projections: " + ", ".join(enabled_projection_ids))
    lines.append("")
    lines.extend(tree_lines)
    if unknown_types:
        lines.append("")
        lines.append("!!! UNKNOWN OBJECT TYPES FOUND !!!")
        for type_guid, example in sorted(unknown_types.items()):
            lines.append(" - {0} (Example: {1})".format(type_guid, example))
        lines.append("")
        lines.append("Suggested profile JSON is included in discover_report.json.")

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
            len(all_objects), len(unknown_types), tree_path, report_path
        )
    )
    return {"status": "success", "report": report_path, "tree": tree_path}
