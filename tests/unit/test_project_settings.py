# -*- coding: utf-8 -*-
"""
test_project_settings.py - Unit tests for the sync_mode / xml_in_view_kinds
settings keys (coercion, aliases, defaults, round-trip).
"""

import json

from cds_text_sync.engine._project_settings import (
    SYNC_MODE_TEXT_FIRST,
    SYNC_MODE_XML_FIRST,
    default_project_settings,
    load_project_settings,
    normalize_sync_mode,
    save_project_settings,
    settings_path,
)


def _write_settings(project_root, data):
    with open(settings_path(project_root), "w") as handle:
        json.dump(data, handle)


class TestDefaults:
    def test_defaults_include_sync_mode_and_kinds(self):
        defaults = default_project_settings()
        assert defaults["sync_mode"] == SYNC_MODE_XML_FIRST
        assert defaults["xml_in_view_kinds"] == ["visu"]

    def test_missing_file_returns_defaults(self, tmp_path):
        settings = load_project_settings(str(tmp_path))
        assert settings["sync_mode"] == SYNC_MODE_XML_FIRST
        assert settings["xml_in_view_kinds"] == ["visu"]

    def test_missing_keys_fall_back_to_defaults(self, tmp_path):
        _write_settings(str(tmp_path), {"layout": "project-view"})
        settings = load_project_settings(str(tmp_path))
        assert settings["sync_mode"] == SYNC_MODE_XML_FIRST
        assert settings["xml_in_view_kinds"] == ["visu"]


class TestNormalizeSyncMode:
    def test_aliases(self):
        for alias in ("text_first", "text-first", "TEXT_FIRST", "text", "textfirst"):
            assert normalize_sync_mode(alias) == SYNC_MODE_TEXT_FIRST
        for alias in ("xml_first", "xml-first", "XML", "xmlfirst"):
            assert normalize_sync_mode(alias) == SYNC_MODE_XML_FIRST

    def test_invalid_falls_back_to_default(self):
        assert normalize_sync_mode("banana") == SYNC_MODE_XML_FIRST
        assert normalize_sync_mode(None, SYNC_MODE_TEXT_FIRST) == SYNC_MODE_TEXT_FIRST
        assert normalize_sync_mode("banana", SYNC_MODE_TEXT_FIRST) == SYNC_MODE_TEXT_FIRST


class TestLoadCoercion:
    def test_text_first_alias_is_normalized_on_load(self, tmp_path):
        _write_settings(str(tmp_path), {"sync_mode": "text-first"})
        settings = load_project_settings(str(tmp_path))
        assert settings["sync_mode"] == SYNC_MODE_TEXT_FIRST

    def test_invalid_sync_mode_falls_back(self, tmp_path):
        _write_settings(str(tmp_path), {"sync_mode": 42})
        settings = load_project_settings(str(tmp_path))
        assert settings["sync_mode"] == SYNC_MODE_XML_FIRST

    def test_kind_list_is_normalized(self, tmp_path):
        _write_settings(
            str(tmp_path), {"xml_in_view_kinds": ["Visu", " visu ", "", "textlist"]}
        )
        settings = load_project_settings(str(tmp_path))
        assert settings["xml_in_view_kinds"] == ["visu", "textlist"]

    def test_invalid_kind_list_falls_back(self, tmp_path):
        _write_settings(str(tmp_path), {"xml_in_view_kinds": "visu"})
        settings = load_project_settings(str(tmp_path))
        assert settings["xml_in_view_kinds"] == ["visu"]

    def test_empty_kind_list_is_respected(self, tmp_path):
        _write_settings(str(tmp_path), {"xml_in_view_kinds": []})
        settings = load_project_settings(str(tmp_path))
        assert settings["xml_in_view_kinds"] == []


class TestSaveRoundTrip:
    def test_round_trip_preserves_new_keys(self, tmp_path):
        project_root = str(tmp_path)
        saved = save_project_settings(
            project_root,
            {"sync_mode": "text-first", "xml_in_view_kinds": ["Visu", "textlist"]},
        )
        assert saved["sync_mode"] == SYNC_MODE_TEXT_FIRST
        assert saved["xml_in_view_kinds"] == ["visu", "textlist"]
        loaded = load_project_settings(project_root)
        assert loaded["sync_mode"] == SYNC_MODE_TEXT_FIRST
        assert loaded["xml_in_view_kinds"] == ["visu", "textlist"]

    def test_save_without_new_keys_writes_defaults(self, tmp_path):
        project_root = str(tmp_path)
        saved = save_project_settings(project_root, {"layout": "project-view"})
        assert saved["sync_mode"] == SYNC_MODE_XML_FIRST
        assert saved["xml_in_view_kinds"] == ["visu"]
        with open(settings_path(project_root), "r") as handle:
            raw = json.load(handle)
        assert raw["sync_mode"] == SYNC_MODE_XML_FIRST


class TestViewRootStorage:
    def _saved_root(self, project_root):
        with open(settings_path(project_root)) as handle:
            return json.load(handle)["view_root"]

    def test_root_inside_the_sync_folder_is_stored_relative(self, tmp_path):
        root = str(tmp_path)
        settings = save_project_settings(root, {"view_root": str(tmp_path / "views" / "st")})
        assert self._saved_root(root) == "views/st"
        assert settings["view_root"] == str(tmp_path / "views" / "st")

    def test_relative_root_survives_a_load_and_save(self, tmp_path):
        root = str(tmp_path)
        _write_settings(root, {"view_root": "views"})
        save_project_settings(root, load_project_settings(root))
        assert self._saved_root(root) == "views"

    def test_root_outside_the_sync_folder_stays_absolute(self, tmp_path):
        root = str(tmp_path / "proj")
        (tmp_path / "proj").mkdir()
        outside = str(tmp_path / "elsewhere")
        save_project_settings(root, {"view_root": outside})
        assert self._saved_root(root) == outside

    def test_no_custom_root_is_stored_as_null(self, tmp_path):
        root = str(tmp_path)
        save_project_settings(root, {})
        assert self._saved_root(root) is None
