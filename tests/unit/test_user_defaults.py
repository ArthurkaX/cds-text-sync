# -*- coding: utf-8 -*-
"""
test_user_defaults.py - Unit tests for the per-user sparse defaults layer.

Covers path resolution, first-access creation, sparse/validated writes,
tolerant reads (invalid JSON, invalid values, unknown keys, a non-relative
view_root) and the future-key case where a value missing from the file keeps
its code default.
"""

import io
import json
import os

from cds_text_sync.engine import _user_defaults
from cds_text_sync.engine._project_settings import (
    SETTINGS_INVALID,
    SETTINGS_MISSING,
    SETTINGS_OK,
    default_project_settings,
)


def _write_raw(path, text):
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _write_json(path, data):
    _write_raw(path, json.dumps(data))


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _empty_file(tmp_path):
    """A defaults path inside tmp_path that does not exist yet."""
    return str(tmp_path / "config" / "cds-text-sync" / "defaults.json")


class TestDefaultsPath:
    def test_windows_uses_appdata(self, monkeypatch):
        monkeypatch.setattr(_user_defaults, "_is_windows", lambda: True)
        monkeypatch.setenv("APPDATA", "C:\\Users\\dev\\AppData\\Roaming")
        expected = os.path.join(
            "C:\\Users\\dev\\AppData\\Roaming", "cds-text-sync", "defaults.json"
        )
        assert _user_defaults.defaults_path() == expected

    def test_other_uses_xdg_config_home(self, monkeypatch):
        monkeypatch.setattr(_user_defaults, "_is_windows", lambda: False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/home/dev/.config")
        expected = os.path.join("/home/dev/.config", "cds-text-sync", "defaults.json")
        assert _user_defaults.defaults_path() == expected

    def test_other_falls_back_to_home_config(self, monkeypatch):
        monkeypatch.setattr(_user_defaults, "_is_windows", lambda: False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", "/home/dev")
        expected = os.path.join("/home/dev/.config", "cds-text-sync", "defaults.json")
        assert _user_defaults.defaults_path() == expected


class TestKeyClass:
    def test_behavior_keys(self):
        for name in _user_defaults.BEHAVIOR_KEYS:
            assert _user_defaults.key_class(name) == "behavior"

    def test_format_keys(self):
        for name in _user_defaults.FORMAT_KEYS:
            assert _user_defaults.key_class(name) == "format"

    def test_unknown_defaults_to_format(self):
        assert _user_defaults.key_class("brand_new_key") == "format"


class TestFirstAccess:
    def test_missing_file_reports_missing(self, tmp_path):
        path = _empty_file(tmp_path)
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert overrides == {}
        assert status == SETTINGS_MISSING
        assert error == ""
        assert not os.path.exists(path)

    def test_ensure_creates_version_only_file(self, tmp_path):
        path = _empty_file(tmp_path)
        assert _user_defaults.ensure_user_defaults(path) is True
        assert os.path.exists(path)
        assert _read_json(path) == {"version": 1}

    def test_ensure_is_idempotent(self, tmp_path):
        path = _empty_file(tmp_path)
        _user_defaults.ensure_user_defaults(path)
        _write_json(path, {"version": 1, "advanced_debug": True})
        assert _user_defaults.ensure_user_defaults(path) is True
        assert _read_json(path)["advanced_debug"] is True

    def test_ensure_does_not_raise_on_unwritable_dir(self, tmp_path, monkeypatch):
        path = _empty_file(tmp_path)

        def boom(*args, **kwargs):
            raise OSError("read-only")

        monkeypatch.setattr(_user_defaults.os, "makedirs", boom)
        assert _user_defaults.ensure_user_defaults(path) is False

    def test_effective_runs_ensure_first(self, tmp_path):
        path = _empty_file(tmp_path)
        settings = _user_defaults.effective_user_defaults(path)
        assert os.path.exists(path)
        assert settings == default_project_settings()


class TestWriteSparse:
    def test_equal_to_code_default_is_dropped(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults(
            {"show_completion_popup": True, "backup_retention_count": 10}, path
        )
        assert written == {"version": 1}
        assert _read_json(path) == {"version": 1}

    def test_changed_values_are_kept(self, tmp_path):
        path = _empty_file(tmp_path)
        _user_defaults.write_user_defaults(
            {"show_completion_popup": False, "advanced_debug": True}, path
        )
        assert _read_json(path) == {
            "version": 1,
            "advanced_debug": True,
            "show_completion_popup": False,
        }

    def test_values_are_normalized(self, tmp_path):
        path = _empty_file(tmp_path)
        _user_defaults.write_user_defaults(
            {"sync_mode": "text-first", "layout": "root-view"}, path
        )
        data = _read_json(path)
        assert data["sync_mode"] == "text_first"
        assert data["layout"] == "root-view"

    def test_a_relative_view_root_is_stored(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults(
            {"view_root": "views\\nested"}, path
        )
        assert written["view_root"] == "views/nested"
        assert _read_json(path)["view_root"] == "views/nested"

    def test_an_absolute_view_root_is_rejected(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults({"view_root": "/somewhere"}, path)
        assert "view_root" not in written
        assert _read_json(path) == {"version": 1}

    def test_a_drive_letter_view_root_is_rejected(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults(
            {"view_root": "C:\\elsewhere"}, path
        )
        assert "view_root" not in written

    def test_a_parent_segment_view_root_is_rejected(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults(
            {"view_root": "views/../../outside"}, path
        )
        assert "view_root" not in written

    def test_an_empty_view_root_is_rejected(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults({"view_root": ""}, path)
        assert "view_root" not in written

    def test_no_view_root_is_the_default_and_is_not_written(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults({"view_root": None}, path)
        assert "view_root" not in written

    def test_invalid_values_are_dropped(self, tmp_path):
        path = _empty_file(tmp_path)
        written = _user_defaults.write_user_defaults(
            {"show_completion_popup": "maybe", "backup_retention_count": 0}, path
        )
        assert written == {"version": 1}

    def test_creates_parent_directory(self, tmp_path):
        path = _empty_file(tmp_path)
        _user_defaults.write_user_defaults({}, path)
        assert os.path.isdir(os.path.dirname(path))


class TestReadTolerance:
    def test_invalid_json_reports_invalid(self, tmp_path, capsys):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_raw(path, "{not json")
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert overrides == {}
        assert status == SETTINGS_INVALID
        assert path in error
        assert "Warning" in capsys.readouterr().out

    def test_non_object_reports_invalid(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, [1, 2, 3])
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert overrides == {}
        assert status == SETTINGS_INVALID

    def test_warn_can_be_silenced(self, tmp_path, capsys):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_raw(path, "{not json")
        _user_defaults.read_user_defaults(path, warn=False)
        assert capsys.readouterr().out == ""

    def test_invalid_value_is_dropped_with_warning(self, tmp_path, capsys):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(
            path,
            {"version": 1, "show_completion_popup": "maybe", "advanced_debug": True},
        )
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert status == SETTINGS_OK
        assert overrides == {"advanced_debug": True}
        assert "show_completion_popup" in capsys.readouterr().out

    def test_unknown_key_is_ignored(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, {"version": 1, "brand_new_key": "value"})
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert status == SETTINGS_OK
        assert overrides == {}

    def test_version_is_not_an_override(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, {"version": 1})
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert overrides == {}

    def test_a_relative_view_root_is_read(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, {"version": 1, "view_root": "views/nested"})
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert status == SETTINGS_OK
        assert overrides["view_root"] == "views/nested"

    def test_an_absolute_view_root_is_refused_with_a_warning(self, tmp_path, capsys):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, {"version": 1, "view_root": "/somewhere"})
        overrides, status, error = _user_defaults.read_user_defaults(path)
        assert status == SETTINGS_OK
        assert "view_root" not in overrides
        assert "view_root" in capsys.readouterr().out

    def test_sync_mode_alias_is_normalized(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, {"version": 1, "sync_mode": "text-first"})
        overrides = _user_defaults.read_user_defaults(path)[0]
        assert overrides["sync_mode"] == "text_first"


class TestEffectiveDefaults:
    def test_future_key_missing_from_file_keeps_code_default(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_json(path, {"version": 1, "advanced_debug": True})
        settings = _user_defaults.effective_user_defaults(path)
        defaults = default_project_settings()
        assert settings["advanced_debug"] is True
        # A key the file never mentioned keeps whatever the code says today.
        assert settings["verbose_logging"] == defaults["verbose_logging"]
        assert settings["backup_retention_count"] == defaults["backup_retention_count"]

    def test_invalid_json_falls_back_to_code_defaults(self, tmp_path):
        path = _empty_file(tmp_path)
        os.makedirs(os.path.dirname(path))
        _write_raw(path, "{not json")
        assert _user_defaults.effective_user_defaults(path) == default_project_settings()

    def test_overrides_apply_on_top_of_code_defaults(self, tmp_path):
        path = _empty_file(tmp_path)
        _user_defaults.write_user_defaults(
            {"show_completion_popup": False, "backup_retention_count": 3}, path
        )
        settings = _user_defaults.effective_user_defaults(path)
        defaults = default_project_settings()
        assert settings["show_completion_popup"] is False
        assert settings["backup_retention_count"] == 3
        assert settings["sync_mode"] == defaults["sync_mode"]
