# -*- coding: utf-8 -*-
"""
test_settings_layers.py - Layering of code defaults, user defaults and the
project file.

Pins the resolution rules: behavior keys inherit from the per-user file unless
the project pins them, format keys only seed a project that has no file yet,
version 1 migrates its equal-to-default behavior values to "not pinned", and
saving keeps a sparse file. Sources report where each value came from.
"""

import io
import json
import os

from cds_text_sync.engine._project_settings import (
    SETTINGS_MISSING,
    SETTINGS_OK,
    SETTINGS_VERSION,
    default_project_settings,
    read_project_settings,
    read_project_settings_layers,
    save_project_settings,
    settings_path,
)


def _user_path(tmp_path):
    return str(tmp_path / "config" / "cds-text-sync" / "defaults.json")


def _write_json(path, data):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data))


def _write_raw(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read_file(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_project(root, data):
    with io.open(settings_path(str(root)), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data))


class TestBehaviorInheritance:
    def test_user_override_applies_when_project_does_not_pin(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": SETTINGS_VERSION, "layout": "project-view"})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "advanced_debug": True})

        settings, sources, status, error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert status == SETTINGS_OK
        assert settings["advanced_debug"] is True
        assert sources["advanced_debug"] == "user"

    def test_project_pin_wins_over_user_override(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": SETTINGS_VERSION, "advanced_debug": False})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "advanced_debug": True})

        settings, sources, status, error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["advanced_debug"] is False
        assert sources["advanced_debug"] == "project"

    def test_code_default_when_neither_layer_sets_it(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": SETTINGS_VERSION})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1})

        settings, sources, status, error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        defaults = default_project_settings()
        assert settings["verbose_logging"] == defaults["verbose_logging"]
        assert sources["verbose_logging"] == "code"
        assert sources["layout"] == "code"

    def test_format_key_source_is_project_when_present(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": SETTINGS_VERSION, "sync_mode": "text_first"})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1})

        settings, sources, _status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["sync_mode"] == "text_first"
        assert sources["sync_mode"] == "project"


class TestFormatKeys:
    def test_user_format_does_not_touch_existing_project_file(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        # The file exists and says nothing about sync_mode, so the code default
        # stands even though the user layer prefers text_first.
        _write_project(root, {"version": SETTINGS_VERSION, "layout": "project-view"})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "sync_mode": "text_first"})

        settings, sources, _status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["sync_mode"] == "xml_first"
        assert sources["sync_mode"] == "code"

    def test_user_format_seeds_a_missing_project_file(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "sync_mode": "text_first", "profile": "astra"})

        settings, sources, status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert status == SETTINGS_MISSING
        assert settings["sync_mode"] == "text_first"
        assert sources["sync_mode"] == "user"
        assert settings["profile"] == "astra"
        assert sources["profile"] == "user"

    def test_missing_project_file_still_inherits_behavior(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "advanced_debug": True})

        settings, sources, status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert status == SETTINGS_MISSING
        assert settings["advanced_debug"] is True
        assert sources["advanced_debug"] == "user"

    def test_relative_view_root_seeds_a_missing_project_file(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "view_root": "views"})

        settings, sources, status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert status == SETTINGS_MISSING
        # The user value is relative; seeded into this project it is resolved
        # against the project's own sync folder, not the working directory.
        assert settings["view_root"] == os.path.normpath(
            os.path.join(str(root), "views")
        )
        assert sources["view_root"] == "user"

    def test_view_root_does_not_touch_an_existing_project_file(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": SETTINGS_VERSION, "layout": "project-view"})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "view_root": "views"})

        settings, sources, _status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["view_root"] is None
        assert sources["view_root"] == "code"

    def test_an_absolute_view_root_in_the_user_file_is_ignored(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        user = _user_path(tmp_path)
        _write_raw(user, json.dumps({"version": 1, "view_root": "/elsewhere"}))

        settings, sources, _status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["view_root"] is None
        assert sources["view_root"] == "code"


class TestVersionOneMigration:
    def test_equal_to_code_default_is_not_pinned(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        # show_completion_popup defaults to True, so a v1 file storing True is
        # treated as "nobody chose this" and starts inheriting.
        _write_project(root, {"version": 1, "show_completion_popup": True})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "show_completion_popup": False})

        settings, sources, _status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["show_completion_popup"] is False
        assert sources["show_completion_popup"] == "user"

    def test_differing_value_is_pinned(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": 1, "show_completion_popup": False})
        user = _user_path(tmp_path)
        _write_json(user, {"version": 1, "show_completion_popup": True})

        settings, sources, _status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert settings["show_completion_popup"] is False
        assert sources["show_completion_popup"] == "project"

    def test_save_rewrites_as_v2_and_drops_inherited(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(
            root,
            {"version": 1, "layout": "project-view", "show_completion_popup": True},
        )

        settings = read_project_settings(str(root))[0]
        assert settings["show_completion_popup"] is True
        save_project_settings(str(root), settings)

        on_disk = _read_file(settings_path(str(root)))
        assert on_disk["version"] == SETTINGS_VERSION
        assert on_disk["layout"] == "project-view"
        # Equal to the code default, so it is no longer written at all.
        assert "show_completion_popup" not in on_disk

    def test_save_keeps_a_differing_behavior_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(
            root,
            {"version": 1, "layout": "project-view", "show_completion_popup": False},
        )

        settings = read_project_settings(str(root))[0]
        save_project_settings(str(root), settings)

        on_disk = _read_file(settings_path(str(root)))
        assert on_disk["version"] == SETTINGS_VERSION
        assert on_disk["show_completion_popup"] is False


class TestSavePinning:
    def test_pinned_keeps_a_value_equal_to_inherited(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        save_project_settings(
            str(root),
            {"show_completion_popup": True},
            pinned=["show_completion_popup"],
        )
        assert _read_file(settings_path(str(root)))["show_completion_popup"] is True

    def test_unpinned_drops_a_value_equal_to_inherited(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        save_project_settings(str(root), {"show_completion_popup": True})
        assert "show_completion_popup" not in _read_file(settings_path(str(root)))

    def test_save_returns_the_full_settings_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        root = tmp_path / "sync"
        root.mkdir()
        returned = save_project_settings(str(root), {"layout": "project-view"})
        assert returned["layout"] == "project-view"
        assert returned["advanced_debug"] is False
        assert returned["version"] == SETTINGS_VERSION


class TestInvalidUserDefaults:
    def test_invalid_file_does_not_change_project_status(self, tmp_path, capsys):
        root = tmp_path / "sync"
        root.mkdir()
        _write_project(root, {"version": SETTINGS_VERSION, "layout": "root-view"})
        user = _user_path(tmp_path)
        _write_raw(user, "{not json")

        settings, sources, status, error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert status == SETTINGS_OK
        assert error == ""
        assert settings["layout"] == "root-view"
        assert sources["layout"] == "project"
        assert capsys.readouterr().out  # the bad defaults file is still warned about

    def test_invalid_file_falls_back_to_code_defaults(self, tmp_path):
        root = tmp_path / "sync"
        root.mkdir()
        user = _user_path(tmp_path)
        _write_raw(user, "{not json")

        settings, _sources, status, _error = read_project_settings_layers(
            str(root), user_defaults_path=user
        )

        assert status == SETTINGS_MISSING
        assert settings == default_project_settings()

    def test_unwritable_dir_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        from cds_text_sync.engine import _user_defaults

        def boom(*args, **kwargs):
            raise OSError("read-only")

        monkeypatch.setattr(_user_defaults.os, "makedirs", boom)
        root = tmp_path / "sync"
        root.mkdir()
        settings, _sources, status, _error = read_project_settings_layers(str(root))
        assert status == SETTINGS_MISSING
        assert settings == default_project_settings()
