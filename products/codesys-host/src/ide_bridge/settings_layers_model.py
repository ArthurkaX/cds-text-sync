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


def _project_profiles():
    from cds_text_sync.engine import _project_profiles
    return _project_profiles


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


def projection_enabled(projections, projection):
    """Whether *projection* is on in a ``projections`` mapping.

    This delegates to the engine's
    ``_project_profiles.projection_enabled``, the one rule the pipeline uses:
    an explicit entry for the projection's id or kind wins -- a dict whose
    ``enabled`` is false turns it off, any other truthy value turns it on --
    and a projection no entry mentions follows the profile's
    ``default_enabled``. Both tabs show this answer, so a box matches what a
    new project gets.
    """
    return _project_profiles().projection_enabled(projection, projections)


def general_kind_initial(original, available):
    """Which of *available* the General tab shows checked for xml_in_view_kinds.

    Strictly the effective General value: a kind the profile offers but the
    user layer does not list is shown unchecked, so leaving it alone writes
    nothing.
    """
    listed = set(str(item).strip().lower() for item in (original or []))
    checked = []
    for kind in (available or []):
        name = str(kind).strip().lower()
        if name in listed and name not in checked:
            checked.append(name)
    return checked


def general_projection_initial(original, options):
    """The projection ids the General tab shows checked.

    Each box starts at the engine's effective answer for the General value,
    ``default_enabled`` included, so what the tab shows is what a new project
    gets. A box the user never moves is therefore not an edit.
    """
    checked = []
    for projection in (options or []):
        projection_id = projection.get("id") or projection.get("kind")
        if projection_id and projection_enabled(original, projection):
            checked.append(projection_id)
    return checked


def merge_general_values(originals, initials, current):
    """The General values to store: *originals* plus only the controls edited.

    A control whose value still equals the value it was shown with is
    untouched, so the effective value is kept as-is. Those effective values are
    exactly what a sparse write round-trips, so an untouched tab leaves the
    per-user file unchanged.
    """
    result = dict(originals or {})
    for name, value in (current or {}).items():
        if initials.get(name) != value:
            result[name] = value
    return result


def merge_general_kinds(original, turned_on, turned_off):
    """xml_in_view_kinds after the General checkboxes were toggled.

    *turned_on* and *turned_off* hold only the options the current profile
    offers and the user actually moved. Every other item of *original* is kept
    -- including one the profile does not offer -- so an empty toggle set
    returns *original* unchanged.
    """
    dropped = set(turned_off or [])
    result = [item for item in (original or []) if item not in dropped]
    for item in (turned_on or []):
        if item not in result:
            result.append(item)
    return result


def merge_general_projections(original, turned_on, turned_off):
    """projections after the General checkboxes were toggled.

    *turned_on* maps a projection key to the entry to store, *turned_off* names
    keys to drop, and every key not named keeps its effective value exactly --
    including a projection the current profile does not offer, and a stored
    ``true`` that must not be rewritten as an object. An empty toggle set
    therefore returns *original* unchanged.
    """
    result = dict(original or {})
    for key in (turned_off or []):
        result.pop(key, None)
    for key, entry in (turned_on or {}).items():
        result[key] = entry
    return result


def general_values_to_store(originals, initials, current, options,
                            projection_entries):
    """Assemble the General values to write from the tab's control state.

    *originals* is the effective General value the tab opened with, *initials*
    the control state it was built with, *current* the same shape read back at
    save: the scalar controls plus ``kinds_checked`` and ``projections_checked``
    (the offered options whose boxes are on). *options* are the project profile's
    projection descriptors and *projection_entries* describes every offered
    projection -- the entry to store, with ``enabled`` already set to the state
    of its box -- so a projection the user switched off can be written as an
    explicit ``{"enabled": false, ...}``.

    Only the controls that differ from *initials* are applied, and a list key
    keeps everything the profile cannot offer, so an untouched tab returns
    *originals* unchanged -- and since those values are what a sparse write
    round-trips, saving them leaves the per-user file as it was.
    """
    values = merge_general_values(originals, initials, current)

    initial_kinds = list(initials.get("kinds_checked") or [])
    current_kinds = list(current.get("kinds_checked") or [])
    initial_kind_set = set(initial_kinds)
    current_kind_set = set(current_kinds)
    values["xml_in_view_kinds"] = merge_general_kinds(
        originals.get("xml_in_view_kinds"),
        [kind for kind in current_kinds if kind not in initial_kind_set],
        [kind for kind in initial_kinds if kind not in current_kind_set],
    )

    initial_projections = set(initials.get("projections_checked") or [])
    current_projections = set(current.get("projections_checked") or [])
    turned_on = {}
    turned_off = []
    for projection in (options or []):
        projection_id = projection.get("id") or projection.get("kind")
        if not projection_id:
            continue
        if (projection_id in current_projections) == (
                projection_id in initial_projections):
            continue
        keys = []
        for key in (projection.get("id"), projection.get("kind")):
            if key and key not in keys:
                keys.append(key)
        state = projection_id in current_projections
        if state == bool(projection.get("default_enabled")):
            # The box is back at the profile's own answer, so no explicit entry
            # is needed: the projection follows the profile again.
            turned_off.extend(keys)
        else:
            entry = dict((projection_entries or {}).get(projection_id) or {})
            entry["enabled"] = state
            turned_on[projection_id] = entry
            for key in keys:
                if key != projection_id:
                    turned_off.append(key)
    values["projections"] = merge_general_projections(
        originals.get("projections"), turned_on, turned_off)
    return values


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
