# -*- coding: utf-8 -*-
"""
_project_profiles.py - Helpers for loading CODESYS fork/profile metadata.
"""

from __future__ import print_function

import json
import os

ROOT_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", ".."
    )
)
PROFILES_DIR = os.path.join(ROOT_DIR, "profiles")


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _read_json(path):
    with open(path, "r") as handle:
        return json.load(handle)


def _merge_unique_list(base_items, override_items):
    result = []
    seen = set()
    for value in list(base_items or []) + list(override_items or []):
        key = str(value).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _merge_profiles(base, override):
    base = dict(_safe_dict(base))
    override = _safe_dict(override)
    result = dict(base)

    for key, value in override.items():
        if key == "guid_aliases":
            aliases = {}
            for kind, values in _safe_dict(base.get("guid_aliases")).items():
                aliases[kind] = list(values or [])
            for kind, values in _safe_dict(value).items():
                aliases[kind] = _merge_unique_list(aliases.get(kind), values)
            result[key] = aliases
        elif key == "ambiguous_text_type_guids":
            ambig = {}
            for kind, values in _safe_dict(
                base.get("ambiguous_text_type_guids")
            ).items():
                ambig[kind] = list(values or [])
            for kind, values in _safe_dict(value).items():
                ambig[kind] = _merge_unique_list(ambig.get(kind), values)
            result[key] = ambig
        elif key == "context_rules":
            result[key] = list(base.get("context_rules") or []) + list(value or [])
        elif key in ("sync_profile_overrides", "sync_direction_overrides"):
            merged = dict(_safe_dict(base.get(key)))
            merged.update(_safe_dict(value))
            result[key] = merged
        elif key == "projections":
            result[key] = list(value or [])
        else:
            result[key] = value
    return result


def _load_profile_file(profile_name, profiles_dir, visited=None):
    visited = visited or set()
    profile_name = profile_name or "default"
    if profile_name in visited:
        raise ValueError("Profile inheritance cycle: " + profile_name)
    visited.add(profile_name)

    path = os.path.join(profiles_dir, profile_name + ".json")
    if not os.path.exists(path):
        return None

    data = _read_json(path)
    if not isinstance(data, dict):
        return None

    base_name = data.get("extends")
    if base_name:
        base = _load_profile_file(str(base_name), profiles_dir, visited)
        if isinstance(base, dict):
            data = _merge_profiles(base, data)

    data["_profile_id"] = os.path.splitext(os.path.basename(path))[0]
    return data


def list_profiles(profiles_dir=None):
    profiles_dir = profiles_dir or PROFILES_DIR
    result = []
    if not os.path.isdir(profiles_dir):
        return result

    for filename in sorted(os.listdir(profiles_dir)):
        if not filename.lower().endswith(".json"):
            continue
        path = os.path.join(profiles_dir, filename)
        try:
            data = _read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        profile_id = os.path.splitext(filename)[0]
        result.append(
            {
                "id": profile_id,
                "name": data.get("name") or profile_id,
                "label": data.get("label") or data.get("name") or profile_id,
                "path": path,
            }
        )
    return result


def load_profile(profile_name, profiles_dir=None):
    profiles_dir = profiles_dir or PROFILES_DIR
    profile_name = profile_name or "default"
    for candidate in (profile_name, "default"):
        try:
            data = _load_profile_file(candidate, profiles_dir)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {"_profile_id": "default"}


def projection_options(profile):
    profile = _safe_dict(profile)
    projections = profile.get("projections")
    if isinstance(projections, list):
        return [item for item in projections if isinstance(item, dict)]
    return []


def kind_for_type_guid(profile, type_guid):
    profile = _safe_dict(profile)
    guid = (type_guid or "").strip().strip("{}").lower()
    if not guid:
        return None
    for kind, aliases in _safe_dict(profile.get("guid_aliases")).items():
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if guid == str(alias).strip().strip("{}").lower():
                return kind
    return None


def enabled_projection_options(profile, selected):
    selected = _safe_dict(selected)
    result = []
    for projection in projection_options(profile):
        projection_id = projection.get("id")
        kind = projection.get("kind")
        selected_value = None
        if projection_id in selected:
            selected_value = selected.get(projection_id)
        elif kind in selected:
            selected_value = selected.get(kind)
        elif projection.get("default_enabled"):
            selected_value = True

        if isinstance(selected_value, dict):
            if not selected_value.get("enabled", True):
                continue
        elif not selected_value:
            continue

        result.append(projection)
    return result


def _projection_kinds(projection):
    kinds = projection.get("kinds") or [projection.get("kind")]
    return [str(kind).strip().lower() for kind in kinds if kind]


def st_projection_ids(profile):
    """Ids of every ST-format projection defined by the profile."""
    result = []
    for projection in projection_options(profile):
        if str(projection.get("format") or "").strip().lower() != "st":
            continue
        projection_id = projection.get("id") or projection.get("kind")
        if projection_id and projection_id not in result:
            result.append(projection_id)
    return result


def effective_projection_selection(profile, selected, sync_mode=None):
    """Return the projection selection the pipeline should actually use.

    In text-first mode every ST projection is force-enabled - ``.st`` files are
    the editable surface, so they must exist for all st-capable kinds. CSV
    projections keep their per-project opt-in. XML-first returns ``selected``
    unchanged.
    """
    if (sync_mode or "").strip().lower() != "text_first":
        return selected
    result = dict(_safe_dict(selected))
    for projection in projection_options(profile):
        if str(projection.get("format") or "").strip().lower() != "st":
            continue
        projection_id = projection.get("id") or projection.get("kind")
        if not projection_id:
            continue
        result[projection_id] = {
            "enabled": True,
            "kind": projection.get("kind"),
            "format": "st",
            "import_safe": bool(projection.get("import_safe", False)),
        }
    return result


def xml_in_view_kind_options(profile):
    """Kinds that may keep their native XML in the view root in text-first mode.

    Candidates are profile kinds with no ST projection: their XML sidecar is
    the only editable artifact, so hiding it in ``.dump`` makes them
    export-only. Kinds covered by an ST projection are excluded - their text
    lives in ``.st`` files and the XML mirror is internal.
    """
    profile = _safe_dict(profile)
    st_kinds = set()
    for projection in projection_options(profile):
        if str(projection.get("format") or "").strip().lower() != "st":
            continue
        st_kinds.update(_projection_kinds(projection))
    result = []
    for kind in sorted(_safe_dict(profile.get("guid_aliases")).keys()):
        key = str(kind).strip().lower()
        if key and key not in st_kinds and key not in result:
            result.append(key)
    return result
