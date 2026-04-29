# -*- coding: utf-8 -*-
"""
codesys_utils.pyw - Minimal helpers for the XML-first extract/inject flow.
"""
from __future__ import print_function
import os
import sys


def safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return "<unprintable>"


def log_info(message):
    print("[INFO] " + safe_str(message))


def log_warning(message):
    print("[WARNING] " + safe_str(message))


def log_error(message, critical=False):
    print("[ERROR] " + safe_str(message))


def resolve_system(caller_globals=None):
    if caller_globals and "system" in caller_globals:
        return caller_globals["system"]
    try:
        import __main__
        return getattr(__main__, "system", None)
    except Exception:
        return None


def is_valid_projects(obj):
    if obj is None:
        return False
    try:
        return obj.primary is not None
    except Exception:
        return False


def resolve_projects(projects_obj=None, caller_globals=None):
    if is_valid_projects(projects_obj):
        return projects_obj
    if caller_globals and "projects" in caller_globals and is_valid_projects(caller_globals["projects"]):
        return caller_globals["projects"]
    try:
        import __main__
        candidate = getattr(__main__, "projects", None)
        if is_valid_projects(candidate):
            return candidate
    except Exception:
        pass
    for module in list(sys.modules.values()):
        try:
            candidate = getattr(module, "projects", None)
            if is_valid_projects(candidate):
                return candidate
        except Exception:
            pass
    return None


def _project_info_values():
    projects_obj = resolve_projects()
    project = projects_obj.primary if projects_obj else None
    if project is None:
        return None
    info = None
    if hasattr(project, "get_project_info"):
        info = project.get_project_info()
    elif hasattr(project, "project_info"):
        info = project.project_info
    if info is None:
        return None
    return info.values if hasattr(info, "values") else info


def get_project_prop(key, default=None):
    try:
        props = _project_info_values()
        if props is not None and key in props:
            return props[key]
    except Exception:
        pass
    return default


def set_project_prop(key, value):
    props = _project_info_values()
    if props is None:
        return False
    props[key] = value
    return True


def init_logging(base_dir):
    return None


def load_base_dir():
    base_dir = get_project_prop("cds-sync-folder")
    if not base_dir:
        return None, "Project sync directory is not set. Run Project_directory.py first."

    base_dir = safe_str(base_dir).strip()
    is_relative = base_dir == "." or base_dir.startswith("./") or base_dir.startswith(".\\")
    if is_relative:
        projects_obj = resolve_projects()
        project = projects_obj.primary if projects_obj else None
        project_path = safe_str(getattr(project, "path", ""))
        if not project_path:
            return None, "Cannot resolve relative sync directory: project path is not available."
        project_dir = os.path.dirname(project_path)
        base_dir = os.path.normpath(os.path.join(project_dir, base_dir.replace("/", os.sep).replace("\\", os.sep)))

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    return base_dir, None


def update_application_count_flag():
    return True
