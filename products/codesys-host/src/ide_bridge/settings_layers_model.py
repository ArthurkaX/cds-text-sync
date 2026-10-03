# -*- coding: utf-8 -*-
"""
settings_layers_model.py - Decision logic behind the settings-layer dialogs.

The WinForms dialogs in ``codesys_ui.py`` are a thin shell: which control is
enabled, what a checked "Inherit" box means, and what saving writes are all
decided here, so the rules can be unit-tested under CPython without CLR or
WinForms. Nothing in this module imports ``clr`` and nothing touches a widget.

Two dialogs are served:

* The project options dialog works on the layered view of one project:
  ``project_layers`` reads it, ``behavior_rows`` says how each behavior key
  should be shown, ``format_reset_values`` supplies the "Reset to defaults"
  button, and ``assemble_project_save`` turns the form state back into the
  ``(settings, pinned)`` pair ``save_project_settings`` takes.
* The "CTS Defaults" window edits the sparse per-user file: ``user_defaults_state``
  supplies its rows, ``user_values_to_overrides`` parses the controls back into
  overrides (reporting a bad value instead of dropping it silently), and
  ``save_user_defaults`` writes them.

The settings semantics themselves stay in ``cds_text_sync.engine``; this module
only decides how they map onto a form. IronPython 2.7 compatible.
"""
from __future__ import print_function

import json


def _project_settings():
    from cds_text_sync.engine import _project_settings
    return _project_settings


def _user_defaults():
    from cds_text_sync.engine import _user_defaults
    return _user_defaults


# Text under an "Inherit" checkbox: where the inherited value comes from.
SOURCE_HINTS = {
    "user": "user default",
    "code": "built-in",
    "project": "project file",
}


def behavior_names():
    """The behavior keys, in the engine's order."""
    return list(_user_defaults().BEHAVIOR_KEYS)


def format_names():
    """The format keys a user may default, in the engine's order (no view_root)."""
    module = _user_defaults()
    return [name for name in module.FORMAT_KEYS if name not in module.PROJECT_ONLY_KEYS]


def behavior_hints():
    """Where each behavior key's inherited value comes from.

    "user default" when the per-user file overrides it, "built-in" otherwise.
    """
    module = _user_defaults()
    path = module.defaults_path()
    overrides = module.read_user_defaults(path, warn=False)[0]
    hints = {}
    for name in module.BEHAVIOR_KEYS:
        if name in overrides:
            hints[name] = SOURCE_HINTS["user"]
        else:
            hints[name] = SOURCE_HINTS["code"]
    return hints


def project_layers(project_root, user_defaults_path=None):
    """Read the layered settings for the project dialog.

    Returns the engine's ``(settings, sources, status, error)`` unchanged.
    """
    return _project_settings().read_project_settings_layers(
        project_root, warn=False, user_defaults_path=user_defaults_path
    )


def behavior_rows(settings, sources):
    """One row per behavior key, describing its project-dialog control.

    ``pinned`` is True when the project file owns the value: the control is
    editable and saving re-pins it. Otherwise the control shows the inherited
    value disabled, and ``hint`` names its origin for the checkbox label.
    """
    rows = []
    for name in _user_defaults().BEHAVIOR_KEYS:
        source = sources.get(name, "code")
        rows.append(
            {
                "name": name,
                "value": settings.get(name),
                "pinned": source == "project",
                "source": source,
                "hint": SOURCE_HINTS.get(source, source),
            }
        )
    return rows


def inherited_behavior_values():
    """The value each behavior key inherits: the user override, else the code default.

    What a behavior control must show again when the user re-checks "Inherit"
    after the project file had pinned it.
    """
    module = _user_defaults()
    defaults = _project_settings().default_project_settings()
    path = module.defaults_path()
    overrides = module.read_user_defaults(path, warn=False)[0]
    values = {}
    for name in module.BEHAVIOR_KEYS:
        if name in overrides:
            values[name] = overrides[name]
        else:
            values[name] = defaults.get(name)
    return values


