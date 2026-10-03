# -*- coding: utf-8 -*-
"""
_project_settings.py - Project settings loader and writer.

The settings file is intentionally tracked and non-dot-prefixed so it can live
next to root-view project files without being treated as generated state.

Values are layered, from weakest to strongest:

    code defaults -> per-user overrides (``defaults.json``) -> project file

BEHAVIOR keys inherit: an effective value is the project's own when the file
pins it, otherwise the user's override, otherwise the code default. FORMAT
keys describe what gets written to disk, so they are only ever inherited into
a project that has no settings file yet (that is the file it would be seeded
with); once the file exists its own value or the code default wins. A
``view_root`` in the user layer is relative to each project's sync folder, so
seeding one resolves it against that project's own root.
"""
from __future__ import print_function
import json
import os

from ._project_layout import LAYOUT_PROJECT_VIEW, normalize_layout_mode
from cts_shared.coerce import as_bool


SETTINGS_FILENAME = "cds-text-sync.json"

# Current on-disk shape. Version 2 pins a behavior key whenever it is present;
# version 1 (or no version) is migrated on read: a behavior value equal to the
# code default counts as "not pinned" so it starts inheriting the user layer.
SETTINGS_VERSION = 2

# Outcome of reading the settings file. Both a missing file and an unreadable
# one yield the defaults, so a caller that must not act on a guess has to be
# able to tell them apart: only the second is a problem worth reporting.
SETTINGS_MISSING = "missing"
SETTINGS_OK = "ok"
SETTINGS_INVALID = "invalid"

SYNC_MODE_XML_FIRST = "xml_first"
SYNC_MODE_TEXT_FIRST = "text_first"


def default_project_settings():
    return {
        "version": SETTINGS_VERSION,
        "layout": LAYOUT_PROJECT_VIEW,
        "view_root": None,
        "profile": "default",
        "projections": {},
        "sync_mode": SYNC_MODE_XML_FIRST,
        "xml_in_view_kinds": ["visu"],
        "verbose_logging": False,
        "advanced_debug": False,
        "show_completion_popup": True,
        "pre_import_backup_enabled": True,
        "backup_retention_count": 10,
    }


def settings_path(project_root):
    return os.path.join(project_root, SETTINGS_FILENAME)


