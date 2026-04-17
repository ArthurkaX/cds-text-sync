# -*- coding: utf-8 -*-
"""
codesys_type_profiles.py - JSON-based type profiles for CODESYS variants.

Profiles are loaded from .json files in the profiles/ directory.
Each profile maps runtime GUIDs to semantic kinds and optionally
provides context rules and sync profile overrides.

If profiles/ is missing or empty, a built-in hardcoded fallback is used.
"""
from __future__ import print_function
import os
import sys

try:
    import json
    _HAS_JSON = True
except ImportError:
    _HAS_JSON = False


DEFAULT_PROFILE_NAME = "codesys_sp20_plus"
PROJECT_PROPERTY_KEY = "cds-sync-type-profile"

_BUILT_IN_PROFILES = {
    "codesys_sp20_plus", "codesys_sp17", "astra_sp17", "cont_sp16",
}


def _profiles_dir():
    try:
        this_file = os.path.abspath(__file__)
    except Exception:
        this_file = os.path.abspath(sys.modules.get(__name__, type('', (), {})).__file__ if hasattr(sys.modules.get(__name__, type('', (), {})), '__file__') else '.')
    runtime_dir = os.path.dirname(this_file)
    tool_root = os.path.dirname(runtime_dir)
    candidate = os.path.join(tool_root, "profiles")
    if os.path.isdir(candidate):
        return candidate
    parent_root = os.path.dirname(os.path.dirname(tool_root))
    candidate2 = os.path.join(parent_root, "profiles")
    if os.path.isdir(candidate2):
        return candidate2
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv else '.'))
    candidate3 = os.path.join(script_dir, "profiles")
    if os.path.isdir(candidate3):
        return candidate3
    return candidate


def _parse_simple_json(text):
    text = text.strip()
    if not text:
        return None
    text = text.replace("\t", " ")
    mapping = {"true": "True", "false": "False", "null": "None"}
    for old, new in mapping.items():
        text = text.replace(old, new)
    try:
        return eval(text)
    except Exception:
        return None


def _load_json_profile(filepath):
    try:
        with open(filepath, "r") as f:
            text = f.read()
        if _HAS_JSON:
            return json.loads(text)
        return _parse_simple_json(text)
    except Exception:
        return None


def _normalize_aliases(raw_aliases):
    result = {}
    if not raw_aliases or not isinstance(raw_aliases, dict):
        return result
    for kind, guids in raw_aliases.items():
        if isinstance(guids, str):
            guids = [guids]
        result[kind] = [str(g).lower() for g in guids]
    return result


def _merge_aliases(base, override):
    merged = dict(base)
    for kind, guids in override.items():
        if kind in merged:
            seen = set(merged[kind])
            for g in guids:
                if g not in seen:
                    merged[kind].append(g)
                    seen.add(g)
        else:
            merged[kind] = list(guids)
    return merged


def _merge_rules(base, override):
    if not base:
        return list(override or [])
    if not override:
        return list(base)
    return list(base) + list(override)


def _resolve_extends(profile_data, all_raw):
    extends = profile_data.get("extends")
    if not extends:
        return profile_data
    parent = all_raw.get(extends)
    if not parent:
        return profile_data
    parent = _resolve_extends(parent, all_raw)
    parent_aliases = _normalize_aliases(parent.get("guid_aliases", {}))
    child_aliases = _normalize_aliases(profile_data.get("guid_aliases", {}))
    merged = _merge_aliases(parent_aliases, child_aliases)
    parent_rules = parent.get("context_rules", [])
    child_rules = profile_data.get("context_rules", [])
    result = {
        "name": profile_data.get("name"),
        "label": profile_data.get("label", parent.get("label")),
        "description": profile_data.get("description", parent.get("description")),
        "guid_aliases": merged,
        "context_rules": _merge_rules(parent_rules, child_rules),
    }
    parent_overrides = parent.get("sync_profile_overrides", {})
    child_overrides = profile_data.get("sync_profile_overrides", {})
    if parent_overrides or child_overrides:
        overrides = dict(parent_overrides)
        overrides.update(child_overrides)
        result["sync_profile_overrides"] = overrides
    return result


