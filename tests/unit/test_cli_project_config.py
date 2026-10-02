# -*- coding: utf-8 -*-
"""
test_cli_project_config.py - One reader for cds-text-sync.json.

The CLI used to parse the file itself, from the current directory only, and to
fall back to nothing at all when it could not. These pin the unified loader:
the CLI and the engine read one file the same way, the search walks up to the
sync root, and a file that cannot be read is reported rather than swallowed.
"""

import json
import os
from pathlib import Path

import pytest

from cds_text_sync.engine._project_settings import (
    SETTINGS_INVALID,
    SETTINGS_MISSING,
    SETTINGS_OK,
    default_project_settings,
    find_settings_root,
    load_project_settings,
    read_project_settings,
    settings_path,
)

from cds_cli import _cli_io


def _write_settings(root, data):
    with open(settings_path(str(root)), "w") as handle:
        json.dump(data, handle)


def _write_raw(root, text):
    Path(settings_path(str(root))).write_text(text, encoding="utf-8")


@pytest.fixture
def sync_root(tmp_path):
    """A sync folder whose settings name a profile that carries app defaults."""
    root = tmp_path / "sync"
    root.mkdir()
    _write_settings(
        root,
        {
            "layout": "project-view",
            "profile": "astra",
            "sync_mode": "text_first",
            "version": 1,
        },
    )
    return root


# -- One reader, one interpretation -------------------------------------------


class TestCliAndEngineAgree:
    def test_cli_returns_what_the_engine_reads(self, sync_root, monkeypatch):
        monkeypatch.chdir(sync_root)
        cli_settings, _profile = _cli_io._load_project_config()
        assert cli_settings == load_project_settings(str(sync_root))

    def test_profile_named_by_the_file_is_resolved(self, sync_root, monkeypatch):
        monkeypatch.chdir(sync_root)
        cli_settings, profile = _cli_io._load_project_config()
        assert cli_settings["profile"] == "astra"
        assert profile["default_app_name"] == "Application"

    def test_settings_normalization_is_the_engine_s(self, sync_root, monkeypatch):
        """The CLI gets the engine's coercion, not the file's raw JSON."""
        monkeypatch.chdir(sync_root)
        cli_settings, _profile = _cli_io._load_project_config()
        assert cli_settings["sync_mode"] == "text_first"
        assert cli_settings["xml_in_view_kinds"] == ["visu"]


class TestSearchRule:
    def test_subdirectory_finds_the_sync_root(self, sync_root, monkeypatch):
        subdir = sync_root / "project-view" / "PLC"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        cli_settings, profile = _cli_io._load_project_config()

        assert find_settings_root(os.getcwd()) == str(sync_root)
        assert cli_settings == load_project_settings(str(sync_root))
        assert profile["default_app_name"] == "Application"

    def test_nearest_settings_file_wins(self, tmp_path, monkeypatch):
        outer = tmp_path / "outer"
        inner = outer / "inner"
        inner.mkdir(parents=True)
        _write_settings(outer, {"profile": "default"})
        _write_settings(inner, {"profile": "astra"})
        monkeypatch.chdir(inner)

        assert find_settings_root(os.getcwd()) == str(inner)

    def test_no_file_anywhere_reports_none(self, tmp_path, monkeypatch):
        start = tmp_path / "empty"
        start.mkdir()
        monkeypatch.chdir(start)
        if find_settings_root(os.getcwd()) is not None:
            pytest.skip("an ancestor of the temp dir holds a cds-text-sync.json")
        assert find_settings_root(os.getcwd()) is None


