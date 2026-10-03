# -*- coding: utf-8 -*-
"""
_cli_handlers_config.py - ``cts config``: inspect and edit the settings layers.

Settings are layered, from weakest to strongest:

    code defaults -> per-user defaults.json -> the project's cds-text-sync.json

``show`` reports the effective value and where each one came from; ``set`` and
``unset`` change exactly one layer. Everything here is offline: no daemon is
contacted, so this works on a machine with no CODESYS running.
"""

from __future__ import annotations

import json
import os
import sys

from cds_cli._cli_io import _print_error


def _engine():
    """The engine modules the CLI reads settings from."""
    from cds_text_sync.engine import _project_settings, _user_defaults

    return _project_settings, _user_defaults


def _resolve_project_root(explicit):
    """The sync folder to read, or None when no project file was found.

    Same rule as the other offline commands: an explicit ``--project-root``
    wins, otherwise walk up from the working directory so ``cts`` run from a
    subdirectory finds the same file as one run at the sync root.
    """
    from cds_text_sync.engine._project_settings import find_settings_root

    if explicit:
        return os.path.abspath(explicit)
    try:
        return find_settings_root(os.getcwd())
    except OSError:
        return None


def _project_path(root):
    from cds_text_sync.engine._project_settings import settings_path

    return settings_path(root if root else os.getcwd())


def _file_version(path):
    """The raw ``version`` the project file carries, or None."""
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except Exception:
        return None
    if isinstance(data, dict):
        return data.get("version")
    return None


def _cell(value):
    """One value rendered for the table, unambiguous about type."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _render_table(rows, headers):
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = [
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    ]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append(
            "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip()
        )
    return "\n".join(lines)


def _project_header(root, path, status, error, version):
    """The one line describing the project file under the table."""
    module, _user = _engine()
    if status == module.SETTINGS_MISSING:
        tail = "(missing)"
    elif status == module.SETTINGS_INVALID:
        tail = "(invalid: {0})".format(error)
    elif version == module.SETTINGS_VERSION:
        tail = "(ok, version {0})".format(version)
    else:
        shown = "version {0}".format(version) if version is not None else "no version"
        tail = "(ok, {0}, will be migrated on next save)".format(shown)
    if root is None:
        return (
            "project settings: no cds-text-sync.json found from {0} upward {1}".format(
                os.getcwd(), tail
            )
        )
    return "project settings: {0} {1}".format(path, tail)


def cmd_config_show(project_root="", as_json=False):
    """Print the effective settings and their provenance."""
    project_settings, user_defaults = _engine()
    root = _resolve_project_root(project_root)
    path = _project_path(root)

    user_path = user_defaults.defaults_path()
    user_defaults.ensure_user_defaults(user_path)
    overrides, user_status, user_error = user_defaults.read_user_defaults(
        user_path, warn=False
    )

    settings, sources, status, error = project_settings.read_project_settings_layers(
        root if root else os.getcwd(), warn=False
    )
    version = _file_version(path) if os.path.exists(path) else None

    settings_out = {}
    for name in user_defaults.USER_DEFAULT_KEYS:
        settings_out[name] = {
            "value": settings.get(name),
            "source": sources.get(name, "code"),
            "class": user_defaults.key_class(name),
        }

    if as_json:
        print(
            json.dumps(
                {
                    "user_defaults": {
                        "path": user_path,
                        "status": user_status,
                        "error": user_error,
                        "overrides": overrides,
                    },
                    "project": {
                        "path": path,
                        "status": status,
                        "error": error,
                        "version": version,
                    },
                    "settings": settings_out,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(
        "user defaults: {0} ({1})".format(
            user_path,
            user_status if user_status != "invalid" else "invalid: {0}".format(user_error),
        )
    )
    print(_project_header(root, path, status, error, version))
    print("")
    rows = [
        [
            name,
            _cell(settings_out[name]["value"]),
            settings_out[name]["source"],
            settings_out[name]["class"],
        ]
        for name in user_defaults.USER_DEFAULT_KEYS
    ]
    print(_render_table(rows, ["key", "value", "source", "class"]))


def _parse_value(text):
    """Parse a CLI value as JSON when it looks like it, else keep the string."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _unknown_key(key, user_defaults):
    _print_error(
        "Unknown setting: {0}. Valid keys: {1}".format(
            key, ", ".join(user_defaults.USER_DEFAULT_KEYS)
        )
    )
    sys.exit(1)


def _normalize_for_project(key, value, user_defaults):
    """Normalize a value for the project layer, ``(ok, normalized)``.

    ``view_root`` names a folder inside this one project, so the project layer
    takes any non-empty path string -- relative or absolute -- even though the
    user layer requires a relative one.
    """
    if key == "view_root":
        if isinstance(value, str) and value.strip():
            return True, value.strip()
        return False, None
    return user_defaults._validate(key, value)


