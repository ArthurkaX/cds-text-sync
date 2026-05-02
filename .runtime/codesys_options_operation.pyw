# -*- coding: utf-8 -*-
"""
codesys_options_operation.pyw - Minimal project settings workflow.

This first options entrypoint intentionally avoids a full UI. It creates or
updates cds-text-sync.json from explicit params and reports the active values.
"""
from __future__ import print_function
import os
import sys
import json

from codesys_runtime import resolve_runtime
from codesys_utils import load_base_dir, init_logging


RECOMMENDED_GITIGNORE_ENTRIES = [
    ".dump/",
    ".backup/",
    ".diff/",
    "sync_debug.log",
    "build.log",
]


def _ensure_gitignore_entries(project_root):
    path = os.path.join(project_root, ".gitignore")
    existing_text = ""
    existing_lines = []
    if os.path.exists(path):
        with open(path, "r") as handle:
            existing_text = handle.read()
        existing_lines = [line.strip() for line in existing_text.splitlines()]

    missing = [entry for entry in RECOMMENDED_GITIGNORE_ENTRIES if entry not in existing_lines]
    if not missing:
        return {"path": path, "added": []}

    with open(path, "a") as handle:
        if existing_text and not existing_text.endswith(("\n", "\r")):
            handle.write("\n")
        if existing_text and existing_text.strip():
            handle.write("\n")
        handle.write("# cds-text-sync generated state\n")
        for entry in missing:
            handle.write(entry + "\n")
    return {"path": path, "added": missing}


def _compact_settings(settings):
    projections = settings.get("projections") or {}
    return (
        "layout={0}, view_root={1}, profile={2}, projections={3}, verbose_logging={4}, pre_import_backup={5}, backup_retention={6}".format(
            settings.get("layout"),
            settings.get("view_root") or "<default>",
            settings.get("profile"),
            len(projections),
            settings.get("verbose_logging"),
            settings.get("pre_import_backup_enabled"),
            settings.get("backup_retention_count"),
        )
    )


def _export_lock_info(project_root):
    manifest_path = os.path.join(project_root, ".dump", "manifest.json")
    if not os.path.exists(manifest_path):
        return {
            "locked": False,
            "path": manifest_path,
            "view_root": None,
        }
    view_root = None
    try:
        with open(manifest_path, "r") as handle:
            manifest = json.load(handle)
        view_root = manifest.get("view_root") or manifest.get("views_path")
    except Exception:
        view_root = None
    return {
        "locked": True,
        "path": manifest_path,
        "view_root": view_root,
    }


def _setting_changed(settings, key, value):
    current = settings.get(key)
    if key == "view_root":
        current = current or None
        value = value or None
    return current != value


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}

    init_logging(base_dir)

    utility_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    engine_dir = os.path.join(utility_root, "src", "external_engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    try:
        from _project_profiles import list_profiles, load_profile, projection_options
        from _project_settings import load_project_settings, save_project_settings, settings_path

        settings = load_project_settings(base_dir)
        export_lock = _export_lock_info(base_dir)
        settings["_view_root_locked"] = export_lock.get("locked")
        settings["_view_root_lock_path"] = export_lock.get("path")
        settings["_view_root_lock_value"] = export_lock.get("view_root")
        profile = load_profile(settings.get("profile"))
        settings["_available_profiles"] = list_profiles()
        settings["_available_projections"] = projection_options(profile)
        changed = False
        has_explicit_params = any(key in params for key in (
            "layout",
            "view_root",
            "profile",
            "projections",
            "verbose_logging",
            "ensure_gitignore",
            "pre_import_backup_enabled",
            "backup_retention_count",
        ))

        if export_lock.get("locked") and "layout" in params and _setting_changed(settings, "layout", params.get("layout")):
            message = "View storage cannot be changed after export. To choose another folder, start over with a clean sync directory."
            runtime.ui.error(message)
            return {"status": "error", "error": message}
        if export_lock.get("locked") and "view_root" in params and _setting_changed(settings, "view_root", params.get("view_root")):
            message = "Custom view root cannot be changed after export. To choose another folder, start over with a clean sync directory."
            runtime.ui.error(message)
            return {"status": "error", "error": message}

        if "layout" in params:
            settings["layout"] = params.get("layout")
            changed = True
        if "view_root" in params:
            settings["view_root"] = params.get("view_root") or None
            changed = True
        if "profile" in params:
            settings["profile"] = params.get("profile") or "default"
            profile = load_profile(settings.get("profile"))
            settings["_available_projections"] = projection_options(profile)
            changed = True
        if "projections" in params and isinstance(params.get("projections"), dict):
            settings["projections"] = params.get("projections")
            changed = True
        if "verbose_logging" in params:
            settings["verbose_logging"] = params.get("verbose_logging")
            changed = True
        if "pre_import_backup_enabled" in params:
            settings["pre_import_backup_enabled"] = params.get("pre_import_backup_enabled")
            changed = True
        if "backup_retention_count" in params:
            settings["backup_retention_count"] = params.get("backup_retention_count")
            changed = True

        ensure_gitignore = bool(params.get("ensure_gitignore", False))

        if not has_explicit_params and not runtime.is_headless:
            selected = runtime.ui.show_project_options_dialog(settings)
            if selected is None:
                runtime.ui.info("Project sync options cancelled.")
                return {"status": "cancelled", "settings": settings, "path": settings_path(base_dir)}
            ensure_gitignore = bool(selected.pop("_ensure_gitignore", False))
            settings.update(selected)
            changed = True

        gitignore_result = None
        if ensure_gitignore:
            gitignore_result = _ensure_gitignore_entries(base_dir)

        if changed or bool(params.get("create", True)):
            settings = save_project_settings(base_dir, settings)
            message = "Project sync settings saved:\n" + settings_path(base_dir) + "\n" + _compact_settings(settings)
            if gitignore_result:
                if gitignore_result.get("added"):
                    message += "\n.gitignore updated:\n" + gitignore_result.get("path")
                else:
                    message += "\n.gitignore already contains recommended entries."
            runtime.ui.info(message)
            return {"status": "success", "settings": settings, "path": settings_path(base_dir), "gitignore": gitignore_result}

        runtime.ui.info("Project sync settings:\n" + settings_path(base_dir) + "\n" + _compact_settings(settings))
        return {"status": "success", "settings": settings, "path": settings_path(base_dir), "gitignore": gitignore_result}
    except Exception as e:
        runtime.ui.error("Error updating project sync options: " + str(e))
        return {"status": "error", "error": str(e)}
