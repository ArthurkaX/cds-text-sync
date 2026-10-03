# -*- coding: utf-8 -*-
"""
test_settings_layers_model.py - Decision logic behind the settings dialogs.

The WinForms code is a thin shell over ``settings_layers_model``; these pin the
rules that shell depends on: which behavior key is pinned, where an inherited
value comes from, what "Reset to defaults" fills in, what the dialog writes,
and how the CTS Defaults window parses its controls back into overrides.
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

from cds_text_sync.engine import _project_settings, _user_defaults


def _write_project(root, data):
    with io.open(_project_settings.settings_path(str(root)), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data))


def _read_project(root):
    with io.open(_project_settings.settings_path(str(root)), encoding="utf-8") as handle:
        return json.load(handle)


def _write_user(overrides, path):
    _user_defaults.write_user_defaults(overrides, path=path)


class TestBehaviorRows:
    def test_sources_decide_pinned_and_hint(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2, "advanced_debug": True})
        user = str(tmp_path / "config" / "defaults.json")
        _write_user({"verbose_logging": True}, user)

        settings, sources, _status, _error = model.project_layers(
            str(root), user_defaults_path=user
        )
        rows = dict(
            (row["name"], row) for row in model.behavior_rows(settings, sources)
        )

        assert rows["advanced_debug"]["pinned"] is True
        assert rows["advanced_debug"]["source"] == "project"
        assert rows["verbose_logging"]["pinned"] is False
        assert rows["verbose_logging"]["source"] == "user"
        assert rows["verbose_logging"]["hint"] == "user default"
        assert rows["advanced_debug"]["hint"] == "project file"
        # untouched key: not pinned, code default
        assert rows["show_completion_popup"]["pinned"] is False
        assert rows["show_completion_popup"]["hint"] == "built-in"

    def test_behavior_rows_cover_every_behavior_key(self):
        rows = model.behavior_rows(
            _project_settings.default_project_settings(), {}
        )
        assert [row["name"] for row in rows] == list(_user_defaults.BEHAVIOR_KEYS)


class TestInheritedValues:
    def test_override_wins_else_code_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _write_user({"advanced_debug": True}, _user_defaults.defaults_path())

        values = model.inherited_behavior_values()
        defaults = _project_settings.default_project_settings()

        assert values["advanced_debug"] is True
        assert values["verbose_logging"] == defaults["verbose_logging"]

    def test_hints_follow_the_user_layer(self, tmp_path):
        _write_user({"advanced_debug": True}, _user_defaults.defaults_path())

        hints = model.behavior_hints()

        assert hints["advanced_debug"] == "user default"
        assert hints["verbose_logging"] == "built-in"


class TestFormatReset:
    def test_overrides_win_and_view_root_is_untouched(self, tmp_path):
        user = str(tmp_path / "config" / "defaults.json")
        _write_user({"sync_mode": "text_first", "profile": "astra"}, user)

        values = model.format_reset_values(user)

        assert values["sync_mode"] == "text_first"
        assert values["profile"] == "astra"
        assert values["layout"] == _project_settings.default_project_settings()["layout"]
        assert "view_root" not in values
        assert not (set(_user_defaults.PROJECT_ONLY_KEYS) & set(values))

    def test_missing_file_falls_back_to_code_defaults(self, tmp_path):
        values = model.format_reset_values(str(tmp_path / "nope" / "defaults.json"))
        defaults = _project_settings.default_project_settings()

        assert values["sync_mode"] == defaults["sync_mode"]
        assert values["xml_in_view_kinds"] == defaults["xml_in_view_kinds"]


class TestAssembleProjectSave:
    def test_pinned_order_follows_the_engine(self):
        _settings, pinned = model.assemble_project_save(
            {},
            {},
            {"verbose_logging": True, "advanced_debug": True},
            ["advanced_debug", "verbose_logging"],
        )
        assert pinned == ["verbose_logging", "advanced_debug"]

    def test_unpinned_key_keeps_inheriting(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})

        # The control was edited to True, but its "Inherit" box stayed checked:
        # the value handed back is the inherited one, so nothing is written.
        settings, pinned = model.assemble_project_save(
            {}, {}, {"verbose_logging": False}, ["advanced_debug"]
        )
        assert pinned == ["advanced_debug"]

        _project_settings.save_project_settings(
            str(root), settings, pinned=pinned
        )
        on_disk = _read_project(root)

        assert "verbose_logging" not in on_disk
        assert on_disk["advanced_debug"] is False  # pinned, written explicitly

    def test_format_values_reach_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        settings, pinned = model.assemble_project_save(
            {}, {"sync_mode": "text_first"}, {}, []
        )
        _project_settings.save_project_settings(str(root), settings, pinned=pinned)

        assert _read_project(root)["sync_mode"] == "text_first"


class TestUserDefaultsState:
    def test_rows_show_effective_values_and_create_the_file(self, tmp_path):
        path = str(tmp_path / "config" / "cds-text-sync" / "defaults.json")

        returned_path, rows, status, error = model.user_defaults_state(path)

        assert returned_path == path
        assert os.path.exists(path)
        assert status == _project_settings.SETTINGS_OK
        assert error == ""
        names = [row["name"] for row in rows]
        assert "view_root" not in names
        assert set(names) == set(_user_defaults.USER_DEFAULT_KEYS) - set(
            _user_defaults.PROJECT_ONLY_KEYS
        )
        by_name = dict((row["name"], row) for row in rows)
        defaults = _project_settings.default_project_settings()
        assert by_name["sync_mode"]["value"] == defaults["sync_mode"]
        assert by_name["sync_mode"]["class"] == "format"
        assert by_name["advanced_debug"]["class"] == "behavior"
        assert by_name["advanced_debug"]["overridden"] is False

    def test_overridden_flag_tracks_the_file(self, tmp_path):
        path = str(tmp_path / "config" / "defaults.json")
        _write_user({"advanced_debug": True}, path)

        _returned, rows, _status, _error = model.user_defaults_state(path)
        by_name = dict((row["name"], row) for row in rows)

        assert by_name["advanced_debug"]["overridden"] is True
        assert by_name["advanced_debug"]["value"] is True

    def test_broken_file_reports_the_error_and_defaults(self, tmp_path):
        path = tmp_path / "config" / "defaults.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

        _returned, rows, status, error = model.user_defaults_state(str(path))

        assert status == _project_settings.SETTINGS_INVALID
        assert error
        by_name = dict((row["name"], row) for row in rows)
        assert by_name["advanced_debug"]["value"] is False

    def test_reset_user_rows_are_the_code_defaults(self):
        values = model.reset_user_rows()
        defaults = _project_settings.default_project_settings()

        assert "view_root" not in values
        for name, value in values.items():
            assert value == defaults[name]


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

    def test_view_root_in_the_raw_values_is_ignored(self):
        overrides, error = model.user_values_to_overrides(
            {"view_root": "/elsewhere", "verbose_logging": True}
        )
        assert error == ""
        assert "view_root" not in overrides
        assert overrides["verbose_logging"] is True


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


class TestProjectDialogRoundTrip:
    def test_pinned_state_survives_a_save_and_reload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 2})
        _write_user({"advanced_debug": True}, _user_defaults.defaults_path())

        settings, sources, _status, _error = model.project_layers(str(root))
        rows = dict(
            (row["name"], row) for row in model.behavior_rows(settings, sources)
        )
        # advanced_debug inherits the user's True, verbose_logging is at the
        # built-in False; the user pins verbose_logging and leaves the rest.
        assert rows["advanced_debug"]["pinned"] is False
        inherited = model.inherited_behavior_values()

        save_settings, pinned = model.assemble_project_save(
            settings,
            {},
            {
                "advanced_debug": inherited["advanced_debug"],
                "verbose_logging": True,
            },
            ["verbose_logging"],
        )
        _project_settings.save_project_settings(str(root), save_settings, pinned=pinned)

        reloaded, reloaded_sources, _status, _error = model.project_layers(str(root))
        reloaded_rows = dict(
            (row["name"], row)
            for row in model.behavior_rows(reloaded, reloaded_sources)
        )
        assert reloaded_rows["verbose_logging"]["pinned"] is True
        assert reloaded["verbose_logging"] is True
        assert reloaded_rows["advanced_debug"]["pinned"] is False
        assert reloaded["advanced_debug"] is True  # still inherited from the user