def format_reset_values(user_defaults_path=None):
    """Format-control values for "Reset to defaults": code defaults + user overrides.

    ``view_root`` is project-specific, so it is left out and the reset button
    never moves the project's view root. Values that cannot be read fall back
    to the code defaults.
    """
    module = _user_defaults()
    defaults = _project_settings().default_project_settings()
    path = user_defaults_path or module.defaults_path()
    overrides = module.read_user_defaults(path, warn=False)[0]
    values = {}
    for name in module.FORMAT_KEYS:
        if name in module.PROJECT_ONLY_KEYS:
            continue
        if name in overrides:
            values[name] = overrides[name]
        else:
            values[name] = defaults.get(name)
    return values


def assemble_project_save(base_settings, format_values, behavior_values, pinned):
    """Build the ``(settings, pinned)`` pair ``save_project_settings`` takes.

    ``behavior_values`` holds one value per behavior key. A key named in
    ``pinned`` is written to the project file; an unpinned key carries the
    value it inherits, which the writer then omits so the key keeps inheriting.
    ``pinned`` keeps the engine's key order.
    """
    module = _user_defaults()
    settings = dict(base_settings or {})
    if format_values:
        settings.update(format_values)
    behavior_values = behavior_values or {}
    for name in module.BEHAVIOR_KEYS:
        if name in behavior_values:
            settings[name] = behavior_values[name]
    wanted = set(pinned or [])
    return settings, [name for name in module.BEHAVIOR_KEYS if name in wanted]


def user_defaults_state(path=None):
    """Rows for the CTS Defaults window: ``(path, rows, status, error)``.

    Creates the file on first access. A file that cannot be read yields the
    code defaults as rows plus the error, so the window can show it and still
    let a save overwrite it. ``view_root`` is not a user-default key and is not
    listed.
    """
    module = _user_defaults()
    if path is None:
        path = module.defaults_path()
    module.ensure_user_defaults(path)
    overrides, status, error = module.read_user_defaults(path, warn=False)
    defaults = _project_settings().default_project_settings()
    rows = []
    for name in module.FORMAT_KEYS + module.BEHAVIOR_KEYS:
        if name in module.PROJECT_ONLY_KEYS:
            continue
        if name in overrides:
            value = overrides[name]
        else:
            value = defaults.get(name)
        rows.append(
            {
                "name": name,
                "class": module.key_class(name),
                "value": value,
                "overridden": name in overrides,
            }
        )
    return path, rows, status, error


def _parse_projections(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_kinds(value):
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return None


def user_values_to_overrides(raw):
    """Turn the defaults window's control values into overrides.

    Values arrive as the controls hold them: booleans for checkboxes, strings
    for text boxes. The two structured keys accept either shape. Returns
    ``(overrides, "")`` or ``(None, message)`` for a value that cannot be used,
    so the window can name the offending key instead of dropping it silently.
    """
    module = _user_defaults()
    overrides = {}
    raw = raw or {}
    for name in module.FORMAT_KEYS + module.BEHAVIOR_KEYS:
        if name in module.PROJECT_ONLY_KEYS or name not in raw:
            continue
        value = raw[name]
        if name == "projections":
            value = _parse_projections(value)
            if value is None:
                return None, "projections must be a JSON object"
        elif name == "xml_in_view_kinds":
            value = _parse_kinds(value)
            if value is None:
                return None, "xml_in_view_kinds must be a list or comma-separated names"
        elif isinstance(value, str):
            value = value.strip()
        ok, normalized = module._validate(name, value)
        if not ok:
            return None, "invalid value for " + name
        overrides[name] = normalized
    return overrides, ""


def save_user_defaults(raw, path=None):
    """Validate and write the per-user overrides. Returns ``(written, error)``.

    Never raises: an unwritable file comes back as an error string so the
    window can report it and stay open.
    """
    overrides, error = user_values_to_overrides(raw)
    if error:
        return None, error
    module = _user_defaults()
    if path is None:
        path = module.defaults_path()
    try:
        return module.write_user_defaults(overrides, path=path), ""
    except Exception as exc:
        return None, str(exc)


def reset_user_rows(path=None):
    """Raw control values for "Reset all to built-in": every key at its code default."""
    module = _user_defaults()
    defaults = _project_settings().default_project_settings()
    values = {}
    for name in module.FORMAT_KEYS + module.BEHAVIOR_KEYS:
        if name in module.PROJECT_ONLY_KEYS:
            continue
        values[name] = defaults.get(name)
    return values
