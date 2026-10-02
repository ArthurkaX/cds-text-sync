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
from codesys_utils import resolve_sync_folder
import ide_online_helpers as _helpers
from ide_daemon_state import _json_safe, _build_path, _log, _obj_name, _project_file_path

# ── Constants ─────────────────────────────────────────────────────────────

_DEVICE_CACHE_TTL = 30  # seconds
MAX_TREE_DEPTH = 50  # safety guard against cycles


# ── Project info helpers ───────────────────────────────────────────────────


def _get_project_info_object(project, errors=None):
    """Return the project's Project Information object, or None.

    The lookups may simply be absent on a limited project (the Project
    Information dialog is not always there) -- that is not an error. But a
    lookup that raises for any other reason is recorded in *errors* instead of
    being read as "this project has no properties".
    """
    try:
        if hasattr(project, "get_project_info"):
            return project.get_project_info()
    except AttributeError:
        pass
    except Exception as error:
        if errors is not None:
            errors.append("get_project_info: {0}".format(error))
    try:
        if hasattr(project, "project_info"):
            return project.project_info
    except AttributeError:
        pass
    except Exception as error:
        if errors is not None:
            errors.append("project_info: {0}".format(error))
    return None


def _read_project_info_attr(proj_info, names, errors=None):
    for name in names:
        try:
            if hasattr(proj_info, name):
                value = getattr(proj_info, name)
                if callable(value):
                    value = value()
                if value is not None:
                    return _json_safe(value)
        except AttributeError:
            continue
        except Exception as error:
            if errors is not None:
                errors.append("{0}: {1}".format(name, error))
    return None


def _project_info_summary(proj_info, errors=None):
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
        value = _read_project_info_attr(proj_info, names, errors)
        if value is not None:
            summary[key] = value
    return summary


def _mapping_to_dict(values, errors=None):
    """Convert a CODESYS mapping to a JSON-safe dict, best effort.

    Several collection shapes occur across CODESYS versions, so the fallbacks
    stay. But an entry that cannot be converted is recorded in *errors*
    instead of being dropped in silence: a dropped ``cds-sync-folder`` reads
    as "not configured" and sends the user chasing a settings problem that is
    really a read failure.
    """
    result = {}
    if values is None:
        return result

    try:
        for key, value in values.items():
            try:
                result[_json_safe(key)] = _json_safe(value)
            except Exception as error:
                if errors is not None:
                    errors.append("property {0!r}: {1}".format(key, error))
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
                except Exception as error:
                    if errors is not None:
                        errors.append("property {0!r}: {1}".format(key, error))
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
            except Exception as error:
                if errors is not None:
                    errors.append("property {0!r}: {1}".format(item, error))
    except Exception:
        pass
    return result


def _project_info_properties(proj_info, errors=None):
    try:
        values = getattr(proj_info, "values", None)
    except Exception as error:
        if errors is not None:
            errors.append("project_info.values: {0}".format(error))
        values = None
    if values is None:
        values = proj_info
    return _mapping_to_dict(values, errors)


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
    """Read one text-document member of *obj*.

    None means the object carries no such member: either the attribute is
    absent, or the getter raises -- CODESYS object types without a section
    (GVL/DUT have no textual_implementation) raise instead of returning None,
    which is the same "no such section" answer ``ide_st_objects.read_document``
    reads it as.

    A member that exists but whose text cannot be read is a different thing.
    Returning None there would report a real object as having an empty body and
    ``read_object`` would quietly drop the section, so it raises instead: the
    daemon answers ``ok: false`` with the reason and the CLI prints it.
    """
    try:
        member = getattr(obj, attr_name, None)
    except Exception:
        # The getter itself raises for object types that have no such section.
        return None
    if member is None:
        return None
    try:
        if hasattr(member, "text"):
            text = member.text
            if callable(text):
                text = text()
            return _json_safe(text)
        return _json_safe(str(member))
    except Exception as error:
        raise RuntimeError(
            "Could not read {0} of '{1}': {2}".format(attr_name, _obj_name(obj), error)
        )


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
    """Build the ``project_tree`` display tree for *obj*.

    The tree is a report, so a node that cannot be walked must not vanish: an
    unreadable node carries ``_error`` and stays in its parent's ``children``,
    and the siblings already collected are kept. The old shape wrapped the whole
    child loop in one ``try/except: pass``, so a single failing child (or a
    parent whose ``get_children`` raised) discarded every child collected so far
    and the node was handed out looking like a leaf -- a truncated subtree
    presented as a complete one.
    """
    node = {"name": _obj_name(obj)}
    try:
        guid = _common.object_guid(obj)
    except Exception as error:
        _log(
            "Project tree: could not read the guid of '{0}': {1}".format(
                node["name"], error
            )
        )
        guid = None
    if guid:
        node["guid"] = guid
    if current_depth > MAX_TREE_DEPTH:
        node["_truncated"] = True
        return node
    if depth > 0 and current_depth >= depth:
        return node
    child_list = []
    try:
        for child in obj.get_children():
            child_list.append(
                _build_tree(child, depth=depth, current_depth=current_depth + 1)
            )
    except Exception as error:
        _log(
            "Project tree: could not list the children of '{0}': {1}".format(
                node["name"], error
            )
        )
        node["_error"] = "could not list children: {0}".format(error)
    if child_list:
        node["children"] = child_list
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
        return resolve_sync_folder(base_dir, prj), None
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
