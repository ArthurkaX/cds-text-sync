# -*- coding: utf-8 -*-
"""
test_settings_layers_model.py - Decision logic behind the settings dialog.

The WinForms dialog is a thin shell over ``settings_layers_model``; these pin
the rules that shell depends on: which radio the Project tab starts on, what
"Same as General" writes (nothing) versus "Own for this project" (the whole
behavior block), how the General tab's controls turn into per-user overrides,
and what a first access or a broken file does to the rows it shows.
"""

import io
import json
import os
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"
if str(_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_BRIDGE))

import settings_layers_model as model

from cds_text_sync.engine import _project_profiles, _project_settings, _user_defaults


def _write_project(root, data):
    with io.open(_project_settings.settings_path(str(root)), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data))


def _read_project(root):
    with io.open(_project_settings.settings_path(str(root)), encoding="utf-8") as handle:
        return json.load(handle)


def _write_user(overrides, path):
    _user_defaults.write_user_defaults(overrides, path=path)


def _behavior_values(settings):
    return dict((name, settings[name]) for name in model.behavior_names())


def _general_behavior_values():
    """What the General tab's behavior controls hold for every behavior key."""
    _path, rows, _status, _error = model.general_state()
    values = dict((row["name"], row["value"]) for row in rows)
    return dict((name, values[name]) for name in model.behavior_names())


class TestBehaviorMode:
    def test_fresh_project_starts_on_same(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})

        settings, sources, _status, _error = model.project_layers(str(root))

        assert model.behavior_mode(settings, sources) == "same"

    def test_a_user_override_alone_is_still_same(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})
        _write_user({"advanced_debug": True}, _user_defaults.defaults_path())

        settings, sources, _status, _error = model.project_layers(str(root))

        assert sources["advanced_debug"] == "user"
        assert model.behavior_mode(settings, sources) == "same"

    def test_a_project_pin_selects_own(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2, "advanced_debug": True})

        settings, sources, _status, _error = model.project_layers(str(root))

        assert model.behavior_mode(settings, sources) == "own"

    def test_pins_follow_the_mode(self):
        assert model.project_behavior_pins("same") == []
        assert model.project_behavior_pins("own") == list(_user_defaults.BEHAVIOR_KEYS)


class TestAssembleProjectSave:
    def test_own_pins_every_behavior_key_in_engine_order(self):
        _settings, pinned = model.assemble_project_save(
            {}, {}, {"verbose_logging": True}, "own"
        )
        assert pinned == list(_user_defaults.BEHAVIOR_KEYS)

    def test_same_pins_nothing_and_writes_no_behavior_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2, "verbose_logging": True})

        settings, _sources, _status, _error = model.project_layers(str(root))
        # Under "Same as General" the controls mirror the General tab, so the
        # dialog hands back the per-user values, not the project's own pin.
        settings, pinned = model.assemble_project_save(
            settings, {}, _general_behavior_values(), "same"
        )
        assert pinned == []
        _project_settings.save_project_settings(str(root), settings, pinned=pinned)

        on_disk = _read_project(root)
        for name in model.behavior_names():
            assert name not in on_disk

    def test_own_writes_every_behavior_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})

        settings, _sources, _status, _error = model.project_layers(str(root))
        values = _behavior_values(settings)
        values["verbose_logging"] = True
        settings, pinned = model.assemble_project_save(settings, {}, values, "own")
        _project_settings.save_project_settings(str(root), settings, pinned=pinned)

        on_disk = _read_project(root)
        for name in model.behavior_names():
            assert name in on_disk
        assert on_disk["verbose_logging"] is True
        assert on_disk["advanced_debug"] is False

    def test_format_values_reach_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        settings, pinned = model.assemble_project_save(
            {}, {"sync_mode": "text_first"}, {}, "same"
        )
        _project_settings.save_project_settings(str(root), settings, pinned=pinned)

        assert _read_project(root)["sync_mode"] == "text_first"


