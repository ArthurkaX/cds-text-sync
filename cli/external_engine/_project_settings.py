# -*- coding: utf-8 -*-
"""
_project_settings.py - Project settings loader and writer.

The settings file is intentionally tracked and non-dot-prefixed so it can live
next to root-view project files without being treated as generated state.
"""
from __future__ import print_function
import json
import os

from _project_layout import LAYOUT_PROJECT_VIEW, normalize_layout_mode


SETTINGS_FILENAME = "cds-text-sync.json"


def default_project_settings():
    return {
        "version": 1,
        "layout": LAYOUT_PROJECT_VIEW,
        "view_root": None,
        "profile": "default",
        "projections": {},
        "verbose_logging": False,
        "show_completion_popup": True,
        "pre_import_backup_enabled": True,
        "backup_retention_count": 10,
    }


def settings_path(project_root):
    return os.path.join(project_root, SETTINGS_FILENAME)


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def _safe_positive_int(value, default):
    try:
        result = int(value)
    except Exception:
        return default
    if result < 1:
        return default
    return result


def _normalize_view_root(project_root, value):
    if not value:
        return None
    view_root = str(value)
    if os.path.isabs(view_root):
        return os.path.abspath(os.path.normpath(view_root))
    return os.path.abspath(os.path.normpath(os.path.join(project_root, view_root)))


def load_project_settings(project_root):
    settings = default_project_settings()
    path = settings_path(project_root)
    if not os.path.exists(path):
        return settings

    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except Exception as error:
        print("Warning: Could not read project settings {0}: {1}".format(path, error))
        return settings

    if not isinstance(data, dict):
        print("Warning: Ignoring project settings because root JSON value is not an object:", path)
        return settings

    try:
        settings["layout"] = normalize_layout_mode(data.get("layout", settings["layout"]))
    except Exception as error:
        print("Warning: Ignoring invalid layout in project settings {0}: {1}".format(path, error))

    settings["view_root"] = _normalize_view_root(project_root, data.get("view_root"))
    if data.get("profile"):
        settings["profile"] = str(data.get("profile"))
    settings["projections"] = _safe_dict(data.get("projections"))
    settings["verbose_logging"] = _safe_bool(
        data.get("verbose_logging"),
        settings["verbose_logging"],
    )
    settings["show_completion_popup"] = _safe_bool(
        data.get("show_completion_popup"),
        settings["show_completion_popup"],
    )
    settings["pre_import_backup_enabled"] = _safe_bool(
        data.get("pre_import_backup_enabled"),
        settings["pre_import_backup_enabled"],
    )
    settings["backup_retention_count"] = _safe_positive_int(
        data.get("backup_retention_count"),
        settings["backup_retention_count"],
    )
    return settings


def save_project_settings(project_root, settings):
    current = default_project_settings()
    data = _safe_dict(settings)

    try:
        current["layout"] = normalize_layout_mode(data.get("layout", current["layout"]))
    except Exception:
        current["layout"] = LAYOUT_PROJECT_VIEW

    current["view_root"] = data.get("view_root") or None
    if current["view_root"]:
        current["view_root"] = str(current["view_root"])
    if data.get("profile"):
        current["profile"] = str(data.get("profile"))
    current["projections"] = _safe_dict(data.get("projections"))
    current["verbose_logging"] = _safe_bool(
        data.get("verbose_logging"),
        current["verbose_logging"],
    )
    current["show_completion_popup"] = _safe_bool(
        data.get("show_completion_popup"),
        current["show_completion_popup"],
    )
    current["pre_import_backup_enabled"] = _safe_bool(
        data.get("pre_import_backup_enabled"),
        current["pre_import_backup_enabled"],
    )
    current["backup_retention_count"] = _safe_positive_int(
        data.get("backup_retention_count"),
        current["backup_retention_count"],
    )

    path = settings_path(project_root)
    with open(path, "w") as handle:
        json.dump(current, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return current
