# -*- coding: utf-8 -*-
"""
discover_report.py - Shared CODESYS project-discovery report builder.

Builds the object-tree + profile-coverage diagnostic (kind resolution, unknown
type detection, enabled projections) from a live CODESYS project plus the
on-disk sync settings/profile. Pure logic: no runtime/ui/file-IO, so both the
forward-mode operation (codesys_discover_operation.pyw) and the reverse-pipe
daemon handler (ide_handlers_project._cmd_discover) reuse it instead of
duplicating ~150 lines.

The offline-engine profile modules (_project_profiles/_project_settings) are
imported lazily inside build_discovery_report, so importing this module stays
cheap and free of engine dependencies (keeps the daemon name-resolution guard
happy under CPython). This module imports no .pyw modules, so it is importable
by name under both CPython and IronPython.
"""

from __future__ import print_function

import os
import sys


def _engine_dir():
    """Locate cli/external_engine relative to this file (src/ide_bridge/)."""
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    engine = os.path.join(root, "cli", "external_engine")
    if not os.path.isdir(engine):
        engine = os.path.join(root, "src", "external_engine")
    return engine


def _ensure_engine_path():
    engine = _engine_dir()
    if engine not in sys.path:
        sys.path.insert(0, engine)
    return engine


def _safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return "<unprintable>"


def _type_guid(obj):
    return _safe_str(getattr(obj, "type", "")).strip().lower()


def _guid(obj):
    return _safe_str(getattr(obj, "guid", "")).strip().lower()


def _name(obj):
    try:
        return _safe_str(obj.get_name())
    except Exception:
        return _safe_str(getattr(obj, "name", ""))


def _class_name(obj):
    try:
        return obj.__class__.__name__
    except Exception:
        return ""


def _project_name(project):
    try:
        if hasattr(project, "get_name"):
            return _safe_str(project.get_name())
        if hasattr(project, "name"):
            return _safe_str(project.name)
        if hasattr(project, "path"):
            return os.path.basename(_safe_str(project.path))
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
        if when_name_suffix and not _safe_str(obj_name).lower().endswith(
            _safe_str(when_name_suffix).lower()
        ):
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
        "description": "Custom profile extending "
        + profile_id
        + " with unknown GUIDs found in project",
        "extends": profile_id,
        "guid_aliases": aliases,
        "_notes": lines,
    }


def build_discovery_report(project, base_dir, codesys_version=""):
    """Build the discovery report dict for *project* rooted at *base_dir*.

    Returns a report dict with status "success" and a flat "objects" list (each
    carrying name/kind/type_guid/sync_profile/class/level/unknown, enough to
    render a tree), or {"status": "error", "error": ...} if the object tree
    cannot be enumerated. Callers wrap this in their own transport
    (forward-mode file output, or the daemon's {"ok": ...} envelope).
    """
    _ensure_engine_path()
    from _project_profiles import (
        kind_for_type_guid,
        load_profile,
        projection_options,
    )
    from _project_settings import load_project_settings

    settings = load_project_settings(base_dir)
    profile = load_profile(settings.get("profile"))
    profile_id = profile.get("_profile_id") or settings.get("profile") or "default"

    try:
        all_objects = list(project.get_children(recursive=True))
    except Exception as error:
        return {"status": "error", "error": _safe_str(error)}

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
        kind_by_guid[_guid(obj)] = _apply_context_rules(
            profile, direct, parent_kind, _name(obj)
        )

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
        objects.append(
            {
                "guid": obj_guid,
                "parent_guid": _guid(getattr(obj, "parent", None)),
                "name": _name(obj),
                "type_guid": type_guid,
                "kind": kind,
                "sync_profile": sync_profile,
                "class": _class_name(obj),
                "level": level,
                "unknown": is_unknown,
            }
        )
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
        "codesys_version": _safe_str(codesys_version),
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
    return report
