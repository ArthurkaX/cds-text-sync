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
from ide_daemon_state import _json_safe, _build_path, _log, _obj_name, _project_file_path

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


def _normalize_object_path(path):
    """Canonical form for comparing object paths.

    The compare report names an object by its projection file --
    "...\\TASKS AND CORES\\ProgrammTask3.xml" -- while `_build_path` names it
    by its objects -- ".../Task configuration/ProgrammTask3". For the two to
    match, the projection extension is stripped and the comparison is made
    case-insensitively (CODESYS object names are case-insensitive).
    """
    text = str(path or "").replace("\\", "/").strip("/")
    for ext in (".xml", ".st", ".csv"):
        if text.lower().endswith(ext):
            text = text[: -len(ext)]
            break
    return text.lower()


def _find_object_by_selector(project, params):
    """Resolve an object by guid, then path, then name -- in that order.

    The order is the whole point, and it used to be wrong. The test used to be
    made per object -- guid, path, name against one child before moving to the
    next -- so the first object matching on *any* criterion won, and a name
    match on an early object beat an exact guid match on a later one.

    A CODESYS project happily holds a task and a POU under the same name. That
    is what `cts import` hit on ProgrammTask3: the compare report named the POU
    by guid, the scan reached the task first, matched it by name, and the
    import tried to write a POU body into a task object -- "'ScriptObject' has
    no attribute 'textual_declaration'". It failed loudly there, but only
    because a task has nothing to write to. Any two same-named objects that
    *are* both writable would have taken the edit silently, into the wrong one.

    So: three passes over one scan, strongest identifier first.

    Paths are compared with their projection extension stripped and without
    regard to case. The compare report names an object by its file --
    "...\\TASKS AND CORES\\ProgrammTask3.xml" -- while `_build_path` names it
    by its objects -- ".../Task configuration/ProgrammTask3". Requiring those
    to match verbatim meant the path pass never matched anything either.
    """
    guid = _common.normalize_guid(params.get("guid", ""))
    path = _normalize_object_path(params.get("path", ""))
    name = str(params.get("name", "") or "")

    by_path = None
    by_name = None

    for child in _get_device_objects(project):
        if guid:
            if _common.object_guid(child) == guid:
                return child

        if path and by_path is None:
            try:
                child_path = _normalize_object_path(_build_path(child))
            except Exception:
                child_path = ""
            if child_path and child_path == path:
                by_path = child

        if name and by_name is None:
            try:
                child_name = str(_common.object_name(child))
            except Exception:
                child_name = ""
            if child_name and child_name == name:
                by_name = child

    if by_path is not None:
        return by_path
    return by_name


def _online_app_if_connected(project):
    """The existing online session, or (None, None, reason) -- never a new one.

    Opening a session means ``create_online_application`` plus
    ``_ensure_logged_in``, and the latter walks a list of login candidates.
    With no PLC reachable every candidate has to time out before the call
    returns, and the daemon loop is single-threaded: it serves nothing for
    minutes and every other command reports "make sure the daemon is running"
    -- which is exactly wrong, it is running and busy.

    So no command opens a session as a side effect. ``cts connect`` is where
    the user asked to wait; everywhere else an absent session is an answer,
    not a reason to go looking for one. See
    ``ide_online_helpers.require_online_session`` for the measurement.
    """
    try:
        online_app = _helpers.require_online_session(project)
    except Exception as e:
        return None, None, str(e)
    target_app = sys._codesys_daemon_loop.get("online_target_app")
    return online_app, target_app, None


# ── Tree building ──────────────────────────────────────────────────────────


def _build_tree(obj, depth=0, current_depth=0):
    if current_depth > MAX_TREE_DEPTH:
        return {"name": _obj_name(obj), "_truncated": True}
    node = {"name": _obj_name(obj)}
    guid = _common.object_guid(obj)
    if guid:
        node["guid"] = guid
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
        # Resolve relative paths against the project file's directory.
        is_relative = (
            base_dir == "." or base_dir.startswith("./") or base_dir.startswith(".\\")
        )
        if is_relative:
            project_path = _project_file_path(prj)
            if not project_path:
                return (
                    None,
                    "Relative cds-sync-folder '{0}' could not be anchored: the "
                    "project exposes no file path (projects.primary has no "
                    "path/filename). Save the project, or set cds-sync-folder to "
                    "an absolute path via Project_directory.py.".format(base_dir),
                )
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
