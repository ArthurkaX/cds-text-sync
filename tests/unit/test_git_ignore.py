# -*- coding: utf-8 -*-
"""The objects a user's git ignore rules leave out of export, import and the
dirty check (``engine/_git_ignore.py`` and its callers)."""

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from cds_text_sync.engine._git_ignore import ignored_guids, ignored_paths
from cds_text_sync.engine._project_model import ProjectModel, ProjectNode
from cds_text_sync.engine.engine_cli import _drop_ignored, _drop_ignored_files
from cds_text_sync.engine.folder_writer import FolderWriter

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

_APPLICATION = "639b491f-5557-464c-af91-1471bac9f549"
_FOLDER = "738bea1e-99bb-4f04-90bb-a7a567e74e3a"
_TASK_CONFIG = "Dev/PLC Logic/Application/Task Configuration"
_PROFILE = {"guid_aliases": {"application": [_APPLICATION]}}


def _git(root, *args):
    subprocess.run(["git", "-C", str(root)] + list(args), check=True, capture_output=True)


def _repo(tmp_path, exclude):
    _git(tmp_path, "init", "-q")
    with open(os.path.join(str(tmp_path), ".git", "info", "exclude"), "w") as handle:
        handle.write(exclude + "\n")
    return tmp_path


def _write(root, relative, text="x"):
    path = os.path.join(str(root), relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _node(model, guid, name, path, parent=None, node_type=_FOLDER):
    node = ProjectNode(guid, name, node_type, parent)
    node.display_path = path
    element = ET.Element("Single", {"Name": "Object"})
    ET.SubElement(element, "Single", {"Name": "Data"}).text = name
    node.entry_element = element
    model.add_node(node)


def _model():
    """Dev / PLC Logic / Application / {Task Configuration / MainTask, POU}"""
    model = ProjectModel()
    _node(model, "dev", "Dev", [])
    _node(model, "plc", "PLC Logic", ["Dev"], "dev")
    _node(model, "app", "Application", ["Dev", "PLC Logic"], "plc", _APPLICATION)
    app = ["Dev", "PLC Logic", "Application"]
    _node(model, "tc", "Task Configuration", app, "app")
    _node(model, "task", "MainTask", app + ["Task Configuration"], "tc")
    _node(model, "pou", "POU", app, "app")
    return model


def test_outside_a_work_tree_nothing_is_ignored(tmp_path):
    assert ignored_paths(str(tmp_path), ["a.xml"]) == set()


def test_rules_match_files_git_tracks(tmp_path):
    root = _repo(tmp_path, "Task Configuration/")
    _write(root, _TASK_CONFIG + "/MainTask.xml")
    _write(root, "Dev/PLC Logic/Application/POU.xml")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "lead")

    assert ignored_paths(
        str(root), [_TASK_CONFIG + "/MainTask.xml", "Dev/PLC Logic/Application/POU.xml"]
    ) == set([_TASK_CONFIG + "/MainTask.xml"])


def test_a_folder_rule_takes_the_folder_and_what_is_below_it(tmp_path):
    root = _repo(tmp_path, "Task Configuration/")
    assert ignored_guids(str(root), _PROFILE, _model()) == set(["tc", "task"])


def test_a_rule_over_the_application_is_refused(tmp_path):
    root = _repo(tmp_path, "Application/")
    with pytest.raises(RuntimeError, match="cover the application"):
        ignored_guids(str(root), _PROFILE, _model())


def test_a_rule_that_keeps_what_is_below_an_ignored_object_is_refused(tmp_path):
    root = _repo(tmp_path, "**/Task Configuration/.cds-object.xml")
    with pytest.raises(RuntimeError, match="MainTask.xml"):
        ignored_guids(str(root), _PROFILE, _model())


def test_export_leaves_the_files_and_entries_of_ignored_objects(tmp_path):
    root = _repo(tmp_path, "Task Configuration/")
    views = str(root / "view")
    dump = str(root / ".dump")
    os.makedirs(dump)
    task_path = "Dev/PLC Logic/Application/Task Configuration/MainTask.xml"
    _write(views, task_path, "lead's task")
    # A file of an object only the lead's project has.
    _write(views, "Dev/PLC Logic/Application/Task Configuration/NewTask.st", "lead")
    task_entry = {"guid": "task", "name": "MainTask", "xml_path": task_path, "hash": "h"}
    with open(os.path.join(dump, "manifest.json"), "w") as handle:
        json.dump({"view_root": "view", "entries": [task_entry]}, handle)
    model = _model()

    FolderWriter(
        views,
        dump,
        profile={"projections": [{"id": "st", "format": "st"}]},
        remove_orphans=True,
        ignored_guids=ignored_guids(views, _PROFILE, model),
    ).write(model)

    with open(os.path.join(views, task_path), encoding="utf-8") as handle:
        assert handle.read() == "lead's task"
    assert os.path.isfile(
        os.path.join(views, "Dev/PLC Logic/Application/Task Configuration/NewTask.st")
    )
    assert not os.path.exists(
        os.path.join(views, "Dev/PLC Logic/Application/Task Configuration/.cds-object.xml")
    )
    assert os.path.isfile(os.path.join(views, "Dev/PLC Logic/Application/POU.xml"))
    with open(os.path.join(dump, "manifest.json"), encoding="utf-8") as handle:
        entries = json.load(handle)["entries"]
    assert task_entry in entries
    assert "tc" not in [entry["guid"] for entry in entries]


def test_compare_and_import_drop_ignored_objects():
    diff = {
        "modified": ["a", "b"],
        "added": ["c"],
        "deleted": ["b"],
        "unsupported_projection_changes": {"b": ["x.st"]},
        "library_manager_changes": {"objects": ["b"], "hint": "h"},
        "library_resolution": {"drift": []},
    }
    assert _drop_ignored(diff, set(["b"])) == {
        "modified": ["a"],
        "added": ["c"],
        "deleted": [],
        "unsupported_projection_changes": {},
        "library_resolution": {"drift": []},
    }


def test_dirty_check_drops_ignored_files(tmp_path):
    root = _repo(tmp_path, "Task Configuration/")
    report = {
        "dirty": [
            {"guid": "task", "path": _TASK_CONFIG + "/MainTask.st"},
            {"guid": "pou", "path": "Dev/PLC Logic/Application/POU.st"},
        ],
        "orphans": [{"path": _TASK_CONFIG + "/NewTask.st"}],
    }
    manifest = {"entries": [{"guid": "task", "xml_path": _TASK_CONFIG + "/MainTask.xml"}]}

    _drop_ignored_files(report, str(root), manifest)

    assert report == {
        "dirty": [{"guid": "pou", "path": "Dev/PLC Logic/Application/POU.st"}],
        "orphans": [],
    }