def _load_user_overrides(user_defaults):
    path = user_defaults.defaults_path()
    user_defaults.ensure_user_defaults(path)
    return path, user_defaults.read_user_defaults(path, warn=False)[0]


def cmd_config_set(key, value_text, layer="user", project_root=""):
    """Set one setting in the user layer or the project file."""
    project_settings, user_defaults = _engine()
    if key not in user_defaults.USER_DEFAULT_KEYS:
        _unknown_key(key, user_defaults)

    value = _parse_value(value_text)

    if layer == "user":
        ok, normalized = user_defaults._validate(key, value)
        if not ok:
            _print_error("Invalid value for {0}: {1}".format(key, value_text))
            sys.exit(1)
        path, overrides = _load_user_overrides(user_defaults)
        overrides[key] = normalized
        written = user_defaults.write_user_defaults(overrides, path=path)
        if key in written:
            print(json.dumps({"layer": "user", "key": key, "value": written[key]}))
        else:
            print(
                json.dumps(
                    {
                        "layer": "user",
                        "key": key,
                        "value": None,
                        "note": "equal to the code default; no override stored",
                    }
                )
            )
        return

    root = _resolve_project_root(project_root)
    path = _project_path(root)
    if root is None or not os.path.exists(path):
        _print_error(
            "No project settings file ({0}); create the sync folder first".format(path)
        )
        sys.exit(1)
    settings, _sources, status, error = project_settings.read_project_settings_layers(
        root, warn=False
    )
    if status != project_settings.SETTINGS_OK:
        _print_error("Cannot read project settings: {0}".format(error))
        sys.exit(1)

    ok, normalized = _normalize_for_project(key, value, user_defaults)
    if not ok:
        _print_error("Invalid value for {0}: {1}".format(key, value_text))
        sys.exit(1)

    settings[key] = normalized
    pinned = [key] if key in user_defaults.BEHAVIOR_KEYS else None
    project_settings.save_project_settings(root, settings, pinned=pinned)
    print(json.dumps({"layer": "project", "key": key, "value": normalized}))


def cmd_config_unset(key, layer="user", project_root=""):
    """Remove one setting from the user layer or the project file."""
    project_settings, user_defaults = _engine()
    if key not in user_defaults.USER_DEFAULT_KEYS:
        _unknown_key(key, user_defaults)

    if layer == "user":
        path, overrides = _load_user_overrides(user_defaults)
        if key not in overrides:
            print(
                json.dumps(
                    {"layer": "user", "key": key, "removed": False, "note": "no override"}
                )
            )
            return
        del overrides[key]
        user_defaults.write_user_defaults(overrides, path=path)
        print(json.dumps({"layer": "user", "key": key, "removed": True}))
        return

    if key not in user_defaults.BEHAVIOR_KEYS:
        _print_error(
            "{0} is a format key; format keys are always explicit in the project "
            "file, so use `cts config set {0} ... --project`".format(key)
        )
        sys.exit(1)

    root = _resolve_project_root(project_root)
    path = _project_path(root)
    if root is None or not os.path.exists(path):
        _print_error(
            "No project settings file ({0}); create the sync folder first".format(path)
        )
        sys.exit(1)
    settings, sources, status, error = project_settings.read_project_settings_layers(
        root, warn=False
    )
    if status != project_settings.SETTINGS_OK:
        _print_error("Cannot read project settings: {0}".format(error))
        sys.exit(1)
    if sources.get(key) != "project":
        print(
            json.dumps(
                {
                    "layer": "project",
                    "key": key,
                    "removed": False,
                    "note": "not pinned in the project file",
                }
            )
        )
        return

    # Set the value back to what it would inherit and save without pinning it:
    # save_project_settings then omits it, so the file keeps inheriting.
    settings[key] = user_defaults.effective_user_defaults()[key]
    project_settings.save_project_settings(root, settings)
    print(json.dumps({"layer": "project", "key": key, "removed": True}))


def dispatch_config(args, output_fmt="json"):
    """Handle ``cts config <action>``. Returns True when the command was ours."""
    if getattr(args, "command", None) != "config":
        return False
    action = getattr(args, "config_action", None)
    if action == "show":
        cmd_config_show(
            project_root=getattr(args, "project_root", ""),
            as_json=getattr(args, "config_json", False),
        )
    elif action == "set":
        cmd_config_set(
            getattr(args, "key", ""),
            getattr(args, "value", ""),
            layer=getattr(args, "config_layer", "user"),
            project_root=getattr(args, "project_root", ""),
        )
    elif action == "unset":
        cmd_config_unset(
            getattr(args, "key", ""),
            layer=getattr(args, "config_layer", "user"),
            project_root=getattr(args, "project_root", ""),
        )
    else:
        _print_error("Unknown config action: {0}".format(action))
        sys.exit(1)
    return True


__all__ = [
    "cmd_config_set",
    "cmd_config_show",
    "cmd_config_unset",
    "dispatch_config",
]