def find_settings_root(start_dir=None):
    """Return the nearest directory at or above *start_dir* holding the file.

    This is the one file-search rule for every reader. The settings file lives
    at the root of the sync folder, and a caller that only knows where it is
    standing finds it by walking up: a command run from a subdirectory reads
    the same file as one run from the root, and one run outside any sync folder
    reads nothing rather than a stranger's file further up.

    Only the search uses this. ``load_project_settings`` keeps taking the root
    it is handed, because the engine is told which project it is working on and
    must not silently drift to a different one.

    Returns an absolute path, or None when no ancestor holds the file.
    """
    try:
        current = os.path.abspath(start_dir or os.getcwd())
    except OSError:
        return None
    while True:
        if os.path.exists(os.path.join(current, SETTINGS_FILENAME)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_bool(value, default=False):
    return as_bool(value, default)


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


def _stored_view_root(project_root, value):
    """The form of ``view_root`` written to the project file.

    The file is tracked in git, so a root inside the sync folder is stored
    relative to it (forward slashes); only a root outside it stays absolute.
    """
    if not value:
        return None
    full = _normalize_view_root(project_root, value)
    base = os.path.abspath(os.path.normpath(project_root))
    try:
        relative = os.path.relpath(full, base)
    except ValueError:
        # Another drive on Windows.
        return full
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return full
    return relative.replace(os.sep, "/")


def _safe_sync_mode(value, default=SYNC_MODE_XML_FIRST):
    if value is None:
        return default
    text = str(value).strip().lower().replace("-", "_")
    if text in (SYNC_MODE_TEXT_FIRST, "text", "textfirst"):
        return SYNC_MODE_TEXT_FIRST
    if text in (SYNC_MODE_XML_FIRST, "xml", "xmlfirst"):
        return SYNC_MODE_XML_FIRST
    return default


def normalize_sync_mode(value, default=SYNC_MODE_XML_FIRST):
    """Public alias used by the options workflow and the engine."""
    return _safe_sync_mode(value, default)


def _safe_kind_list(value, default):
    if value is None:
        return list(default)
    if not isinstance(value, (list, tuple)):
        return list(default)
    result = []
    for item in value:
        text = str(item or "").strip().lower()
        if text and text not in result:
            result.append(text)
    return result


def _user_defaults_module():
    """Import ``_user_defaults`` lazily.

    The two modules cross-reference each other (the user layer validates with
    this module's normalize helpers), so this side imports at call time to keep
    the package importable in either order.
    """
    from . import _user_defaults
    return _user_defaults


def _load_user_overrides(user_defaults_path, warn):
    """Read the per-user overrides, creating the file on first access.

    Never raises and never affects a project read's status: an unusable or
    unwritable defaults file only warns and yields no overrides, so the code
    defaults still stand.
    """
    module = _user_defaults_module()
    if user_defaults_path is None:
        user_defaults_path = module.defaults_path()
    try:
        module.ensure_user_defaults(user_defaults_path)
        return module.read_user_defaults(user_defaults_path, warn=warn)[0]
    except Exception as error:
        if warn:
            print("Warning: Ignoring user defaults: {0}".format(error))
        return {}


def _project_file_values(project_root, data, warn, path):
    """Normalize the project file into ``{key: value}`` for keys it sets.

    Only keys the file actually carries appear, so the caller can tell a
    pinned value from an inherited one. Values are coerced exactly as the old
    flat reader did, including the "ignore an invalid layout" warning.
    """
    module = _user_defaults_module()
    values = {}
    if "layout" in data:
        try:
            values["layout"] = normalize_layout_mode(data.get("layout"))
        except Exception as error:
            if warn:
                print("Warning: Ignoring invalid layout in project settings {0}: {1}".format(path, error))
    view_root = _normalize_view_root(project_root, data.get("view_root"))
    if view_root is not None:
        values["view_root"] = view_root
    if data.get("profile"):
        values["profile"] = str(data.get("profile"))
    if isinstance(data.get("projections"), dict):
        values["projections"] = _safe_dict(data.get("projections"))
    if data.get("sync_mode") is not None:
        values["sync_mode"] = _safe_sync_mode(data.get("sync_mode"))
    if isinstance(data.get("xml_in_view_kinds"), (list, tuple)):
        values["xml_in_view_kinds"] = _safe_kind_list(
            data.get("xml_in_view_kinds"),
            default_project_settings()["xml_in_view_kinds"],
        )
    for name in module.BEHAVIOR_KEYS:
        if name in data:
            ok, value = module._validate(name, data[name])
            if ok:
                values[name] = value
    return values


def _merge_layers(settings, sources, values, version, overrides, module):
    """Apply the project file on top of the code defaults and user overrides.

    FORMAT keys from the file win outright; BEHAVIOR keys win only when the
    file pins them (present under version 2, or different from the code
    default under the legacy version 1), otherwise the user override and then
    the code default take over.
    """
    defaults = default_project_settings()
    pinned_file = version == SETTINGS_VERSION
    for name in module.USER_DEFAULT_KEYS:
        present = name in values
        if name in module.BEHAVIOR_KEYS:
            pinned = present and (pinned_file or values[name] != defaults[name])
            if pinned:
                settings[name] = values[name]
                sources[name] = "project"
            elif name in overrides:
                settings[name] = overrides[name]
                sources[name] = "user"
            continue
        if present:
            settings[name] = values[name]
            sources[name] = "project"


def read_project_settings_layers(project_root, warn=True, user_defaults_path=None):
    """Read project settings and report where each value came from.

    Returns ``(settings, sources, status, error)``. ``sources`` maps every
    settings key to ``"code"``, ``"user"`` or ``"project"``, which is what
    ``cts config show`` and the options UI need to explain an inherited value.

    The status vocabulary is ``read_project_settings``': ``SETTINGS_MISSING``
    (no project file: format keys are seeded from the user overrides, which is
    what a first save would write), ``SETTINGS_OK`` or ``SETTINGS_INVALID``
    (present but unreadable or not a JSON object, in which case the returned
    settings are the code defaults alone).

    Reading may create the empty per-user file (its "generated on first
    access" contract), but a broken or unwritable one only warns and falls
    back to the code defaults; it never changes the project's own status.
    """
    settings = default_project_settings()
    sources = {}
    for name in settings:
        sources[name] = "code"

    module = _user_defaults_module()
    overrides = _load_user_overrides(user_defaults_path, warn)

    path = settings_path(project_root)
    if not os.path.exists(path):
        for name in module.USER_DEFAULT_KEYS:
            if name in overrides:
                value = overrides[name]
                if name == "view_root":
                    # The user layer holds a path relative to each project's
                    # sync folder, so it is resolved here, exactly as a relative
                    # value in a project file would be.
                    value = _normalize_view_root(project_root, value)
                settings[name] = value
                sources[name] = "user"
        return settings, sources, SETTINGS_MISSING, ""

    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except Exception as error:
        message = "Could not read project settings {0}: {1}".format(path, error)
        if warn:
            print("Warning: " + message)
        return settings, sources, SETTINGS_INVALID, message

    if not isinstance(data, dict):
        message = (
            "Ignoring project settings because root JSON value is not an "
            "object: {0}".format(path)
        )
        if warn:
            print("Warning: " + message)
        return settings, sources, SETTINGS_INVALID, message

    values = _project_file_values(project_root, data, warn, path)
    _merge_layers(settings, sources, values, data.get("version"), overrides, module)
    return settings, sources, SETTINGS_OK, ""


def read_project_settings(project_root, warn=True, user_defaults_path=None):
    """Read the layered settings and say whether the project file was usable.

    Returns ``(settings, status, error)`` exactly as before; see
    ``read_project_settings_layers`` for the provenance of each value.
    """
    settings, _sources, status, error = read_project_settings_layers(
        project_root, warn=warn, user_defaults_path=user_defaults_path
    )
    return settings, status, error


def load_project_settings(project_root, user_defaults_path=None):
    """Load project settings, warning about a file that cannot be used.

    The tolerant spelling for callers that only want the values: a missing or
    broken file yields the defaults. Use ``read_project_settings`` when the
    caller has to know that the file was broken.
    """
    return read_project_settings(project_root, user_defaults_path=user_defaults_path)[0]


def _inherited_behavior_value(name, overrides, defaults):
    """The value a behavior key gets when the project file does not pin it."""
    if name in overrides:
        return overrides[name]
    return defaults[name]


def save_project_settings(project_root, settings, pinned=None):
    """Write the project file, keeping the user layer out of the way.

    Format keys are always written explicitly. A behavior key is written only
    when it is named in ``pinned`` or its value differs from what it would
    otherwise inherit (the per-user override, else the code default) - so a
    legacy caller that passes no ``pinned`` keeps only real differences and
    keeps inheriting. A value equal to the inherited one therefore cannot be
    pinned without ``pinned``; the options UI will pass it when it needs to.

    Returns the full effective settings dict, as before, even though the file
    may omit inherited behavior keys.
    """
    current = default_project_settings()
    data = _safe_dict(settings)
    module = _user_defaults_module()
    defaults = default_project_settings()
    try:
        overrides = module.read_user_defaults(None, warn=False)[0]
    except Exception:
        overrides = {}
    pinned_names = set(pinned or ())

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
    current["sync_mode"] = _safe_sync_mode(
        data.get("sync_mode"),
        current["sync_mode"],
    )
    current["xml_in_view_kinds"] = _safe_kind_list(
        data.get("xml_in_view_kinds"),
        current["xml_in_view_kinds"],
    )
    current["verbose_logging"] = _safe_bool(
        data.get("verbose_logging"),
        current["verbose_logging"],
    )
    current["advanced_debug"] = _safe_bool(
        data.get("advanced_debug"),
        current["advanced_debug"],
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

    written = {
        "version": SETTINGS_VERSION,
        "layout": current["layout"],
        "view_root": _stored_view_root(project_root, current["view_root"]),
        "profile": current["profile"],
        "projections": current["projections"],
        "sync_mode": current["sync_mode"],
        "xml_in_view_kinds": current["xml_in_view_kinds"],
    }
    for name in module.BEHAVIOR_KEYS:
        inherited = _inherited_behavior_value(name, overrides, defaults)
        if name in pinned_names or current[name] != inherited:
            written[name] = current[name]

    path = settings_path(project_root)
    with open(path, "w") as handle:
        json.dump(written, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return current