class TestProjectDialogRoundTrip:
    def test_same_keeps_inheriting_the_general_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})
        user = _user_defaults.defaults_path()

        # General tab: turn advanced_debug on for every project.
        written, error = model.save_user_defaults(
            {
                "advanced_debug": True,
                "layout": "project-view",
                "profile": "default",
                "sync_mode": "xml_first",
                "projections": {},
                "xml_in_view_kinds": ["visu"],
            },
            user,
        )
        assert error == ""
        assert written["advanced_debug"] is True

        # Project tab: "Same as General" shows that value and stores nothing.
        settings, sources, _status, _error = model.project_layers(str(root))
        assert model.behavior_mode(settings, sources) == "same"
        settings, pinned = model.assemble_project_save(
            settings, {}, _general_behavior_values(), "same"
        )
        _project_settings.save_project_settings(str(root), settings, pinned=pinned)

        reloaded, reloaded_sources, _status, _error = model.project_layers(str(root))
        assert reloaded["advanced_debug"] is True
        assert reloaded_sources["advanced_debug"] == "user"
        assert model.behavior_mode(reloaded, reloaded_sources) == "same"

    def test_own_survives_a_reload_as_pinned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})
        _write_user({"advanced_debug": True}, _user_defaults.defaults_path())

        settings, sources, _status, _error = model.project_layers(str(root))
        assert model.behavior_mode(settings, sources) == "same"
        values = _behavior_values(settings)
        values["verbose_logging"] = True

        # Switching Same -> Own keeps the shown values as the starting point.
        settings, pinned = model.assemble_project_save(settings, {}, values, "own")
        _project_settings.save_project_settings(str(root), settings, pinned=pinned)

        reloaded, reloaded_sources, _status, _error = model.project_layers(str(root))
        assert model.behavior_mode(reloaded, reloaded_sources) == "own"
        assert reloaded["verbose_logging"] is True
        assert reloaded["advanced_debug"] is True  # kept the shown value, pinned