class TestMissingFile:
    def test_engine_calls_it_missing_and_returns_defaults(self, tmp_path):
        settings, status, error = read_project_settings(str(tmp_path))
        assert status == SETTINGS_MISSING
        assert error == ""
        assert settings == default_project_settings()

    def test_cli_treats_it_as_normal(self, tmp_path, monkeypatch):
        root = tmp_path / "empty"
        root.mkdir()
        monkeypatch.chdir(root)
        if find_settings_root(os.getcwd()) is not None:
            pytest.skip("an ancestor of the temp dir holds a cds-text-sync.json")

        settings, profile = _cli_io._load_project_config()

        assert settings == default_project_settings()
        # The default profile is loaded, but it carries no app defaults, so the
        # net effect matches the old "no file, no profile" behaviour.
        assert profile.get("default_app_name") is None


# -- A broken file is reported, not swallowed ---------------------------------


class TestBrokenFile:
    def test_invalid_json_is_reported_with_the_path(self, sync_root, monkeypatch, capsys):
        _write_raw(sync_root, "{not json")
        monkeypatch.chdir(sync_root)

        settings, profile = _cli_io._load_project_config()

        captured = capsys.readouterr()
        assert "[ERROR]" in captured.err
        assert "cds-text-sync.json" in captured.err
        assert "Traceback" not in captured.err
        assert settings == default_project_settings()
        assert profile is None

    def test_engine_reports_invalid_status(self, sync_root, capsys):
        _write_raw(sync_root, "{not json")

        settings, status, error = read_project_settings(str(sync_root), warn=False)

        assert status == SETTINGS_INVALID
        assert error
        assert settings == default_project_settings()
        assert capsys.readouterr().out == ""

    def test_engine_still_warns_when_asked(self, sync_root, capsys):
        _write_raw(sync_root, "{not json")

        settings = load_project_settings(str(sync_root))

        assert settings == default_project_settings()
        assert "Warning:" in capsys.readouterr().out

    def test_an_unusable_layout_is_silenced_too(self, sync_root, capsys):
        """warn=False means no warning at all, not just no warning for JSON."""
        _write_settings(sync_root, {"layout": "not-a-layout"})

        settings, status, _error = read_project_settings(str(sync_root), warn=False)

        assert status == SETTINGS_OK
        assert settings["layout"] == "project-view"
        assert capsys.readouterr().out == ""

    def test_an_unusable_layout_still_warns_when_asked(self, sync_root, capsys):
        _write_settings(sync_root, {"layout": "not-a-layout"})

        settings = load_project_settings(str(sync_root))

        assert settings["layout"] == "project-view"
        assert "Warning:" in capsys.readouterr().out

    def test_non_object_json_no_longer_raises(self, sync_root, monkeypatch, capsys):
        _write_raw(sync_root, "[1, 2]")
        monkeypatch.chdir(sync_root)

        settings, status, error = read_project_settings(str(sync_root), warn=False)
        assert status == SETTINGS_INVALID
        assert "not an object" in error
        assert settings == default_project_settings()

        cli_settings, profile = _cli_io._load_project_config()
        assert cli_settings == default_project_settings()
        assert profile is None
        assert "Traceback" not in capsys.readouterr().err


class TestProfileDefaults:
    def test_defaults_are_filled_in(self):
        params = _cli_io._apply_profile_defaults(
            {}, {"default_app_name": "Application", "plc_app_path": "PLC"}
        )
        assert params == {"app": "Application", "app_dir": "PLC"}

    def test_explicit_params_win(self):
        params = _cli_io._apply_profile_defaults(
            {"app": "Other"}, {"default_app_name": "Application", "plc_app_path": "PLC"}
        )
        assert params["app"] == "Other"
        assert params["app_dir"] == "PLC"

    def test_no_profile_changes_nothing(self):
        assert _cli_io._apply_profile_defaults({}, None) == {}

    def test_a_profile_without_the_keys_changes_nothing(self):
        assert _cli_io._apply_profile_defaults({}, {"name": "x"}) == {}


def test_statuses_are_distinct():
    assert SETTINGS_MISSING != SETTINGS_OK
    assert SETTINGS_OK != SETTINGS_INVALID
