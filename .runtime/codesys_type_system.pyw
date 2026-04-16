# -*- coding: utf-8 -*-
"""
codesys_type_system.py - Profile-aware type resolution for CODESYS objects.

This first pass keeps compatibility with the legacy GUID-based engine:
- runtime GUIDs are resolved to semantic kinds using the selected profile
- semantic kinds are mapped back to canonical GUIDs from codesys_constants
- context rules can override ambiguous runtime GUIDs
"""
from __future__ import print_function

import re
import os
import sys

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


def _load_sibling_module(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".pyw")
    if _HAS_IMPORTLIB_UTIL:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    if _HAS_IMP:
        module = imp.load_source(name, path)
        sys.modules[name] = module
        return module
    raise ImportError(name + ".pyw not found.")

from codesys_constants import TYPE_GUIDS
try:
    from codesys_type_profiles import (
        DEFAULT_PROFILE_NAME, PROJECT_PROPERTY_KEY, get_profile_guid_to_kind,
        get_profile_raw_guid, get_profile_label, list_profiles, resolve_profile_name
    )
except ImportError:
    _type_profiles = _load_sibling_module("codesys_type_profiles")
    DEFAULT_PROFILE_NAME = _type_profiles.DEFAULT_PROFILE_NAME
    PROJECT_PROPERTY_KEY = _type_profiles.PROJECT_PROPERTY_KEY
    get_profile_guid_to_kind = _type_profiles.get_profile_guid_to_kind
    get_profile_raw_guid = _type_profiles.get_profile_raw_guid
    get_profile_label = _type_profiles.get_profile_label
    list_profiles = _type_profiles.list_profiles
    resolve_profile_name = _type_profiles.resolve_profile_name


SEMANTIC_TYPE_NAMES = sorted(TYPE_GUIDS.keys())
SEMANTIC_EXPORTABLE_KINDS = set([
    "pou", "gvl", "dut", "itf", "nvl_sender", "nvl_receiver",
    "param_list", "textlist", "global_text_list", "symbol_config",
    "imagepool", "unit_conversion", "visu", "visu_manager",
    "alarm_config", "alarm_group", "alarm_storage", "task_config",
    "task", "library_manager", "trace", "softmotion_pool", "visu_style",
    "project_settings", "device", "file_object", "alarm_class",
    "imagepool_variant", "alarm_config_item", "device_module",
    "action", "method", "itf_method", "property", "property_accessor",
    "task_local_gvl",
])
SEMANTIC_XML_KINDS = set([
    "visu", "textlist", "global_text_list", "imagepool",
    "symbol_config", "alarm_config", "alarm_group", "alarm_storage",
    "visu_manager", "task_config", "task", "library_manager",
    "trace", "softmotion_pool", "visu_style", "project_settings",
    "device", "device_module", "file_object", "alarm_class",
    "imagepool_variant", "alarm_config_item", "task_local_gvl",
    "nvl_sender", "nvl_receiver",
])
SEMANTIC_IMPLEMENTATION_KINDS = set([
    "pou", "action", "method",
])
_SKIP_KINDS = set([
    "property_accessor",
    "task",
    "device",
    "device_module",
    "visu_style",
])
_NATIVE_XML_KINDS = set([
    "task_config",
    "alarm_config",
    "visu_manager",
    "softmotion_pool",
    "nvl_sender",
    "nvl_receiver",
])
_NESTED_MEMBER_KINDS = set([
    "action",
    "method",
    "property",
    "itf_method",
    "task_call",
])
_TEXTUAL_KINDS = set([
    "pou",
    "gvl",
    "dut",
    "itf",
    "param_list",
    "recipe_manager",
    "recipe",
    "textlist",
    "global_text_list",
    "imagepool",
    "symbol_config",
    "target_visu",
    "image",
    "trace",
    "project_info",
    "alarm_config_item",
    "file_object",
    "alarm_class",
    "imagepool_variant",
    "unit_conversion",
    "visu_style",
    "task_local_gvl",
    "project_settings",
    "library_manager",
])
_CREATION_STRATEGY_BY_KIND = {
    "folder": "create_folder",
    "gvl": "create_gvl",
    "task_local_gvl": "create_gvl",
    "dut": "create_dut",
    "itf": "create_interface",
    "method": "create_method",
    "property": "create_property",
    "action": "create_action",
    "pou": "create_pou",
}


SYNC_PROFILE_CATEGORIES = {
    "textual": _TEXTUAL_KINDS,
    "native_xml": _NATIVE_XML_KINDS,
    "nested_member": _NESTED_MEMBER_KINDS,
    "skip": _SKIP_KINDS,
}


def _safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


def get_selected_profile_name(params=None, project_profile=None, explicit_profile=None):
    return resolve_profile_name(explicit_profile, params=params, project_profile=project_profile)


def get_selected_profile_label(profile_name):
    return get_profile_label(profile_name)


def get_selected_profile_raw_guid(kind, profile_name=None):
    return get_profile_raw_guid(kind, profile_name)


def semantic_kind_to_guid(kind, profile_name=None):
    if not kind:
        return None
    return get_profile_raw_guid(kind, profile_name or DEFAULT_PROFILE_NAME)


