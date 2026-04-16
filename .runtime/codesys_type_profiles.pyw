# -*- coding: utf-8 -*-
"""
codesys_type_profiles.py - Manual type profiles for CODESYS variants.

Profiles map runtime GUIDs to semantic kinds. The semantic kinds are then
resolved to canonical GUIDs from codesys_constants.pyw, so the rest of the
sync engine can continue to use the existing manager and path logic.
"""
from __future__ import print_function
import os
import sys

try:
    from codesys_constants import TYPE_GUIDS
except ImportError:
    try:
        import importlib.util
        _HAS_IMPORTLIB_UTIL = True
    except ImportError:
        _HAS_IMPORTLIB_UTIL = False

    try:
        import imp
        _HAS_IMP = True
    except ImportError:
        _HAS_IMP = False

    def _load_constants():
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codesys_constants.pyw")
        if _HAS_IMPORTLIB_UTIL:
            spec = importlib.util.spec_from_file_location("codesys_constants", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules["codesys_constants"] = module
                spec.loader.exec_module(module)
                return module
        if _HAS_IMP:
            module = imp.load_source("codesys_constants", path)
            sys.modules["codesys_constants"] = module
            return module
        raise ImportError("codesys_constants.pyw not found.")

    TYPE_GUIDS = _load_constants().TYPE_GUIDS


DEFAULT_PROFILE_NAME = "codesys_sp20_plus"
PROJECT_PROPERTY_KEY = "cds-sync-type-profile"


def _unique_guids(*values):
    result = []
    seen = set()
    for value in values:
        if not value:
            continue
        lowered = str(value).lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(lowered)
    return result


def _profile_guid(kind, *extras):
    return _unique_guids(TYPE_GUIDS.get(kind), *extras)


_BASE_GUID_ALIASES = {
    "pou": _profile_guid("pou"),
    "gvl": _profile_guid("gvl"),
    "dut": _profile_guid("dut"),
    "action": _profile_guid("action"),
    "method": _profile_guid("method"),
    "property": _profile_guid("property"),
    "property_accessor": _profile_guid("property_accessor"),
    "folder": _profile_guid("folder"),
    "device": _profile_guid("device"),
    "device_module": _profile_guid("device_module"),
    "plc_logic": _profile_guid("plc_logic"),
    "application": _profile_guid(
        "application",
        "6394ad93-46a4-4927-8819-c1ca8654c6ad"
    ),
    "library_manager": _profile_guid("library_manager"),
    "task_config": _profile_guid("task_config"),
    "task": _profile_guid("task"),
    "task_call": _profile_guid("task_call"),
    "itf": _profile_guid("itf"),
    "itf_method": _profile_guid("itf_method"),
    "nvl_sender": _profile_guid("nvl_sender"),
    "nvl_receiver": _profile_guid("nvl_receiver"),
    "param_list": _profile_guid("param_list"),
    "persistent_gvl": _profile_guid(
        "persistent_gvl",
        "261bd6e6-249c-4232-bb6f-84c2fbeef430"
    ),
    "recipe_manager": _profile_guid("recipe_manager"),
    "recipe": _profile_guid("recipe"),
    "visu": _profile_guid("visu"),
    "textlist": _profile_guid("textlist"),
    "global_text_list": _profile_guid("global_text_list"),
    "imagepool": _profile_guid("imagepool"),
    "visu_manager": _profile_guid("visu_manager"),
    "web_visu": _profile_guid("web_visu"),
    "alarm_config": _profile_guid("alarm_config"),
    "alarm_group": _profile_guid("alarm_group"),
    "alarm_storage": _profile_guid("alarm_storage"),
    "symbol_config": _profile_guid("symbol_config"),
    "target_visu": _profile_guid("target_visu"),
    "image": _profile_guid("image"),
    "trace": _profile_guid("trace"),
    "project_info": _profile_guid("project_info"),
    "alarm_config_item": _profile_guid("alarm_config_item"),
    "file_object": _profile_guid("file_object"),
    "alarm_class": _profile_guid("alarm_class"),
    "imagepool_variant": _profile_guid("imagepool_variant"),
    "unit_conversion": _profile_guid("unit_conversion"),
    "softmotion_pool": _profile_guid("softmotion_pool"),
    "visu_style": _profile_guid("visu_style"),
    "task_local_gvl": _profile_guid("task_local_gvl"),
    "project_settings": _profile_guid("project_settings"),
}


PROFILES = {
    "codesys_sp20_plus": {
        "label": "CODESYS SP20+",
        "guid_aliases": dict((k, list(v)) for k, v in _BASE_GUID_ALIASES.items()),
    },
    "codesys_sp17": {
        "label": "CODESYS SP17-SP19",
        "guid_aliases": dict((k, list(v)) for k, v in _BASE_GUID_ALIASES.items()),
    },
    "astra_sp17": {
        "label": "Astra IDE SP17 Fork",
        "guid_aliases": dict((k, list(v)) for k, v in _BASE_GUID_ALIASES.items()),
    },
    "cont_sp16": {
        "label": "CONT Designer SP16 Fork",
        "guid_aliases": dict((k, list(v)) for k, v in _BASE_GUID_ALIASES.items()),
    },
}


def list_profiles():
    return sorted(PROFILES.keys())


def get_profile(profile_name=None):
    name = normalize_profile_name(profile_name)
    return PROFILES.get(name, PROFILES[DEFAULT_PROFILE_NAME])


def normalize_profile_name(profile_name):
    if not profile_name:
        return DEFAULT_PROFILE_NAME
    value = str(profile_name).strip()
    if value in PROFILES:
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
    return str(TYPE_GUIDS.get(kind, "")).lower() or None


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
