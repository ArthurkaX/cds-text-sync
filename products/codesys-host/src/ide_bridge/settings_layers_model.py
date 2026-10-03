# -*- coding: utf-8 -*-
"""
settings_layers_model.py - Decision logic behind the settings dialog.

The WinForms dialog in ``codesys_ui.py`` is a thin shell over this module: which
control is enabled, what the General and Project tabs mean, and what saving
writes are all decided here, so the rules can be unit-tested under CPython
without CLR or WinForms. Nothing in this module imports ``clr`` and nothing
touches a widget.

The dialog shows one layered view per tab:

* General edits the sparse per-user file (``defaults.json``): ``general_state``
  supplies its rows and path, ``user_values_to_overrides`` parses the controls
  back into overrides (reporting a bad value instead of dropping it silently),
  ``save_user_defaults`` writes them, and ``reset_user_rows`` fills the controls
  with the built-in defaults.
* Project edits this project's ``cds-text-sync.json``: ``project_layers`` reads
  it, ``behavior_mode`` seeds the "Same as General" / "Own for this project"
  radio, and ``assemble_project_save`` turns the form state back into the
  ``(settings, pinned)`` pair ``save_project_settings`` takes.

The settings semantics themselves stay in ``cds_text_sync.engine``; this module
only decides how they map onto a form. IronPython 2.7 compatible.
"""
from __future__ import print_function

import json


# The Project tab's behavior radio. "same" keeps the block inheriting the
# per-user values; "own" pins the whole block in the project file.
BEHAVIOR_MODE_SAME = "same"
BEHAVIOR_MODE_OWN = "own"


def _project_settings():
    from cds_text_sync.engine import _project_settings
    return _project_settings


def _user_defaults():
    from cds_text_sync.engine import _user_defaults
    return _user_defaults


def behavior_names():
    """The behavior keys, in the engine's order."""
    return list(_user_defaults().BEHAVIOR_KEYS)


def behavior_mode(settings, sources):
    """Which radio the Project tab starts on.

    ``"own"`` when the project file pins any behavior key: the project has
    already opted out of the General values, so the whole block shows as owned.
    ``"same"`` otherwise, when every key still comes from the code or user
    layer.
    """
    for name in _user_defaults().BEHAVIOR_KEYS:
        if sources.get(name) == "project":
            return BEHAVIOR_MODE_OWN
    return BEHAVIOR_MODE_SAME


def project_behavior_pins(mode):
    """The behavior keys a project save pins for *mode*.

    "own" pins every behavior key, because the tab edits the block as one unit
    (per-key pins stay possible through ``cts config set --project``). "same"
    pins none, so each key goes back to inheriting.
    """
    if mode == BEHAVIOR_MODE_OWN:
        return behavior_names()
    return []


def project_layers(project_root, user_defaults_path=None):
    """Read the layered settings for the project dialog.

    Returns the engine's ``(settings, sources, status, error)`` unchanged.
    """
    return _project_settings().read_project_settings_layers(
        project_root, warn=False, user_defaults_path=user_defaults_path
    )


def assemble_project_save(base_settings, format_values, behavior_values, mode):
    """Build the ``(settings, pinned)`` pair ``save_project_settings`` takes.

    ``mode`` is the Project tab's radio. Under "own" every behavior key is
    pinned, so the project file owns the whole block. Under "same" none is: the
    values handed in are the inherited ones (the General tab's, which the same
    save has just written to the per-user file), and the writer omits them so
    the project keeps inheriting. ``pinned`` keeps the engine's key order.
    """
    module = _user_defaults()
    settings = dict(base_settings or {})
    if format_values:
        settings.update(format_values)
    behavior_values = behavior_values or {}
    for name in module.BEHAVIOR_KEYS:
        if name in behavior_values:
            settings[name] = behavior_values[name]
    wanted = set(project_behavior_pins(mode))
    return settings, [name for name in module.BEHAVIOR_KEYS if name in wanted]


def general_state(path=None):
    """Effective per-user values for the General tab.

    Returns ``(path, rows, status, error)``. Each row is
    ``{name, class, value, overridden}`` for one key the user layer may hold:
    the format keys that seed new projects and the behavior keys projects
    inherit. ``view_root`` is not listed because it names a directory inside one
    project. The file is created on first access; a file that cannot be read
    yields the code defaults as rows plus the error, so the tab can show it and
    still let a save overwrite it.
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
    """Turn the General tab's control values into overrides.

    Values arrive as the controls hold them: booleans for checkboxes, strings
    for text boxes. The two structured keys accept either shape. Returns
    ``(overrides, "")`` or ``(None, message)`` for a value that cannot be used,
    so the tab can name the offending key instead of dropping it silently.
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
    dialog can report it and stay open.
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


def reset_user_rows():
    """Raw control values for "Reset to built-in": every key at its code default."""
    module = _user_defaults()
    defaults = _project_settings().default_project_settings()
    values = {}
    for name in module.FORMAT_KEYS + module.BEHAVIOR_KEYS:
        if name in module.PROJECT_ONLY_KEYS:
            continue
        values[name] = defaults.get(name)
    return values
