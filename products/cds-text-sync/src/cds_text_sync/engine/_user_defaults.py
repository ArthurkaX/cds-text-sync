# -*- coding: utf-8 -*-
"""
_user_defaults.py - Per-user settings overrides for cds-text-sync.

The project settings file (``_project_settings.py``) is committed and travels
with the sync folder. This module holds the personal layer that sits between
the code defaults and a project's own file: the values one user changes for
themselves, stored once per machine under the user's config directory.

The file is deliberately SPARSE. It contains only the keys whose value differs
from ``default_project_settings()``, so a key added to the code in a later
version is picked up without touching anybody's file. An empty file (or no
file at all) means "the code defaults", which is what first access generates.

Keys fall into two classes. FORMAT keys change what gets written to disk, so
they only ever SEED a new project file; BEHAVIOR keys are personal and are
inherited at runtime. ``view_root`` is a format key like the rest, and it is
the one that has to be relative here: it names a folder inside each project's
own sync root, so an absolute path would send every new project to the same
directory.

IronPython 2.7 compatible: no f-strings, no annotations, no pathlib. Reads and
writes go through ``io.open`` with an explicit UTF-8 encoding.
"""
from __future__ import print_function

import io
import json
import os

from ._project_layout import normalize_layout_mode
from ._project_settings import (
    SETTINGS_INVALID,
    SETTINGS_MISSING,
    SETTINGS_OK,
    _safe_dict,
    _safe_kind_list,
    _safe_positive_int,
    _safe_sync_mode,
    default_project_settings,
)
from cts_shared.coerce import FALSE_VALUES, TRUE_VALUES


DEFAULTS_DIRNAME = "cds-text-sync"
DEFAULTS_FILENAME = "defaults.json"

# Bumped only if the on-disk shape has to change; the sparse format itself
# needs no migration, because a missing key simply keeps the code default.
DEFAULTS_VERSION = 1

# Keys that affect what is written to disk. They later only seed a new
# project file, so changing one does not rewrite existing projects.
FORMAT_KEYS = (
    "layout",
    "view_root",
    "profile",
    "projections",
    "sync_mode",
    "xml_in_view_kinds",
)

# Personal keys, inherited at runtime onto the effective project settings.
BEHAVIOR_KEYS = (
    "verbose_logging",
    "advanced_debug",
    "show_completion_popup",
    "pre_import_backup_enabled",
    "backup_retention_count",
)

USER_DEFAULT_KEYS = FORMAT_KEYS + BEHAVIOR_KEYS


def key_class(name):
    """Classify a setting name as ``"format"`` or ``"behavior"``.

    Anything unrecognised is treated as format, the conservative choice: an
    unknown key is assumed to influence stored files and must not be silently
    inherited across projects.
    """
    if name in BEHAVIOR_KEYS:
        return "behavior"
    return "format"


def _is_windows():
    return os.name == "nt"


def defaults_path():
    """Path of the per-user defaults file.

    Windows uses ``%APPDATA%\\cds-text-sync\\defaults.json``; elsewhere the
    XDG config directory (or ``~/.config``) is used.
    """
    if _is_windows():
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, DEFAULTS_DIRNAME, DEFAULTS_FILENAME)


def _valid_bool(value):
    if isinstance(value, bool):
        return True, value
    if value is None:
        return False, None
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True, True
    if text in FALSE_VALUES:
        return True, False
    return False, None


def _valid_positive_int(value):
    result = _safe_positive_int(value, None)
    if result is None:
        return False, None
    return True, result


def _valid_layout(value):
    text = str(value or "").strip()
    if not text:
        return False, None
    try:
        return True, normalize_layout_mode(text)
    except Exception:
        return False, None


def _valid_profile(value):
    text = str(value or "").strip()
    if not text:
        return False, None
    return True, text


def _valid_view_root(value):
    """A user-layer view root: relative, inside each project's own sync folder.

    ``None`` is the code default -- no custom root -- and is accepted so that
    turning the choice off round-trips. Anything absolute is refused: a shared
    path in the per-user file would point every new project at one directory.
    ``..`` is refused as well, because it would escape the project. The value
    is normalized to forward slashes so a backslash-typed path still works.
    """
    if value is None:
        return True, None
    text = str(value).strip()
    if not text:
        return False, None
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or os.path.isabs(text):
        return False, None
    if len(normalized) > 1 and normalized[1] == ":":
        return False, None
    parts = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return False, None
        parts.append(part)
    if not parts:
        return False, None
    return True, "/".join(parts)