class TestGeneralState:
    def test_rows_show_effective_values_and_create_the_file(self, tmp_path):
        path = str(tmp_path / "config" / "cds-text-sync" / "defaults.json")

        returned_path, rows, status, error = model.general_state(path)

        assert returned_path == path
        assert os.path.exists(path)
        assert status == _project_settings.SETTINGS_OK
        assert error == ""
        names = [row["name"] for row in rows]
        assert set(names) == set(_user_defaults.USER_DEFAULT_KEYS)
        by_name = dict((row["name"], row) for row in rows)
        defaults = _project_settings.default_project_settings()
        assert by_name["view_root"]["value"] is None
        assert by_name["view_root"]["class"] == "format"
        assert by_name["sync_mode"]["value"] == defaults["sync_mode"]
        assert by_name["sync_mode"]["class"] == "format"
        assert by_name["advanced_debug"]["class"] == "behavior"
        assert by_name["advanced_debug"]["overridden"] is False

    def test_overridden_flag_tracks_the_file(self, tmp_path):
        path = str(tmp_path / "config" / "defaults.json")
        _write_user({"advanced_debug": True}, path)

        _returned, rows, _status, _error = model.general_state(path)
        by_name = dict((row["name"], row) for row in rows)

        assert by_name["advanced_debug"]["overridden"] is True
        assert by_name["advanced_debug"]["value"] is True

    def test_broken_file_reports_the_error_and_defaults(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

        _returned, rows, status, error = model.general_state(str(path))

        assert status == _project_settings.SETTINGS_INVALID
        assert error
        by_name = dict((row["name"], row) for row in rows)
        assert by_name["advanced_debug"]["value"] is False

    def test_reset_rows_are_the_code_defaults(self):
        values = model.reset_user_rows()
        defaults = _project_settings.default_project_settings()

        assert values["view_root"] is None
        for name, value in values.items():
            assert value == defaults[name]


class TestGeneralEdits:
    """Save on an untouched General tab must not change the per-user file.

    The tab is built from the current project's profile options, which need not
    cover what the user layer holds; only a box the user actually moved may
    change the stored value.
    """

    PROJECTIONS = [
        {"id": "st_views", "kind": "st_views", "label": "ST views", "format": "st"},
        {"id": "visu_views", "kind": "visu", "label": "Visu", "format": "xml"},
    ]

    def _state(self, originals, options, kinds):
        """The control state the form starts with, from the effective values."""
        state = dict((name, originals.get(name)) for name in (
            "layout", "profile", "sync_mode", "pre_import_backup_enabled",
            "backup_retention_count", "verbose_logging", "advanced_debug",
            "show_completion_popup",
        ))
        state["kinds_checked"] = model.general_kind_initial(
            originals.get("xml_in_view_kinds"), kinds)
        state["projections_checked"] = model.general_projection_initial(
            originals.get("projections"), options)
        return state

    def _entries(self, options, checked):
        """What the form hands the model: an entry per offered projection.

        The dialog describes every box, checked or not, because unchecking one
        the profile enables by default has to be written as ``enabled: false``.
        """
        entries = {}
        for projection in options:
            projection_id = projection.get("id") or projection.get("kind")
            entries[projection_id] = {
                "enabled": projection_id in checked,
                "kind": projection.get("kind"),
                "format": projection.get("format"),
                "import_safe": False,
            }
        return entries

    def test_untouched_tab_rewrites_the_same_file(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user(
            {"advanced_debug": True, "xml_in_view_kinds": ["visu", "custom"]}, str(path)
        )
        before = path.read_bytes()

        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        initials = self._state(originals, self.PROJECTIONS, ["visu"])
        values = model.general_values_to_store(
            originals, initials, self._state(originals, self.PROJECTIONS, ["visu"]),
            self.PROJECTIONS, self._entries(self.PROJECTIONS, []),
        )
        written, error = model.save_user_defaults(values, str(path))

        assert error == ""
        assert path.read_bytes() == before
        assert written["advanced_debug"] is True
        assert written["xml_in_view_kinds"] == ["visu", "custom"]

    def test_view_root_round_trips_and_turning_it_off_clears_it(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user({"view_root": "views"}, str(path))

        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        assert originals["view_root"] == "views"
        before = path.read_bytes()

        # Untouched: the same value comes back and the file does not change.
        values = model.general_values_to_store(
            originals, dict(originals), dict(originals), [], {}
        )
        written, error = model.save_user_defaults(values, str(path))
        assert error == ""
        assert written["view_root"] == "views"
        assert path.read_bytes() == before

        # Switching it off stores no root at all, so the override is dropped.
        cleared = dict(originals)
        cleared["view_root"] = None
        values = model.general_values_to_store(
            originals, dict(originals), cleared, [], {}
        )
        written, error = model.save_user_defaults(values, str(path))
        assert error == ""
        assert "view_root" not in written

    def test_a_profile_without_the_default_kind_writes_nothing(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user({}, str(path))
        before = path.read_bytes()

        # The profile offers no view kinds at all, so the tab has no boxes;
        # the effective ["visu"] must not be turned into [] by a save.
        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        assert originals["xml_in_view_kinds"] == ["visu"]
        initials = self._state(originals, [], [])
        assert initials["kinds_checked"] == []
        values = model.general_values_to_store(
            originals, initials, self._state(originals, [], []), [], {})

        assert values["xml_in_view_kinds"] == ["visu"]
        written, error = model.save_user_defaults(values, str(path))
        assert error == ""
        assert path.read_bytes() == before
        assert "xml_in_view_kinds" not in written

    def test_a_default_enabled_projection_is_not_an_override(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user({}, str(path))
        before = path.read_bytes()
        options = [
            {"id": "st_views", "kind": "st_views", "label": "ST views",
             "default_enabled": True},
        ]

        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        initials = self._state(originals, options, [])
        # The box shows the profile's own answer, so an untouched tab is still
        # not an edit: nothing is written for it.
        assert initials["projections_checked"] == ["st_views"]
        values = model.general_values_to_store(
            originals, initials, self._state(originals, options, []), options,
            self._entries(options, ["st_views"]),
        )

        assert values["projections"] == {}
        written, error = model.save_user_defaults(values, str(path))
        assert error == ""
        assert path.read_bytes() == before
        assert "projections" not in written

    def test_unchecking_a_default_enabled_projection_writes_enabled_false(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user({}, str(path))
        options = [
            {"id": "st_views", "kind": "st_views", "label": "ST views",
             "default_enabled": True},
        ]

        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        initials = self._state(originals, options, [])
        current = self._state(originals, options, [])
        current["projections_checked"] = []  # the box the profile offers is off
        values = model.general_values_to_store(
            originals, initials, current, options, self._entries(options, []))

        assert values["projections"]["st_views"]["enabled"] is False
        written, error = model.save_user_defaults(values, str(path))
        assert error == ""
        assert written["projections"]["st_views"]["enabled"] is False

    def test_rechecking_a_default_enabled_projection_removes_the_entry(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user({}, str(path))
        options = [
            {"id": "st_views", "kind": "st_views", "label": "ST views",
             "default_enabled": True},
        ]

        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        # The layer already switched the projection off; the box opens
        # unchecked and the user ticks it again.
        originals["projections"] = {"st_views": {"enabled": False}}
        initials = self._state(originals, options, [])
        assert initials["projections_checked"] == []
        current = self._state(originals, options, [])
        current["projections_checked"] = ["st_views"]
        values = model.general_values_to_store(
            originals, initials, current, options, self._entries(options, ["st_views"]))

        assert values["projections"] == {}

    def test_unchecking_a_plain_projection_drops_its_entry(self):
        options = [{"id": "visu_views", "kind": "visu", "label": "Visu"}]
        originals = {"projections": {"visu_views": {"enabled": True}}}
        initials = model.general_projection_initial(originals["projections"], options)
        assert initials == ["visu_views"]

        values = model.general_values_to_store(
            originals, {"projections_checked": initials},
            {"projections_checked": []}, options, self._entries(options, []))

        # Back at the profile default (off), so no entry is left behind.
        assert values["projections"] == {}

    def test_reset_shows_the_profile_defaults_again(self):
        assert model.reset_user_rows()["projections"] == {}

        options = [
            {"id": "st_views", "kind": "st_views", "default_enabled": True},
            {"id": "visu_views", "kind": "visu"},
        ]
        assert model.general_projection_initial({}, options) == ["st_views"]

    def test_toggling_one_kind_changes_only_that_kind(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user({"xml_in_view_kinds": ["visu"]}, str(path))

        _returned, rows, _status, _error = model.general_state(str(path))
        originals = dict((row["name"], row["value"]) for row in rows)
        options = ["visu", "text"]
        initials = self._state(originals, self.PROJECTIONS, options)

        current = self._state(originals, self.PROJECTIONS, options)
        current["kinds_checked"] = ["text"]  # visu unchecked, text checked
        values = model.general_values_to_store(
            originals, initials, current, self.PROJECTIONS,
            self._entries(self.PROJECTIONS, []),
        )

        assert values["xml_in_view_kinds"] == ["text"]
        written, error = model.save_user_defaults(values, str(path))
        assert error == ""
        assert written["xml_in_view_kinds"] == ["text"]

    def test_an_unoffered_kind_survives_a_toggle(self):
        values = model.merge_general_kinds(["custom", "visu"], ["text"], ["visu"])
        assert values == ["custom", "text"]

        # Nothing toggled: the original list, order included, comes back.
        assert model.merge_general_kinds(["custom", "visu"], [], []) == ["custom", "visu"]

    def test_an_unoffered_projection_survives(self):
        original = {"legacy": True, "st_views": {"enabled": True}}
        merged = model.merge_general_projections(original, {}, [])
        assert merged == original

        merged = model.merge_general_projections(
            original, {"visu_views": {"enabled": True}}, [])
        assert merged["legacy"] is True
        assert merged["visu_views"] == {"enabled": True}

    def test_merge_general_values_applies_only_edits(self):
        originals = {"layout": "project-view", "advanced_debug": True}
        initials = {"layout": "project-view", "advanced_debug": True}

        untouched = model.merge_general_values(
            originals, initials, {"layout": "project-view", "advanced_debug": True})
        assert untouched == originals

        edited = model.merge_general_values(
            originals, initials, {"layout": "root-view", "advanced_debug": True})
        assert edited["layout"] == "root-view"
        assert edited["advanced_debug"] is True

    def test_projection_enabled_follows_the_profile_default(self):
        default_on = {"id": "st_views", "kind": "st_views", "default_enabled": True}
        default_off = {"id": "visu_views", "kind": "visu"}
        # Nothing said: the profile decides.
        assert model.projection_enabled({}, default_on) is True
        assert model.projection_enabled({}, default_off) is False
        # An explicit entry wins over the default, whichever way it points.
        assert model.projection_enabled({"st_views": {"enabled": False}}, default_on) is False
        assert model.projection_enabled({"visu_views": {"enabled": True}}, default_off) is True
        assert model.projection_enabled({"st_views": False}, default_on) is False
        assert model.projection_enabled({"st_views": True}, default_on) is True
        # A value keyed by kind counts too.
        assert model.projection_enabled({"visu": {"enabled": True}}, default_off) is True
        assert model.projection_enabled({"st_views": True}, default_off) is False

    def test_general_projection_initial_shows_the_profile_defaults(self):
        options = [
            {"id": "st_views", "kind": "st_views", "default_enabled": True},
            {"id": "visu_views", "kind": "visu"},
        ]
        assert model.general_projection_initial({}, options) == ["st_views"]
        assert model.general_projection_initial({"visu_views": {}}, options) == [
            "st_views", "visu_views"
        ]
        assert model.general_projection_initial(
            {"st_views": {"enabled": False}}, options) == []

    def test_general_kind_initial_is_strict(self):
        assert model.general_kind_initial(["visu"], []) == []
        assert model.general_kind_initial(["visu"], ["text", "visu"]) == ["visu"]
        assert model.general_kind_initial(None, ["visu"]) == []


class TestResetToBuiltIn:
    """"Reset to built-in" makes the save land on an empty user layer.

    The tab's Reset puts the controls at the code defaults and marks the tab
    reset, so the save starts from no overrides at all instead of from the
    file's effective values -- which is what drops the keys the tab cannot show.
    Cancelling never runs this: nothing is written until Save.
    """

    PROJECTIONS = [
        {"id": "pou_st", "kind": "pou_st", "label": "POU", "format": "st",
         "default_enabled": True},
        {"id": "visu_views", "kind": "visu", "label": "Visu", "format": "xml",
         "default_enabled": True},
    ]
    KINDS = ["visu"]

    def _reset_state(self):
        return TestGeneralEdits._state(
            self, model.reset_user_rows(), self.PROJECTIONS, self.KINDS)

    def _entries(self, checked):
        return TestGeneralEdits._entries(self, self.PROJECTIONS, checked)

    def test_reset_then_save_leaves_no_overrides(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        # One key the tab can show and two it cannot: a projection and a kind
        # the current profile does not offer.
        _write_user(
            {
                "verbose_logging": True,
                "projections": {"legacy_views": {"enabled": True}},
                "xml_in_view_kinds": ["visu", "alarm"],
            },
            str(path),
        )

        reset = model.reset_user_rows()
        state = self._reset_state()
        values = model.general_values_to_store(
            reset, state, state, self.PROJECTIONS, self._entries(
                state["projections_checked"]))

        assert values["xml_in_view_kinds"] == ["visu"]
        assert values["projections"] == {}
        written, error = model.save_user_defaults(values, str(path))

        assert error == ""
        assert written == {"version": _user_defaults.DEFAULTS_VERSION}
        assert _user_defaults.read_user_defaults(str(path))[0] == {}

    def test_an_edit_after_reset_is_stored_on_the_empty_base(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        _write_user(
            {"verbose_logging": True, "projections": {"legacy_views": True}},
            str(path),
        )

        reset = model.reset_user_rows()
        initial = self._reset_state()
        current = dict(initial)
        current["verbose_logging"] = True
        current["projections_checked"] = ["pou_st"]  # visu_views unchecked
        values = model.general_values_to_store(
            reset, initial, current, self.PROJECTIONS,
            self._entries(["pou_st"]))
        written, error = model.save_user_defaults(values, str(path))

        assert error == ""
        # Only the two edits survive; the unoffered legacy entry is gone.
        assert written["verbose_logging"] is True
        assert written["projections"] == {
            "visu_views": {
                "enabled": False, "kind": "visu", "format": "xml",
                "import_safe": False,
            }
        }
        assert "legacy_views" not in written


class TestProjectTabEdits:
    """The Project tab saves the same way the General tab does.

    Unchecking a projection has to write an explicit ``enabled: false``, or the
    engine falls back to the profile's ``default_enabled`` and the view stays
    exported; a box put back at the profile's own answer must not leave an
    entry behind; and an untouched tab must not rewrite the file at all.
    """

    def _options(self):
        return model.profile_view_options("default")[0]

    def _kinds(self):
        return model.profile_view_options("default")[1]

    def _tab_state(self, settings, options, kinds):
        return TestGeneralEdits._state(self, settings, options, kinds)

    def _entries(self, options, checked):
        return TestGeneralEdits._entries(self, options, checked)

    def _file(self, **overrides):
        data = {
            "version": 2,
            "layout": "project-view",
            "profile": "default",
            "projections": {},
            "sync_mode": "xml_first",
            "xml_in_view_kinds": ["visu"],
        }
        data.update(overrides)
        return data

    def _save(self, root, settings, view_values):
        format_values = {
            "layout": settings["layout"],
            "view_root": settings.get("view_root"),
            "profile": settings["profile"],
            "projections": view_values["projections"],
            "sync_mode": settings["sync_mode"],
            "xml_in_view_kinds": view_values["xml_in_view_kinds"],
        }
        merged, pinned = model.assemble_project_save(
            settings, format_values, {}, "same")
        _project_settings.save_project_settings(str(root), merged, pinned=pinned)

    def _enabled_ids(self, settings):
        profile = _project_profiles.load_profile(settings["profile"])
        return [
            projection.get("id")
            for projection in _project_profiles.enabled_projection_options(
                profile, settings["projections"])
        ]

    def test_untouched_project_save_is_byte_identical(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        # A file the dialog itself wrote: every projection explicit at the
        # profile's answer, plus a kind the profile does not offer.
        options = self._options()
        _project_settings.save_project_settings(str(root), self._file(
            projections=dict(
                (projection["id"], model.projection_entry(
                    projection,
                    bool(projection.get("default_enabled"))))
                for projection in options),
            xml_in_view_kinds=["visu", "custom"],
        ))
        before = _project_settings.settings_path(str(root))
        with io.open(before, encoding="utf-8") as handle:
            original = handle.read()

        settings, _sources, _status, _error = model.project_layers(str(root))
        state = self._tab_state(settings, options, self._kinds())
        view_values = model.project_view_values(
            settings, state, state, options,
            self._entries(options, state["projections_checked"]))

        assert view_values["xml_in_view_kinds"] == ["visu", "custom"]
        self._save(root, settings, view_values)
        with io.open(before, encoding="utf-8") as handle:
            assert handle.read() == original

    def test_unchecking_a_projection_disables_it_in_the_engine(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        options = self._options()
        _write_project(root, self._file(
            projections=dict(
                (projection["id"], model.projection_entry(projection, True))
                for projection in options)))

        settings, _sources, _status, _error = model.project_layers(str(root))
        initial = self._tab_state(settings, options, self._kinds())
        assert "pou_st" in initial["projections_checked"]

        current = dict(initial)
        current["projections_checked"] = [
            projection_id for projection_id in initial["projections_checked"]
            if projection_id != "pou_st"
        ]
        view_values = model.project_view_values(
            settings, initial, current, options,
            self._entries(options, current["projections_checked"]))
        self._save(root, settings, view_values)

        reloaded, _sources, _status, _error = model.project_layers(str(root))
        assert reloaded["projections"]["pou_st"]["enabled"] is False
        assert "pou_st" not in self._enabled_ids(reloaded)
        # Reopening shows it unchecked, so the box matches the pipeline.
        reopened = self._tab_state(reloaded, options, self._kinds())
        assert "pou_st" not in reopened["projections_checked"]
        assert "gvl_st" in reopened["projections_checked"]

    def test_checking_it_back_removes_the_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        options = self._options()
        _write_project(root, self._file(
            projections={"pou_st": model.projection_entry(options[0], False)}))

        settings, _sources, _status, _error = model.project_layers(str(root))
        initial = self._tab_state(settings, options, self._kinds())
        assert "pou_st" not in initial["projections_checked"]

        current = dict(initial)
        current["projections_checked"] = (
            list(initial["projections_checked"]) + ["pou_st"])
        view_values = model.project_view_values(
            settings, initial, current, options,
            self._entries(options, current["projections_checked"]))
        self._save(root, settings, view_values)

        reloaded, _sources, _status, _error = model.project_layers(str(root))
        assert "pou_st" not in reloaded["projections"]
        assert "pou_st" in self._enabled_ids(reloaded)

    def test_an_unoffered_kind_survives_a_toggle(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        options = self._options()
        _write_project(root, self._file(xml_in_view_kinds=["visu", "custom"]))

        settings, _sources, _status, _error = model.project_layers(str(root))
        kinds = self._kinds()
        initial = self._tab_state(settings, options, kinds)
        assert initial["kinds_checked"] == ["visu"]

        current = dict(initial)
        current["kinds_checked"] = []  # the one offered kind is switched off
        view_values = model.project_view_values(
            settings, initial, current, options, self._entries(options, []))
        self._save(root, settings, view_values)

        reloaded, _sources, _status, _error = model.project_layers(str(root))
        # The kind the profile cannot offer is still there.
        assert reloaded["xml_in_view_kinds"] == ["custom"]


class TestProjectProfileChange:
    """A profile change re-reads the boxes against the new profile."""

    def test_a_box_disagreeing_with_the_new_default_gets_an_entry(self):
        boxed_off = {"id": "visu_views", "kind": "visu", "format": "xml"}
        offered = [
            {"id": "visu_views", "kind": "visu", "format": "xml",
             "default_enabled": True},
            {"id": "pou_st", "kind": "pou", "format": "st",
             "default_enabled": True},
        ]

        values = model.project_view_values_for_profile(
            {"projections": {"legacy": True}, "xml_in_view_kinds": ["old"]},
            [(boxed_off, False)], offered, ["visu"], [])

        # visu_views disagrees with the new default; pou_st has no box, so it
        # keeps the new profile's answer; the unoffered entry is preserved.
        assert values["projections"] == {
            "legacy": True,
            "visu_views": model.projection_entry(boxed_off, False),
        }
        assert values["xml_in_view_kinds"] == ["old"]

    def test_boxes_matching_the_new_default_write_no_entry(self):
        boxed = {"id": "pou_st", "kind": "pou", "format": "st"}
        values = model.project_view_values_for_profile(
            {"projections": {"pou_st": {"enabled": False}}},
            [(boxed, True)],
            [{"id": "pou_st", "kind": "pou", "format": "st",
              "default_enabled": True}],
            ["visu"], ["visu"])

        assert values["projections"] == {}
        assert values["xml_in_view_kinds"] == ["visu"]


class TestUserValuesToOverrides:
    def test_kinds_accept_a_comma_separated_string(self):
        overrides, error = model.user_values_to_overrides(
            {"xml_in_view_kinds": "visu, text ,"}
        )
        assert error == ""
        assert overrides["xml_in_view_kinds"] == ["visu", "text"]

    def test_projections_accept_json_text_and_blank(self, tmp_path):
        overrides, error = model.user_values_to_overrides(
            {"projections": '{"st_views": {"enabled": true}}'}
        )
        assert error == ""
        assert overrides["projections"] == {"st_views": {"enabled": True}}

        # A blank box means "the code default"; the writer drops it.
        written, error = model.save_user_defaults(
            {"projections": "  "}, str(tmp_path / "config" / "defaults.json")
        )
        assert error == ""
        assert "projections" not in written

    def test_strings_are_validated_not_silently_dropped(self):
        overrides, error = model.user_values_to_overrides(
            {"backup_retention_count": "0"}
        )
        assert overrides is None
        assert "backup_retention_count" in error

        overrides, error = model.user_values_to_overrides({"advanced_debug": "maybe"})
        assert overrides is None
        assert "advanced_debug" in error

    def test_unparseable_projections_is_an_error(self):
        overrides, error = model.user_values_to_overrides({"projections": "{"})
        assert overrides is None
        assert "projections" in error

    def test_a_relative_view_root_is_kept(self):
        overrides, error = model.user_values_to_overrides(
            {"view_root": "views", "verbose_logging": True}
        )
        assert error == ""
        assert overrides["view_root"] == "views"
        assert overrides["verbose_logging"] is True

    def test_none_view_root_is_kept_as_no_custom_root(self):
        overrides, error = model.user_values_to_overrides({"view_root": None})
        assert error == ""
        assert overrides["view_root"] is None

    def test_an_absolute_view_root_names_the_rule(self):
        overrides, error = model.user_values_to_overrides({"view_root": "/elsewhere"})
        assert overrides is None
        assert "relative" in error

    def test_a_parent_segment_view_root_names_the_rule(self):
        overrides, error = model.user_values_to_overrides({"view_root": "../up"})
        assert overrides is None
        assert "relative" in error


class TestSaveUserDefaults:
    def test_sparse_file_drops_equal_to_default_values(self, tmp_path):
        path = str(tmp_path / "config" / "defaults.json")

        written, error = model.save_user_defaults(
            {
                "advanced_debug": True,
                "show_completion_popup": True,  # equals the code default
                "backup_retention_count": "25",
            },
            path,
        )

        assert error == ""
        assert written["advanced_debug"] is True
        assert written["backup_retention_count"] == 25
        assert "show_completion_popup" not in written
        assert "show_completion_popup" not in json.load(
            io.open(path, encoding="utf-8")
        )

    def test_an_invalid_value_leaves_the_file_alone(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"advanced_debug": true}', encoding="utf-8")
        before = path.read_text(encoding="utf-8")

        written, error = model.save_user_defaults(
            {"advanced_debug": True, "sync_mode": "not-a-mode"}, str(path)
        )

        assert written is None
        assert "sync_mode" in error
        assert path.read_text(encoding="utf-8") == before

    def test_an_unwritable_path_returns_the_error(self, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("read-only")

        monkeypatch.setattr(_user_defaults.os, "makedirs", boom)
        monkeypatch.setattr(
            _user_defaults, "write_user_defaults", boom
        )

        written, error = model.save_user_defaults(
            {"advanced_debug": True}, str(tmp_path / "blocked" / "defaults.json")
        )

        assert written is None
        assert "read-only" in error
