# -*- coding: utf-8 -*-
"""
codesys_directory_operation.py - Sets the per-project sync directory.

Moved out of the root Project_directory.py so that ScriptDir only ever holds
thin generated menu stubs. Reached through codesys_runtime.run_operation, which
guarantees codesys_utils and codesys_ui are loaded and hands us a runtime whose
UI adapter also works headless.

Indentation here is 4 spaces, matching the dialog code this file was moved
from, rather than the 1 space used by the older bridge modules.
"""
from __future__ import print_function

import os

from codesys_runtime import resolve_runtime
from codesys_utils import (
    log_info,
    project_file_path,
    relativize_to_project,
    resolve_projects,
    resolve_sync_folder,
    suggest_sync_folder,
)


PROJECT_SETTINGS_FILENAME = "cds-text-sync.json"


def _is_first_configuration(project, selected_path):
    """True when the chosen folder has no project settings of its own yet.

    Distinguishes onboarding from reconfiguration: a folder that already holds
    cds-text-sync.json has been through the options dialog before.
    """
    try:
        resolved = resolve_sync_folder(selected_path, project)
    except ValueError:
        return False
    return not os.path.exists(os.path.join(resolved, PROJECT_SETTINGS_FILENAME))


def _open_project_options(runtime):
    """Continue into the options dialog once a folder is configured.

    This is the only moment when the sync mode is still free to choose: the
    manifest fixes it on first export and nothing afterwards can move it. It is
    also where a fresh folder gets its .gitignore entries. Cancelling here
    leaves the folder configured - the two steps are deliberately not tied.
    """
    try:
        import codesys_options_operation
        return codesys_options_operation.main({}, runtime)
    except Exception as error:
        log_info("Could not open project options: " + str(error))
        return None


def _browse_start_dir(project, configured):
    """Where the folder browser opens: the current folder, else the project.

    FolderBrowserDialog ignores a preselected path that does not exist, so an
    unresolvable or not-yet-created folder falls back to the project directory
    rather than dropping the user at the root of the machine.
    """
    if configured:
        try:
            resolved = resolve_sync_folder(configured, project)
        except ValueError:
            resolved = ""
        if resolved and os.path.isdir(resolved):
            return resolved
    project_file = project_file_path(project)
    if project_file and os.path.isabs(project_file):
        return os.path.dirname(project_file)
    return ""


def _browse_for_folder(runtime, project, configured):
    picked = runtime.system.ui.browse_directory_dialog(
        "Select Sync Directory for this Project",
        _browse_start_dir(project, configured),
    )
    # Browsing inside the project yields a portable relative path; a path the
    # user types is left exactly as typed.
    return relativize_to_project(picked, project) if picked else picked


def _query_for_folder(runtime, message, default):
    system_ui = getattr(getattr(runtime, "system", None), "ui", None)
    if system_ui is None or not hasattr(system_ui, "query_string"):
        return None
    return system_ui.query_string(message, default)


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    if projects_obj is None or not getattr(projects_obj, "primary", None):
        message = "No project open! Please open a project to set its sync directory."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    return set_base_directory(runtime, projects_obj)


def set_base_directory(runtime, projects_obj):
    proj = projects_obj.primary

    # Get Project Information object safely
    info = None
    if hasattr(proj, "get_project_info"):
        info = proj.get_project_info()
    elif hasattr(proj, "project_info"):
        info = proj.project_info

    if not info:
        message = "Could not access Project Information!"
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    # Try to read current value for better UX
    initial_dir = ""
    try:
        props = info.values if hasattr(info, "values") else info
        if "cds-sync-folder" in props:  # Dictionary-like access
            initial_dir = props["cds-sync-folder"]
    except Exception as error:
        log_info("Could not read existing sync-folder property: " + str(error))

    # A configured folder wins over the suggestion: this command is also how a
    # project gets reconfigured, and the current value is the better starting
    # point there.
    suggestion = initial_dir or suggest_sync_folder(proj) or "."

    from codesys_ui import show_sync_folder_dialog
    selected_path = show_sync_folder_dialog(
        "Project Sync Configuration",
        suggestion,
        browse=lambda: _browse_for_folder(runtime, proj, initial_dir),
        query=lambda message, default: _query_for_folder(runtime, message, default),
    )

    if not selected_path:
        print("Operation cancelled by user.")
        return {"status": "cancelled"}

    # Normalize path separators
    selected_path = selected_path.replace('/', os.sep).replace('\\', os.sep)

    try:
        resolve_sync_folder(selected_path, proj)
    except ValueError as error:
        message = str(error)
        runtime.ui.error(message)
        return {"status": "error", "error": message}
    is_relative = not os.path.isabs(selected_path)
    # Deciding before the write keeps this a question about the folder the user
    # picked, not about what the options dialog may create a moment later.
    chain_options = not getattr(runtime, "is_headless", True) and _is_first_configuration(
        proj, selected_path
    )

    # Save strictly to project properties
    try:
        props = info.values if hasattr(info, "values") else info
        props["cds-sync-folder"] = selected_path

        # Save current PC name to detect project transfers
        try:
            import socket
            props["cds-sync-pc"] = socket.gethostname()
        except Exception as error:
            log_info("Could not record sync-directory host name: " + str(error))

        if is_relative:
            print("Success: Project sync directory set to relative path: " + selected_path)
        else:
            print("Success: Project sync directory updated to: " + selected_path)
        # The options dialog opens next in the onboarding case and is itself the
        # confirmation; a popup in between would be a third window in a row.
        if not chain_options:
            if is_relative:
                runtime.ui.info("Sync directory saved as relative path.\n\nThis path will be resolved relative to the project file location at runtime.\n\nPath: " + selected_path)
            else:
                runtime.ui.info("Sync directory saved to Project Information > Properties.")
    except Exception as e:
        message = "Could not save to project properties: " + str(e)
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    # Update application count flag
    try:
        from codesys_utils import update_application_count_flag
        update_application_count_flag()
    except Exception as error:
        log_info("Could not update application-count flag: " + str(error))

    # Check _metadata.json for project path mismatch (only for absolute paths)
    if not is_relative:
        try:
            metadata_path = os.path.join(selected_path, "_metadata.json")
            if os.path.exists(metadata_path):
                import json
                with open(metadata_path, 'r') as f:
                    data = json.load(f)

                json_path = data.get('project_path', '')

                # Safe way to get current project path
                current_path = ""
                try:
                    current_path = proj.path
                except Exception as error:
                    log_info("Could not read current project path: " + str(error))

                if current_path and json_path and json_path != current_path:
                    message = "Metadata Mismatch Detected!\n\n"
                    message += "The selected directory contains exports from a different project:\n"
                    message += "Metadata Path: " + json_path + "\n"
                    message += "Current Project: " + current_path + "\n\n"
                    message += "Do you want to update the metadata to match the current project?"

                    # Offer to update
                    if runtime.ui.ask_yes_no("Update Metadata?", message):
                        data['project_path'] = current_path
                        try:
                            data['project_name'] = str(proj)
                        except Exception as error:
                            log_info("Could not read current project name: " + str(error))

                        with open(metadata_path, 'w') as f:
                            json.dump(data, f, indent=2)
                        print("Updated _metadata.json project path to current project.")
                        runtime.ui.info("Metadata updated successfully.")

        except Exception as e:
            print("Warning: Failed to check metadata: " + str(e))

    result = {"status": "ok", "sync_folder": selected_path, "relative": is_relative}
    if chain_options:
        options = _open_project_options(runtime)
        result["options"] = (options or {}).get("status") or "unavailable"
    return result