def _valid_dict(value):
    if not isinstance(value, dict):
        return False, None
    return True, _safe_dict(value)


def _valid_sync_mode(value):
    # ``_safe_sync_mode(value, None)`` returns None for anything it cannot
    # recognize, which is exactly the "invalid" signal this layer needs.
    result = _safe_sync_mode(value, None)
    if result is None:
        return False, None
    return True, result


def _valid_kind_list(value):
    if not isinstance(value, (list, tuple)):
        return False, None
    default = default_project_settings()["xml_in_view_kinds"]
    return True, _safe_kind_list(value, default)


# One validator per key: decides whether a stored value is usable and returns
# it normalized the same way the project loader would have.
_VALIDATORS = {
    "layout": _valid_layout,
    "view_root": _valid_view_root,
    "profile": _valid_profile,
    "projections": _valid_dict,
    "sync_mode": _valid_sync_mode,
    "xml_in_view_kinds": _valid_kind_list,
    "verbose_logging": _valid_bool,
    "advanced_debug": _valid_bool,
    "show_completion_popup": _valid_bool,
    "pre_import_backup_enabled": _valid_bool,
    "backup_retention_count": _valid_positive_int,
}


def _validate(name, value):
    """Return ``(ok, normalized)`` for one known key."""
    validator = _VALIDATORS.get(name)
    if validator is None:
        return False, None
    return validator(value)


def _warn(message, warn):
    if warn:
        print("Warning: " + message)


def read_user_defaults(path=None, warn=True):
    """Read the per-user overrides and say whether the file was usable.

    Returns ``(overrides, status, error)`` using the same vocabulary as
    ``read_project_settings``: ``SETTINGS_MISSING`` (no file: no overrides,
    not an error), ``SETTINGS_OK`` or ``SETTINGS_INVALID`` (unreadable or not
    a JSON object, in which case the overrides are empty and the caller falls
    back to the code defaults).

    ``overrides`` is sparse: only known keys survive, each normalized by the
    same helper the project loader uses. A value that does not validate is
    dropped with a warning; unknown keys are ignored silently; a ``view_root``
    that is not a relative path is refused; ``version`` is metadata, not an
    override.
    """
    if path is None:
        path = defaults_path()
    overrides = {}
    if not os.path.exists(path):
        return overrides, SETTINGS_MISSING, ""

    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as error:
        message = "Could not read user defaults {0}: {1}".format(path, error)
        _warn(message, warn)
        return overrides, SETTINGS_INVALID, message

    if not isinstance(data, dict):
        message = (
            "Ignoring user defaults because root JSON value is not an "
            "object: {0}".format(path)
        )
        _warn(message, warn)
        return overrides, SETTINGS_INVALID, message

    for name in USER_DEFAULT_KEYS:
        if name not in data:
            continue
        ok, value = _validate(name, data[name])
        if ok:
            overrides[name] = value
        else:
            _warn(
                "Ignoring invalid {0} in user defaults {1}".format(name, path),
                warn,
            )
    return overrides, SETTINGS_OK, ""


def write_user_defaults(overrides, path=None):
    """Write the sparse overrides file, keeping only values that differ.

    Every key is validated and normalized; anything invalid is dropped, and a
    value equal to the code default is omitted so the file stays small and a
    future default change is not overridden by an unchanged copy. The
    directory is created when needed. Returns the dict that was written.
    """
    if path is None:
        path = defaults_path()
    defaults = default_project_settings()
    source = _safe_dict(overrides)

    data = {"version": DEFAULTS_VERSION}
    for name in USER_DEFAULT_KEYS:
        if name not in source:
            continue
        ok, value = _validate(name, source[name])
        if ok and value != defaults.get(name):
            data[name] = value

    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, sort_keys=True))
        handle.write(u"\n")
    return data


def ensure_user_defaults(path=None):
    """Create an empty overrides file on first access.

    Returns True when the file exists afterwards. A directory that cannot be
    written (read-only home, missing drive) is not an error here: the caller
    still gets the code defaults, so only False is reported.
    """
    if path is None:
        path = defaults_path()
    if os.path.exists(path):
        return True
    try:
        write_user_defaults({}, path=path)
        return True
    except Exception:
        return False


def effective_user_defaults(path=None):
    """Code defaults updated with the per-user overrides.

    Ensures the file exists first, so reading always reports what the user
    would get. An invalid file warns and yields the code defaults alone.
    """
    if path is None:
        path = defaults_path()
    ensure_user_defaults(path)
    overrides = read_user_defaults(path)[0]
    settings = default_project_settings()
    settings.update(overrides)
    return settings
