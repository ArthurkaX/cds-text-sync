# -*- coding: utf-8 -*-
"""
codesys_options_operation.py - Minimal project settings workflow.

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
    ".dump/*",
    "!.dump/",
    "!.dump/IDE.xml",
    "!.dump/manifest.json",
    ".backup/",
    ".diff/",
    "sync_debug.log",
    "compare.log",
    "build.log",
    "build-report*.json",
]

LEGACY_GITIGNORE_ENTRIES = [
    ".dump/",
]


def _ensure_gitignore_entries(project_root):
    path = os.path.join(project_root, ".gitignore")
    existing_text = ""
    existing_lines = []
    if os.path.exists(path):
        with open(path, "r") as handle:
            existing_text = handle.read()
        existing_lines = [line.strip() for line in existing_text.splitlines()]

    migrated = []
    if existing_lines:
        kept_lines = []
        changed = False
        for line in existing_text.splitlines():
            stripped = line.strip()
            if stripped in LEGACY_GITIGNORE_ENTRIES:
                migrated.append(stripped)
                changed = True
                continue
            kept_lines.append(line)
        if changed:
            existing_text = "\n".join(kept_lines)
            if existing_text:
                existing_text += "\n"
            existing_lines = [line.strip() for line in kept_lines]

    missing = [entry for entry in RECOMMENDED_GITIGNORE_ENTRIES if entry not in existing_lines]
    if not missing and not migrated:
        return {"path": path, "added": [], "migrated": []}

    with open(path, "w") as handle:
        handle.write(existing_text)
        if existing_text and not existing_text.endswith(("\n", "\r")):
            handle.write("\n")
        if existing_text and existing_text.strip():
            handle.write("\n")
        handle.write("# cds-text-sync generated state\n")
        for entry in missing:
            handle.write(entry + "\n")
    return {"path": path, "added": missing, "migrated": migrated}


def _compact_settings(settings):
    projections = settings.get("projections") or {}
    return (
        "layout={0}, view_root={1}, profile={2}, sync_mode={3}, projections={4}, verbose_logging={5}, completion_popup={6}, pre_import_backup={7}, backup_retention={8}".format(
            settings.get("layout"),
            settings.get("view_root") or "<default>",
            settings.get("profile"),
            settings.get("sync_mode"),
            len(projections),
            settings.get("verbose_logging"),
            settings.get("show_completion_popup"),
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
            "sync_mode": None,
        }
    view_root = None
    sync_mode = None
    try:
        with open(manifest_path, "r") as handle:
            manifest = json.load(handle)
        view_root = manifest.get("view_root") or manifest.get("views_path")
        sync_mode = manifest.get("sync_mode")
    except Exception:
        view_root = None
        sync_mode = None
    return {
        "locked": True,
        "path": manifest_path,
        "view_root": view_root,
        "sync_mode": sync_mode,
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
    engine_dir = os.path.join(utility_root, "cds_text_sync", "engine")
    if not os.path.isdir(engine_dir):
        engine_dir = os.path.join(utility_root, "src", "external_engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    try:
        from _project_profiles import (
            list_profiles,
            load_profile,
            projection_options,
            xml_in_view_kind_options,
        )
        from _project_settings import (
            load_project_settings,
            normalize_sync_mode,
            save_project_settings,
            settings_path,
        )

        settings = load_project_settings(base_dir)
        export_lock = _export_lock_info(base_dir)
        settings["_view_root_locked"] = export_lock.get("locked")
        settings["_view_root_lock_path"] = export_lock.get("path")
        settings["_view_root_lock_value"] = export_lock.get("view_root")
        settings["_sync_mode_locked"] = export_lock.get("locked")
        settings["_sync_mode_lock_value"] = normalize_sync_mode(
            export_lock.get("sync_mode"), settings.get("sync_mode")
        )
        if export_lock.get("locked"):
            # The manifest is the authority on the mode once initialized.
            settings["sync_mode"] = settings["_sync_mode_lock_value"]
        profile = load_profile(settings.get("profile"))
        settings["_available_profiles"] = list_profiles()
        settings["_available_projections"] = projection_options(profile)
        settings["_available_xml_in_view_kinds"] = xml_in_view_kind_options(profile)
        changed = False
        has_explicit_params = any(key in params for key in (
            "layout",
            "view_root",
            "profile",
            "projections",
            "sync_mode",
            "xml_in_view_kinds",
            "verbose_logging",
            "show_completion_popup",
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
        if export_lock.get("locked") and "sync_mode" in params and _setting_changed(
            settings, "sync_mode", normalize_sync_mode(params.get("sync_mode"), settings.get("sync_mode"))
        ):
            message = "Sync mode is fixed at initialization. To switch between XML-first and text-first, initialize a new empty sync folder."
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
            settings["_available_xml_in_view_kinds"] = xml_in_view_kind_options(profile)
            changed = True
        if "projections" in params and isinstance(params.get("projections"), dict):
            settings["projections"] = params.get("projections")
            changed = True
        if "sync_mode" in params:
            settings["sync_mode"] = normalize_sync_mode(
                params.get("sync_mode"), settings.get("sync_mode")
            )
            changed = True
        if "xml_in_view_kinds" in params and isinstance(
            params.get("xml_in_view_kinds"), (list, tuple)
        ):
            settings["xml_in_view_kinds"] = list(params.get("xml_in_view_kinds"))
            changed = True
        if "verbose_logging" in params:
            settings["verbose_logging"] = params.get("verbose_logging")
            changed = True
        if "show_completion_popup" in params:
            settings["show_completion_popup"] = params.get("show_completion_popup")
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
            if export_lock.get("locked"):
                # Belt-and-braces: the mode can never change after initialization.
                settings["sync_mode"] = settings["_sync_mode_lock_value"]
            changed = True

        gitignore_result = None
        if ensure_gitignore:
            gitignore_result = _ensure_gitignore_entries(base_dir)

        if changed or bool(params.get("create", True)):
            settings = save_project_settings(base_dir, settings)
            message = "Project sync settings saved:\n" + settings_path(base_dir) + "\n" + _compact_settings(settings)
            if gitignore_result:
                if gitignore_result.get("added") or gitignore_result.get("migrated"):
                    message += "\n.gitignore updated:\n" + gitignore_result.get("path")
                    if gitignore_result.get("migrated"):
                        message += "\nMigrated legacy entries: " + ", ".join(gitignore_result.get("migrated"))
                else:
                    message += "\n.gitignore already contains recommended entries."
            runtime.ui.info(message)
            return {"status": "success", "settings": settings, "path": settings_path(base_dir), "gitignore": gitignore_result}

        runtime.ui.info("Project sync settings:\n" + settings_path(base_dir) + "\n" + _compact_settings(settings))
        return {"status": "success", "settings": settings, "path": settings_path(base_dir), "gitignore": gitignore_result}
    except Exception as e:
        runtime.ui.error("Error updating project sync options: " + str(e))
        return {"status": "error", "error": str(e)}
