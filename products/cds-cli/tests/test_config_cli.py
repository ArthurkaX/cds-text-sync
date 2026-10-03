"""`cts config`: reading and editing the settings layers (offline)."""

import json
import os

import pytest

from cds_cli import main as cli_main
from cds_cli._cli_handlers_config import (
    cmd_config_set,
    cmd_config_show,
    cmd_config_unset,
)
from cds_cli._cli_parser import build_parser
from cds_text_sync.engine import _project_settings as settings_module
from cds_text_sync.engine import _user_defaults as defaults_module


def _write_project(root, data):
    with open(settings_module.settings_path(str(root)), "w") as handle:
        json.dump(data, handle)


def _read_project(root):
    with open(settings_module.settings_path(str(root))) as handle:
        return json.load(handle)


def _read_user_file():
    with open(defaults_module.defaults_path()) as handle:
        return json.load(handle)


def _write_raw_user(text):
    path = defaults_module.defaults_path()
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(text)


@pytest.fixture
def project_root(tmp_path):
    """A sync folder with a version-2 settings file."""
    root = tmp_path / "sync"
    root.mkdir()
    _write_project(root, {"version": settings_module.SETTINGS_VERSION})
    return root


class TestShowTable:
    def test_table_lists_every_key_with_its_source(self, project_root, capsys):
        _write_project(project_root, {"version": 2, "layout": "root-view"})
        cmd_config_set("advanced_debug", "true")

        cmd_config_show(project_root=str(project_root))
        out = capsys.readouterr().out

        assert "key" in out and "source" in out and "class" in out
        assert "advanced_debug" in out and "behavior" in out
        assert "layout" in out and "root-view" in out
        # header carries both layer files and their status
        assert "user defaults:" in out and "project settings:" in out
        assert "(ok, version 2)" in out
        for name in defaults_module.USER_DEFAULT_KEYS:
            assert name in out

    def test_sources_distinguish_code_user_and_project(self, project_root, capsys):
        _write_project(project_root, {"version": 2, "layout": "root-view"})
        cmd_config_set("advanced_debug", "true")

        cmd_config_show(project_root=str(project_root))
        lines = {
            line.split()[0]: line
            for line in capsys.readouterr().out.splitlines()
            if line and not line.startswith(("key", "---", "user ", "project "))
        }

        assert "user" in lines["advanced_debug"]
        assert "project" in lines["layout"]

    def test_missing_project_file_still_shows_code_and_user(self, tmp_path, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()
        cmd_config_set("advanced_debug", "true")

        cmd_config_show(project_root=str(empty))
        out = capsys.readouterr().out

        assert "project settings:" in out and "(missing)" in out
        # the user override is shown even with no project file
        row = next(line for line in out.splitlines() if line.startswith("advanced_debug"))
        assert "true" in row and "user" in row

    def test_version_one_is_flagged_for_migration(self, project_root, capsys):
        _write_project(project_root, {"version": 1, "layout": "root-view"})

        cmd_config_show(project_root=str(project_root))

        assert "will be migrated on next save" in capsys.readouterr().out

    def test_no_project_file_found_from_cwd(self, tmp_path, monkeypatch, capsys):
        start = tmp_path / "no-project"
        start.mkdir()
        monkeypatch.chdir(start)
        if settings_module.find_settings_root(os.getcwd()) is not None:
            pytest.skip("an ancestor of the temp dir holds a cds-text-sync.json")

        cmd_config_show()
        out = capsys.readouterr().out

        assert "no cds-text-sync.json found" in out


class TestShowJson:
    def test_json_has_the_layer_and_settings_shape(self, project_root, capsys):
        _write_project(project_root, {"version": 2, "layout": "root-view"})
        cmd_config_set("advanced_debug", "true")
        capsys.readouterr()  # drop the set's own output

        cmd_config_show(project_root=str(project_root), as_json=True)
        payload = json.loads(capsys.readouterr().out)

        assert set(payload) == {"user_defaults", "project", "settings"}
        assert payload["user_defaults"]["status"] == "ok"
        assert payload["user_defaults"]["overrides"]["advanced_debug"] is True
        assert payload["project"]["status"] == "ok"
        assert payload["project"]["version"] == 2
        entry = payload["settings"]["advanced_debug"]
        assert entry == {"value": True, "source": "user", "class": "behavior"}
        assert payload["settings"]["layout"]["source"] == "project"
        assert payload["settings"]["layout"]["class"] == "format"

    def test_json_reports_an_invalid_user_file(self, project_root, capsys):
        _write_raw_user("{not json")

        cmd_config_show(project_root=str(project_root), as_json=True)
        payload = json.loads(capsys.readouterr().out)

        assert payload["user_defaults"]["status"] == "invalid"
        assert payload["user_defaults"]["error"]
        assert payload["user_defaults"]["overrides"] == {}
        # the project file is unaffected by the broken user layer
        assert payload["project"]["status"] == "ok"


class TestSetUser:
    def test_set_writes_the_override(self, capsys):
        cmd_config_set("advanced_debug", "true")
        result = json.loads(capsys.readouterr().out)

        assert result["layer"] == "user"
        assert _read_user_file()["advanced_debug"] is True

    def test_a_value_equal_to_the_default_is_not_stored(self, capsys):
        cmd_config_set("show_completion_popup", "true")
        result = json.loads(capsys.readouterr().out)

        assert result["value"] is None
        assert "show_completion_popup" not in _read_user_file()

    def test_value_is_parsed_as_json_then_as_a_string(self, capsys):
        cmd_config_set("backup_retention_count", "25")
        cmd_config_set("profile", "astra")
        stored = _read_user_file()

        assert stored["backup_retention_count"] == 25
        assert stored["profile"] == "astra"

    def test_view_root_is_refused(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_config_set("view_root", "/elsewhere")

        assert exc.value.code == 1
        assert "project-specific" in capsys.readouterr().err
        # refused before anything is written
        path = defaults_module.defaults_path()
        assert not os.path.exists(path) or "view_root" not in _read_user_file()

    def test_unknown_key_lists_the_valid_ones(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_config_set("nope", "1")

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Unknown setting" in err
        assert "advanced_debug" in err

    def test_invalid_value_is_refused(self, capsys):
        with pytest.raises(SystemExit):
            cmd_config_set("backup_retention_count", "0")

        assert "Invalid value" in capsys.readouterr().err


class TestSetProject:
    def test_behavior_key_is_pinned_even_when_equal_to_inherited(
        self, project_root, capsys
    ):
        cmd_config_set("advanced_debug", "true")  # user override
        _write_project(project_root, {"version": 2})

        cmd_config_set(
            "advanced_debug", "true", layer="project", project_root=str(project_root)
        )

        # Equal to what it would inherit, so only the explicit pin keeps it.
        assert _read_project(project_root)["advanced_debug"] is True

    def test_format_key_is_written(self, project_root):
        cmd_config_set("sync_mode", "text_first", layer="project", project_root=str(project_root))

        assert _read_project(project_root)["sync_mode"] == "text_first"

    def test_view_root_is_written(self, project_root):
        cmd_config_set("view_root", "/tmp/views", layer="project", project_root=str(project_root))

        assert _read_project(project_root)["view_root"] == "/tmp/views"

    def test_a_missing_project_file_is_an_error(self, tmp_path, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises(SystemExit) as exc:
            cmd_config_set("layout", "root-view", layer="project", project_root=str(empty))

        assert exc.value.code == 1
        assert "No project settings file" in capsys.readouterr().err


class TestUnset:
    def test_user_unset_removes_the_override(self, capsys):
        cmd_config_set("advanced_debug", "true")

        cmd_config_unset("advanced_debug")

        assert "advanced_debug" not in _read_user_file()

    def test_user_unset_without_an_override_says_so(self, capsys):
        cmd_config_unset("advanced_debug")

        assert json.loads(capsys.readouterr().out)["removed"] is False

    def test_project_unset_removes_the_pin(self, project_root, capsys):
        _write_project(project_root, {"version": 2, "advanced_debug": True})

        cmd_config_unset("advanced_debug", layer="project", project_root=str(project_root))

        assert "advanced_debug" not in _read_project(project_root)

    def test_project_unset_on_an_unpinned_key_is_a_no_op(self, project_root, capsys):
        cmd_config_unset("advanced_debug", layer="project", project_root=str(project_root))

        assert json.loads(capsys.readouterr().out)["removed"] is False

    def test_format_key_unset_is_refused(self, project_root, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_config_unset("layout", layer="project", project_root=str(project_root))

        assert exc.value.code == 1
        assert "format key" in capsys.readouterr().err


class TestRegistration:
    def test_parser_exposes_the_subcommands(self):
        parser = build_parser()

        show = parser.parse_args(["config", "show", "--json"])
        assert show.command == "config" and show.config_action == "show"
        assert show.config_json is True

        set_args = parser.parse_args(["config", "set", "sync_mode", "text_first"])
        assert set_args.config_layer == "user"  # default layer
        assert set_args.value == "text_first"

        project = parser.parse_args(
            ["config", "unset", "advanced_debug", "--project", "--project-root", "x"]
        )
        assert project.config_layer == "project"
        assert project.project_root == "x"

    def test_main_dispatches_config_show(self, project_root, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            ["cts", "config", "show", "--json", "--project-root", str(project_root)],
        )

        cli_main.main()
        payload = json.loads(capsys.readouterr().out)

        assert payload["project"]["status"] == "ok"