def is_exportable_kind(semantic_kind):
    return semantic_kind in SEMANTIC_EXPORTABLE_KINDS


def is_xml_kind(semantic_kind):
    return semantic_kind in SEMANTIC_XML_KINDS


def can_have_implementation_kind(semantic_kind):
    return semantic_kind in SEMANTIC_IMPLEMENTATION_KINDS


def _resolve_sync_profile(semantic_kind, is_xml=False):
    if not semantic_kind:
        return "skip"
    if semantic_kind in _SKIP_KINDS:
        return "skip"
    if semantic_kind in _NATIVE_XML_KINDS or is_xml:
        return "native_xml"
    if semantic_kind in _NESTED_MEMBER_KINDS:
        return "nested_member"
    return "textual"


def _resolve_creation_strategy(semantic_kind):
    if not semantic_kind:
        return "create_child"
    return _CREATION_STRATEGY_BY_KIND.get(semantic_kind, "create_child")


def semantic_kind_from_guid(raw_guid, profile_name=None):
    if not raw_guid:
        return None
    guid_map = get_profile_guid_to_kind(profile_name)
    return guid_map.get(str(raw_guid).lower())


def is_guid_kind(raw_guid, semantic_kind, profile_name=None):
    if not raw_guid or not semantic_kind:
        return False
    return semantic_kind_from_guid(raw_guid, profile_name) == semantic_kind


def _apply_context_rules(raw_guid, semantic_kind, parent_kind=None, obj_name=None):
    obj_name = _safe_str(obj_name).lower()

    if semantic_kind == "alarm_group":
        if parent_kind in ["task_config", "task"]:
            return "task_call", ["context_parent=%s" % parent_kind]
        if parent_kind != "alarm_config" and (obj_name.endswith(".cyclic") or obj_name.endswith(".bustask")):
            return "task_call", ["context_name=%s" % obj_name]

    return semantic_kind, []


def resolve_runtime_guid(raw_guid, profile_name=None, parent_kind=None, obj_name=None):
    raw_guid = _safe_str(raw_guid).lower()
    semantic_kind = semantic_kind_from_guid(raw_guid, profile_name)
    evidence = []

    if semantic_kind:
        evidence.append("guid_alias")
    else:
        evidence.append("unknown_guid")

    semantic_kind, context_evidence = _apply_context_rules(
        raw_guid, semantic_kind, parent_kind=parent_kind, obj_name=obj_name
    )
    evidence.extend(context_evidence)

    canonical_guid = semantic_kind_to_guid(semantic_kind, profile_name)
    if not canonical_guid and raw_guid:
        canonical_guid = raw_guid
    sync_profile = _resolve_sync_profile(semantic_kind, is_xml=semantic_kind in _NATIVE_XML_KINDS)
    creation_strategy = _resolve_creation_strategy(semantic_kind)
    manager_key = semantic_kind or canonical_guid

    return {
        "profile_name": profile_name or DEFAULT_PROFILE_NAME,
        "raw_guid": raw_guid,
        "semantic_kind": semantic_kind,
        "canonical_guid": canonical_guid,
        "known": bool(semantic_kind),
        "evidence": evidence,
        "sync_profile": sync_profile,
        "creation_strategy": creation_strategy,
        "manager_key": manager_key,
    }


def resolve_runtime_object(obj, profile_name=None):
    raw_guid = _safe_str(getattr(obj, "type", None)).lower()
    obj_name = None
    try:
        obj_name = obj.get_name()
    except Exception:
        obj_name = None

    parent_kind = None
    try:
        parent = getattr(obj, "parent", None)
        if parent is not None:
            parent_guid = _safe_str(getattr(parent, "type", None)).lower()
            parent_kind = semantic_kind_from_guid(parent_guid, profile_name)
    except Exception:
        parent_kind = None

    result = resolve_runtime_guid(
        raw_guid, profile_name=profile_name, parent_kind=parent_kind, obj_name=obj_name
    )
    result["name"] = _safe_str(obj_name)
    result["parent_kind"] = parent_kind
    result["is_xml"] = result.get("sync_profile") == "native_xml"
    return result


def determine_semantic_kind(content):
    content = _safe_str(content)
    content = re.sub(r"\(\*[\s\S]*?\*\)", "", content)
    content = re.sub(r"\{[\s\S]*?\}", "", content)
    content = re.sub(r"//.*", "", content)
    content = content.strip()

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if not parts:
            continue

        word = parts[0].upper()
        if word in ["PROGRAM", "FUNCTION_BLOCK", "FUNCTION"]:
            return "pou"
        if word == "VAR_GLOBAL":
            return "gvl"
        if word == "TYPE":
            return "dut"
        if word == "INTERFACE":
            return "itf"
        if word == "METHOD":
            return "method"
        if word == "PROPERTY":
            return "property"
        if word == "ACTION":
            return "action"

    return None


def determine_object_type_guid(content):
    kind = determine_semantic_kind(content)
    return semantic_kind_to_guid(kind)


def determine_object_creation_kind(content):
    return determine_semantic_kind(content)


def list_available_profiles():
    return list_profiles()


def get_profile_property_key():
    return PROJECT_PROPERTY_KEY
