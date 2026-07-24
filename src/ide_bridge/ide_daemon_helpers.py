# -*- coding: utf-8 -*-
"""
ide_daemon_helpers.py — Low-level cross-domain helper functions for the CODESYS daemon.

These helpers are shared by multiple command handlers in ide_reverse_pipe_loop.py.
They access CODESYS globals ONLY via the singleton sys._codesys_daemon_loop (lazily
at call time), so they are safe to live in a separate module.
"""

from __future__ import print_function

import os
import sys
import time

import ide_runtime_common as _common
import ide_online_helpers as _helpers
from ide_daemon_state import _json_safe, _build_path, _log, _obj_name

# ── Constants ─────────────────────────────────────────────────────────────

_DEVICE_CACHE_TTL = 30  # seconds
MAX_TREE_DEPTH = 50  # safety guard against cycles


# ── Project info helpers ───────────────────────────────────────────────────


def _get_project_info_object(project):
    try:
        if hasattr(project, "get_project_info"):
            return project.get_project_info()
    except Exception:
        pass
    try:
        if hasattr(project, "project_info"):
            return project.project_info
    except Exception:
        pass
    return None


def _read_project_info_attr(proj_info, names):
    for name in names:
        try:
            if hasattr(proj_info, name):
                value = getattr(proj_info, name)
                if callable(value):
                    value = value()
                if value is not None:
                    return _json_safe(value)
        except Exception:
            pass
    return None


def _project_info_summary(proj_info):
    fields = [
        ("Company", ["Company", "company", "get_company"]),
        ("Title", ["Title", "title", "get_title"]),
        ("Version", ["Version", "version", "get_version"]),
        ("Author", ["Author", "author", "get_author"]),
        ("Description", ["Description", "description", "get_description"]),
        (
            "DefaultNamespace",
            [
                "DefaultNamespace",
                "DefaultNameSpace",
                "defaultNamespace",
                "default_namespace",
                "defaultnamespace",
                "get_default_namespace",
            ],
        ),
        ("URL", ["URL", "Url", "url", "get_url"]),
    ]
    summary = {}
    for key, names in fields:
        value = _read_project_info_attr(proj_info, names)
        if value is not None:
            summary[key] = value
    return summary


def _mapping_to_dict(values):
    result = {}
    if values is None:
        return result

    try:
        for key, value in values.items():
            result[_json_safe(key)] = _json_safe(value)
        return result
    except Exception:
        pass

    keys = None
    for attr in ("keys", "Keys"):
        try:
            keys = getattr(values, attr)
            if callable(keys):
                keys = keys()
            if keys is not None:
                break
        except Exception:
            keys = None
    if keys is not None:
        try:
            for key in keys:
                try:
                    result[_json_safe(key)] = _json_safe(values[key])
                except Exception:
                    pass
            return result
        except Exception:
            pass

    try:
        for item in values:
            try:
                if hasattr(item, "Key") and hasattr(item, "Value"):
                    result[_json_safe(item.Key)] = _json_safe(item.Value)
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    result[_json_safe(item[0])] = _json_safe(item[1])
                else:
                    result[_json_safe(item)] = _json_safe(values[item])
            except Exception:
                pass
    except Exception:
        pass
    return result


def _project_info_properties(proj_info):
    try:
        values = getattr(proj_info, "values", None)
    except Exception:
        values = None
    if values is None:
        values = proj_info
    return _mapping_to_dict(values)


# ── Device / object cache helpers ─────────────────────────────────────────


def _get_device_objects(project):
    """Get project children with TTL cache."""
    cache = sys._codesys_daemon_loop.get("device_cache")
    cache_ts = sys._codesys_daemon_loop.get("device_cache_ts", 0)
    now = time.time()
    if cache is not None and (now - cache_ts) < _DEVICE_CACHE_TTL:
        return cache
    objs = list(project.get_children(recursive=True))
    sys._codesys_daemon_loop["device_cache"] = objs
    sys._codesys_daemon_loop["device_cache_ts"] = now
    return objs


def _invalidate_device_cache():
    """Force invalidate the device cache."""
    sys._codesys_daemon_loop["device_cache_ts"] = 0


def _find_object_in_project(project, obj_name, app_name=None):
    """Find a named object in the project tree.

    Returns (target, obj_type) or (None, None) if not found.
    If app_name is given, only matches objects under that application.
    """
    for child in _get_device_objects(project):
        try:
            cname = str(_common.object_name(child))
        except Exception as e:
            _log("Object search: failed to read object name: {0}".format(e))
            continue

        if cname != obj_name:
            continue

        if app_name:
            parent = child
            found_in_app = False
            while hasattr(parent, "parent"):
                try:
                    parent = parent.parent
                    pname = str(_common.object_name(parent))
                except Exception as e:
                    _log(
                        "Object search: failed to inspect parent chain for '{0}': {1}".format(
                            obj_name, e
                        )
                    )
                    break
                if pname == app_name:
                    found_in_app = True
                    break
            if not found_in_app:
                continue

        try:
            obj_type = str(child.get_type())
        except Exception:
            obj_type = "Unknown"
        return child, obj_type

    return None, None


def _active_application_name(project):
    try:
        app = _helpers.get_active_application(project)
        if app is not None:
            return str(_common.object_name(app))
    except Exception:
        pass
    return ""