def _hardcoded_fallback():
    return {
        "codesys_sp20_plus": {
            "name": "codesys_sp20_plus",
            "label": "CODESYS SP20+ (built-in fallback)",
            "guid_aliases": {},
            "context_rules": [],
        },
    }


_cache = None
_cache_raw = None


def _ensure_loaded():
    global _cache, _cache_raw
    if _cache is None:
        try:
            raw = {}
            profiles_dir = _profiles_dir()
            if os.path.isdir(profiles_dir):
                for filename in os.listdir(profiles_dir):
                    if not filename.endswith(".json"):
                        continue
                    filepath = os.path.join(profiles_dir, filename)
                    data = _load_json_profile(filepath)
                    if data and data.get("name"):
                        raw[data["name"]] = data
            _cache_raw = raw
            resolved = {}
            for name, data in raw.items():
                resolved[name] = _resolve_extends(data, raw)
            _cache = resolved
        except Exception:
            _cache = _hardcoded_fallback()
            _cache_raw = {}
        if not _cache:
            _cache = _hardcoded_fallback()
            _cache_raw = {}
    return _cache


def _ensure_loaded_raw():
    _ensure_loaded()
    return _cache_raw or {}


def reload_profiles():
    global _cache, _cache_raw
    _cache = None
    _cache_raw = None
    return _ensure_loaded()


def _get_profiles():
    return _ensure_loaded()


def list_profiles():
    return sorted(_get_profiles().keys())


def get_profile(profile_name=None):
    name = normalize_profile_name(profile_name)
    return _get_profiles().get(name, _get_profiles().get(DEFAULT_PROFILE_NAME, {}))


def normalize_profile_name(profile_name):
    if not profile_name:
        return DEFAULT_PROFILE_NAME
    value = str(profile_name).strip()
    if value in _get_profiles():
        return value
    return DEFAULT_PROFILE_NAME


def get_profile_label(profile_name):
    profile = get_profile(profile_name)
    return profile.get("label", normalize_profile_name(profile_name))


def get_profile_guid_to_kind(profile_name=None):
    profile = get_profile(profile_name)
    result = {}
    for kind, aliases in profile.get("guid_aliases", {}).items():
        for guid in aliases:
            result[str(guid).lower()] = kind
    return result


def get_profile_raw_guid(kind, profile_name=None):
    profile = get_profile(profile_name)
    aliases = profile.get("guid_aliases", {}).get(kind, [])
    if aliases:
        return aliases[0]
    return None


def get_profile_context_rules(profile_name=None):
    profile = get_profile(profile_name)
    return profile.get("context_rules", [])


def get_profile_sync_profile_overrides(profile_name=None):
    profile = get_profile(profile_name)
    return profile.get("sync_profile_overrides", {})


def get_profile_description(profile_name):
    profile = get_profile(profile_name)
    return profile.get("description", "")


def get_profile_extends(profile_name):
    raw = _ensure_loaded_raw()
    data = raw.get(normalize_profile_name(profile_name), {})
    return data.get("extends", "")


def is_user_profile(profile_name):
    return normalize_profile_name(profile_name) not in _BUILT_IN_PROFILES


def get_profiles_dir():
    return _profiles_dir()


def resolve_profile_name(explicit_profile=None, params=None, project_profile=None):
    params = params or {}
    if explicit_profile:
        return normalize_profile_name(explicit_profile)
    if params.get("type_profile"):
        return normalize_profile_name(params.get("type_profile"))
    if params.get("profile"):
        return normalize_profile_name(params.get("profile"))
    if project_profile:
        return normalize_profile_name(project_profile)
    return DEFAULT_PROFILE_NAME
