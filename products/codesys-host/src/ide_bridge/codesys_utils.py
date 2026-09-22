# -*- coding: utf-8 -*-
"""
codesys_utils.py - Minimal helpers for the XML-first extract/inject flow.
"""
from __future__ import print_function
import os
import sys


def _path_text(value):
    try:
        text_type = unicode
    except NameError:
        text_type = str
    return text_type(value or "").strip()


def project_file_path(project):
    """Read ScriptEngine path variants without depending on daemon state."""
    for attribute in ("path", "filename", "FileName", "FullName", "Path"):
        try:
            value = _path_text(getattr(project, attribute, None))
            if value:
                return value
        except Exception:
            pass
    return ""


SYNC_FOLDER_SUFFIX = "-cts"
_FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'


def sanitize_folder_name(value):
    """Reduce a project name to one usable path segment.

    Only what Windows forbids is dropped; non-ASCII names are kept as they are,
    because the parent directory can be non-ASCII regardless and cleaning the
    leaf buys nothing. Whitespace collapses to "-": the result is handed to
    `cts --sync-folder` on a command line, where spaces would need quoting.
    """
    cleaned = []
    for char in _path_text(value):
        if char in _FORBIDDEN_NAME_CHARS or ord(char) < 32:
            continue
        cleaned.append("-" if char.isspace() else char)
    name = "".join(cleaned)
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip(" .-")


def suggest_sync_folder(project):
    """Suggest a sync folder next to the .project file, as a relative name.

    Relative on purpose: the stored property then survives a clone on another
    machine, which is what the docs tell users to prefer. The project name is
    part of it because one directory can hold several projects, and a shared
    bare name would collide on a foreign manifest.

    Returns "" when the project has never been saved and so has nothing to sit
    beside; the caller decides what to do with that.
    """
    project_file = project_file_path(project)
    if not project_file or not os.path.isabs(project_file):
        return ""
    stem = sanitize_folder_name(os.path.splitext(os.path.basename(project_file))[0])
    if not stem:
        return SYNC_FOLDER_SUFFIX.lstrip("-")
    return stem + SYNC_FOLDER_SUFFIX


def relativize_to_project(path, project):
    """Rewrite a path inside the project directory as a project-relative one.

    Applied to what the folder browser returns, never to what the user typed:
    an absolute path entered by hand is taken literally.
    """
    if not path or not os.path.isabs(path):
        return path
    project_file = project_file_path(project)
    if not project_file or not os.path.isabs(project_file):
        return path
    root = os.path.dirname(project_file)
    if not root:
        return path
    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        # Different drives; os.path.relpath raises rather than returning "..".
        return path
    if relative.startswith(".."):
        return path
    return relative


def _checked_path(value):
    value = _path_text(value).replace("/", os.sep).replace("\\", os.sep)
    if not value or "\x00" in value:
        raise ValueError("Sync folder path is empty or contains a null byte")
    # A drive-relative path or a root without a drive depends on process state.
    # Check explicitly: isabs(rooted_path) differs across Python versions.
    if os.name == "nt":
        drive, tail = os.path.splitdrive(value)
        if (drive and tail and not tail.startswith(os.sep)) or (
            not drive and tail.startswith(os.sep)
        ) or (drive and not tail and len(drive) == 2):
            raise ValueError(
                "Use a fully qualified absolute path or a project-relative path; "
                "drive-relative and root-only paths are not supported"
            )
    return value


def resolve_sync_folder(configured, project):
    """Return an absolute sync root, or raise ValueError before any file IO.

    Ordinary relative paths are anchored only to a saved project, never CWD.
    This also serves menu workflows where no daemon has been started.
    """
    value = _checked_path(configured)
    if not os.path.isabs(value):
        project_file = project_file_path(project)
        if project_file:
            project_file = _checked_path(project_file)
        if not project_file or not os.path.isabs(project_file):
            raise ValueError(
                "Cannot resolve relative sync folder: project has not been saved "
                "or has no absolute file path. Save it first, or configure an absolute path."
            )
        value = os.path.join(os.path.dirname(project_file), value)
    return os.path.normpath(value)


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


def log_error(message, critical=False):
    print("[ERROR] " + safe_str(message))


def _utility_root():
    """Repository root containing the CPython ``cds_text_sync`` package."""
    here = os.path.dirname(os.path.abspath(__file__))
    current = here
    while True:
        if os.path.isdir(
            os.path.join(
                current, "products", "cds-text-sync", "src", "cds_text_sync", "engine"
            )
        ):
            return current
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return os.path.dirname(os.path.dirname(here))


def ensure_engine_path():
    """Put the offline engine dir (cds_text_sync/engine) on sys.path and return it.

    Falls back to the historical src/external_engine location when the primary
    directory is absent.
    """
    engine_dir = os.path.join(
        _utility_root(), "products", "cds-text-sync", "src", "cds_text_sync", "engine"
    )
    if not os.path.isdir(engine_dir):
        engine_dir = os.path.join(_utility_root(), "src", "external_engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    return engine_dir


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


def init_logging(base_dir):
    return None


_CONFIGURING_BASE_DIR = []


def _may_prompt(runtime):
    """Prompt only from an interactive command that asked to be allowed to.

    Callers that pass no runtime stay silent, which is what a background or
    mid-operation lookup needs: a modal dialog there would ambush the user.
    """
    if runtime is None or _CONFIGURING_BASE_DIR:
        return False
    try:
        return not runtime.is_headless
    except Exception:
        return False


def _configure_base_dir(runtime):
    """Offer the sync-folder dialog in place of failing the command outright.

    Returns the configured property value, or None if the user cancelled.
    """
    try:
        from codesys_directory_operation import set_base_directory
    except ImportError as error:
        log_info("Cannot offer sync-folder setup: " + str(error))
        return None

    projects_obj = resolve_projects(
        getattr(runtime, "projects", None), getattr(runtime, "caller_globals", None)
    )
    if projects_obj is None or not getattr(projects_obj, "primary", None):
        return None

    _CONFIGURING_BASE_DIR.append(True)
    try:
        result = set_base_directory(runtime, projects_obj)
    finally:
        _CONFIGURING_BASE_DIR.pop()

    if not result or result.get("status") != "ok":
        return None
    return get_project_prop("cds-sync-folder")


def load_base_dir(runtime=None):
    base_dir = get_project_prop("cds-sync-folder")
    if not base_dir and _may_prompt(runtime):
        base_dir = _configure_base_dir(runtime)
    if not base_dir:
        return None, "Project sync directory is not set. Run Project_directory.py first."

    projects_obj = resolve_projects()
    project = projects_obj.primary if projects_obj else None
    try:
        base_dir = resolve_sync_folder(base_dir, project)
    except ValueError as error:
        return None, str(error)

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    return base_dir, None


def update_application_count_flag():
    return True