def _read_text_member(obj, attr_name):
    try:
        member = getattr(obj, attr_name, None)
        if member is None:
            return None
        if hasattr(member, "text"):
            text = member.text
            if callable(text):
                text = text()
            return _json_safe(text)
        return _json_safe(str(member))
    except Exception:
        return None


def _find_object_by_selector(project, params):
    guid = str(params.get("guid", "") or "").lower()
    path = str(params.get("path", "") or "").replace("\\", "/").strip("/")
    name = str(params.get("name", "") or "")

    for child in _get_device_objects(project):
        try:
            child_name = str(_common.object_name(child))
        except Exception:
            child_name = ""
        try:
            child_guid = str(getattr(child, "Guid", "")).lower()
        except Exception:
            child_guid = ""
        try:
            child_path = _build_path(child).replace("\\", "/").strip("/")
        except Exception:
            child_path = ""

        if guid and child_guid == guid:
            return child
        if path and child_path == path:
            return child
        if name and child_name == name:
            return child

    return None


def _ensure_online_app(project):
    try:
        online_app, target_app = _helpers.ensure_online_connection(project)
        if online_app is not None:
            sys._codesys_daemon_loop["online_app"] = online_app
            sys._codesys_daemon_loop["online_target_app"] = target_app
        return online_app, target_app, None
    except Exception as e:
        return None, None, str(e)


# ── Tree building ──────────────────────────────────────────────────────────


def _build_tree(obj, depth=0, current_depth=0):
    if current_depth > MAX_TREE_DEPTH:
        return {"name": _obj_name(obj), "_truncated": True}
    node = {"name": _obj_name(obj)}
    try:
        guid = obj.Guid
        if guid:
            node["guid"] = str(guid)
    except Exception:
        pass
    if depth > 0 and current_depth >= depth:
        return node
    try:
        children = obj.get_children()
        child_list = []
        for child in children:
            child_list.append(
                _build_tree(child, depth=depth, current_depth=current_depth + 1)
            )
        if child_list:
            node["children"] = child_list
    except Exception:
        pass
    return node


# ── Sync folder helper ─────────────────────────────────────────────────────


def _get_sync_folder():
    """Get the sync folder path from project properties.

    Returns:
        (path, error) tuple. path is None if not configured.
    """
    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return None, "projects not captured"
    try:
        prj = projects.primary
        if prj is None:
            return None, "No active project"
        proj_info = None
        if hasattr(prj, "get_project_info"):
            proj_info = prj.get_project_info()
        elif hasattr(prj, "project_info"):
            proj_info = prj.project_info
        if proj_info is None:
            return None, "Project info not available"
        props = getattr(proj_info, "values", proj_info)
        base_dir = ""
        if hasattr(props, "__getitem__"):
            try:
                if "cds-sync-folder" in props:
                    base_dir = props["cds-sync-folder"]
            except Exception:
                try:
                    base_dir = props.get("cds-sync-folder", "")
                except Exception:
                    pass
        if not base_dir:
            return (
                None,
                "Sync folder not configured. Set 'cds-sync-folder' project property (Tools → Project_directory.py)",
            )
        base_dir = str(base_dir).strip()
        # Resolve relative paths
        is_relative = (
            base_dir == "." or base_dir.startswith("./") or base_dir.startswith(".\\")
        )
        if is_relative:
            project_path = ""
            for attr in ["path", "filename", "FileName", "FullName", "Path"]:
                try:
                    val = getattr(prj, attr)
                    if val:
                        project_path = str(val)
                        break
                except Exception:
                    pass
            if project_path:
                project_dir = os.path.dirname(project_path)
                base_dir = os.path.normpath(
                    os.path.join(
                        project_dir, base_dir.replace("/", os.sep).replace("\\", os.sep)
                    )
                )
        return base_dir, None
    except Exception as e:
        return None, str(e)


# ── Online state detection ─────────────────────────────────────────────────


def _active_app_online_state():
    """Best-effort detection of whether the active application has a live
    online session. Returns (is_online, state_str). Never raises -- on any
    failure returns (False, "") so callers can proceed.
    """
    try:
        import scriptengine as se

        # Prefer the cached online_app if it still reports connected.
        try:
            from ide_online_helpers import _get_cached_online_app

            oa, _ = _get_cached_online_app()
            if oa is not None:
                state = ""
                if hasattr(oa, "application_state"):
                    try:
                        state = str(oa.application_state)
                    except Exception:
                        pass
                for attr in ("is_connected", "is_online"):
                    if hasattr(oa, attr):
                        try:
                            val = getattr(oa, attr)
                            if callable(val):
                                val = val()
                            if val:
                                return (True, state or "connected")
                        except Exception:
                            pass
                return (False, state or "disconnected")
        except Exception:
            pass

        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return (False, "")
        app = projects.primary.active_application
        if app is None:
            return (False, "")
        oa = se.online.create_online_application(app)
        if oa is None:
            return (False, "disconnected")
        state = ""
        if hasattr(oa, "application_state"):
            try:
                state = str(oa.application_state)
            except Exception:
                pass
        online = False
        for attr in ("is_connected", "is_online"):
            if hasattr(oa, attr):
                try:
                    val = getattr(oa, attr)
                    if callable(val):
                        val = val()
                    if val:
                        online = True
                except Exception:
                    pass
        return (online, state)
    except Exception:
        return (False, "")
