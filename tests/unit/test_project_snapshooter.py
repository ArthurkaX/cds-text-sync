import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRIDGE = os.path.join(ROOT, "src", "ide_bridge")
if BRIDGE not in sys.path:
    sys.path.insert(0, BRIDGE)

import importlib.machinery
import importlib.util


MODULE_PATH = os.path.join(BRIDGE, "project_snapshooter.py")
loader = importlib.machinery.SourceFileLoader("project_snapshooter", MODULE_PATH)
spec = importlib.util.spec_from_loader(loader.name, loader)
ps = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = ps
loader.exec_module(ps)


class DummyProject:
    pass


class DummyText:
    def __init__(self, text):
        self.text = text


class DummyObject:
    def __init__(self, name, declaration=None, type_guid=""):
        self.name = name
        self.type = type_guid
        if declaration is not None:
            self.textual_declaration = DummyText(declaration)


class DummyProjectWithChildren:
    def __init__(self, children):
        self.children = children

    def get_children(self, recursive=False):
        return self.children


def test_compare_reports_value_and_type_changes():
    saved = {
        "vars": [
            {"path": "GVL.a", "type": "UINT", "value": "UINT#1", "read_ok": True},
            {"path": "GVL.b", "type": "BOOL", "value": "FALSE", "read_ok": True},
        ]
    }
    current = {
        "vars": [
            {"path": "GVL.a", "type": "DINT", "value": "DINT#2", "read_ok": True},
        ]
    }

    report = ps.compare(saved, current=current)

    assert report["identical"] is False
    assert report["missing"] == ["GVL.b"]
    assert report["type_changed"] == [{"path": "GVL.a", "was": "UINT", "now": "DINT"}]
    assert report["value_changed"] == [{"path": "GVL.a", "was": "UINT#1", "now": "DINT#2"}]


def test_restore_dry_run_warns_on_type_mismatch(monkeypatch):
    monkeypatch.setattr(
        ps,
        "take",
        lambda paths, project=None: {
            "vars": [
                {"path": "GVL.a", "type": "DINT", "value": "DINT#1", "read_ok": True},
            ]
        },
    )
    saved = {
        "vars": [
            {"path": "GVL.a", "type": "UINT", "value": "UINT#7", "read_ok": True},
        ]
    }

    report = ps.restore(saved, apply=False, project=DummyProject())

    assert report["written"] == 0
    assert report["would_write"] == 1
    assert report["skipped"] == 0
    assert report["warnings"] == [
        {"path": "GVL.a", "warning": "type mismatch: UINT -> DINT"}
    ]


def test_restore_apply_writes_eligible_values(monkeypatch):
    monkeypatch.setattr(
        ps,
        "take",
        lambda paths, project=None: {
            "vars": [
                {"path": "GVL.a", "type": "UINT", "value": "UINT#1", "read_ok": True},
            ]
        },
    )

    written_items = []

    def fake_write(_project, items, raw_value=False):
        written_items.extend(items)
        return {
            "results": [
                {"name": "GVL.a", "written": True, "write_error": ""},
            ],
            "written": 1,
        }

    monkeypatch.setattr(ps._helpers, "write_variables_impl", fake_write)
    saved = {
        "vars": [
            {"path": "GVL.a", "type": "UINT", "value": "UINT#7", "read_ok": True},
        ]
    }

    report = ps.restore(saved, apply=True, project=DummyProject())

    assert written_items == [{"name": "GVL.a", "value": "UINT#7"}]
    assert report["written"] == 1
    assert report["would_write"] == 0
    assert report["skipped"] == 0


def test_default_preset_path_uses_sync_folder(monkeypatch):
    monkeypatch.setattr(ps, "_read_project_property", lambda _project, key: r"C:\Sync" if key == "cds-sync-folder" else "")

    path = ps._default_preset_path(DummyProject(), "speed tuning")

    assert path == r"C:\Sync\.dump\snapshots\speed-tuning.json"


def test_ensure_default_snapshot_dir_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "_read_project_property", lambda _project, key: str(tmp_path) if key == "cds-sync-folder" else "")

    directory = ps._ensure_default_snapshot_dir(DummyProject())

    assert directory == os.path.join(str(tmp_path), ".dump", "snapshots")
    assert os.path.isdir(directory)


def test_build_tree_uses_exported_snapshooter_json(monkeypatch, tmp_path):
    ps._SNAPSHOOTER_ROWS_BY_PATH = {}
    monkeypatch.setattr(ps, "_sync_folder", lambda _project: str(tmp_path))
    textual = DummyObject("GVL_Routing", "VAR_GLOBAL\n    speed : INT;\nEND_VAR\n")
    gvl_by_guid = DummyObject("GVL_HMI", type_guid="ffbfa93a-b94d-45fc-a329-229860183b1d")
    method = DummyObject("Save", "METHOD Save\nVAR_INPUT\nEND_VAR\n")
    resource = DummyObject("Logo.png")
    project = DummyProjectWithChildren([textual, gvl_by_guid, method, resource])
    exported_objects = []

    def fake_export(_project, objects, output_path):
        exported_objects.extend(objects)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("<IDE />")
        return True

    def fake_engine(args, project_root=None, dump_root=None, warning_fn=None):
        output_path = args[args.index("--output") + 1]
        data = {
            "rows": [
                {"path": "GVL_Routing.speed", "type": "INT", "leaf": True, "scope": "VAR_GLOBAL"},
                {"path": "GVL_Routing.partCount", "type": "UINT", "leaf": True, "scope": "VAR_GLOBAL"},
            ],
            "stats": {"owners": 1, "leaves": 2, "readable": 2},
        }
        with open(output_path, "w", encoding="utf-8") as handle:
            import json
            json.dump(data, handle)
        return True

    monkeypatch.setattr(ps.ide_export_snapshot, "export_selected_snapshot", fake_export)
    monkeypatch.setattr(ps.ide_runtime_common, "run_external_engine", fake_engine)

    rows = ps.build_tree(project=project)
    paths = sorted(r["path"] for r in rows if r.get("leaf"))

    assert paths == [
        "GVL_Routing.partCount",
        "GVL_Routing.speed",
    ]
    assert exported_objects == [textual, gvl_by_guid]
    assert os.path.exists(os.path.join(str(tmp_path), ".dump", "IDE.xml"))
    assert os.path.exists(os.path.join(str(tmp_path), ".dump", "snapshots", "variable_tree.json"))


def test_build_tree_requires_sync_folder(monkeypatch):
    ps._SNAPSHOOTER_ROWS_BY_PATH = {}
    monkeypatch.setattr(ps, "_sync_folder", lambda _project: "")

    try:
        ps.build_tree(project=DummyProject())
    except RuntimeError as exc:
        assert "cds-sync-folder" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_snapshot_default_label_adds_timestamp(monkeypatch):
    monkeypatch.setattr(ps.time, "strftime", lambda _format: "2026-06-09_153012")

    label = ps._snapshot_default_label("GVL_Routing.partCount")

    assert label == "GVL_Routing.partCount_2026-06-09_153012"


def test_resolve_relative_preset_path_uses_sync_folder(monkeypatch):
    monkeypatch.setattr(ps, "_read_project_property", lambda _project, key: r"C:\Sync" if key == "cds-sync-folder" else "")

    path = ps._resolve_preset_path(DummyProject(), "presets/my.json", "ignored")

    assert path == r"C:\Sync\presets/my.json"


def test_tui_tree_renders_requested_frame():
    rows = [
        {"path": "GVL_Routing.speed", "type": "INT", "value": "1000", "leaf": True, "scope": "VAR_GLOBAL"},
        {"path": "GVL_Routing.partCount", "type": "UINT", "value": "42", "leaf": True, "scope": "VAR_GLOBAL"},
    ]
    root = ps.build_tui_tree(rows, app="Application")
    root.expanded = True
    frame = ps.render_tui(root, set(), project_name="fio-sorting-weight", app="Application")

    assert "Snapshooter :: fio-sorting-weight :: Application" in frame
    assert "[ ]   ▶ GVL_Routing" in frame
    assert "Selected: 0/2 leaves" in frame
    assert "[s]ave [l]oad [d]iff [/]search [q]uit" in frame


def test_tui_toggle_branch_selects_all_leaf_paths():
    rows = [
        {"path": "GVL_Routing.speed", "type": "INT", "value": "1000", "leaf": True, "scope": "VAR_GLOBAL"},
        {"path": "GVL_Routing.partCount", "type": "UINT", "value": "42", "leaf": True, "scope": "VAR_GLOBAL"},
    ]
    root = ps.build_tui_tree(rows, app="Application")
    branch = root.children[0]
    selected = set()

    ps._toggle_node(branch, selected)

    assert selected == {"GVL_Routing.speed", "GVL_Routing.partCount"}
    assert ps._checkbox(branch, selected) == "[x]"


def test_take_skips_excluded_leaves(monkeypatch):
    rows = [
        {"path": "GVL_Live.a", "type": "INT", "leaf": True, "owner": "GVL_Live"},
        {"path": "GVL_Diag.b", "type": "UINT", "leaf": True, "owner": "GVL_Diag", "excluded_from_build": True},
        {"path": "GVL_Diag.c", "type": "BOOL", "leaf": True, "owner": "GVL_Diag", "excluded_from_build": True},
    ]
    monkeypatch.setattr(ps, "_rows_for_paths", lambda _project, paths: [dict(r) for r in rows])
    read_names = []

    def fake_read_variables_impl(_project, names):
        read_names.extend(names)
        return {
            "results": [
                {"name": name, "value": "INT#42", "read_ok": True}
                for name in names
            ]
        }

    monkeypatch.setattr(ps._helpers, "read_variables_impl", fake_read_variables_impl)

    doc = ps.take(project=DummyProject())

    assert sorted(read_names) == ["GVL_Live.a"]
    variables = {v["path"]: v for v in doc["variables"]}
    assert variables["GVL_Live.a"]["read_ok"] is True
    assert variables["GVL_Live.a"]["value"] == "INT#42"
    for path in ("GVL_Diag.b", "GVL_Diag.c"):
        assert variables[path]["read_ok"] is False
        assert variables[path]["value"] == ""
        assert variables[path]["read_error"] == "excluded from build"


def test_take_with_explicit_excluded_path_skips_read(monkeypatch):
    rows = [
        {"path": "GVL_Excluded.x", "type": "INT", "leaf": True, "excluded_from_build": True},
    ]
    ps._SNAPSHOOTER_ROWS_BY_PATH = {}
    monkeypatch.setattr(ps, "_rows_for_paths", lambda _project, paths: [dict(r) for r in rows])
    read_names = []

    def fake_read(_project, names):
        read_names.extend(names)
        return {"results": []}

    monkeypatch.setattr(ps._helpers, "read_variables_impl", fake_read)
    doc = ps.take(paths=["GVL_Excluded.x"], project=DummyProject())

    assert read_names == []
    var = doc["variables"][0]
    assert var["read_ok"] is False
    assert var["read_error"] == "excluded from build"


def test_build_tui_tree_marks_excluded_leaf():
    rows = [
        {"path": "GVL_Included.a", "type": "INT", "value": "7", "leaf": True, "scope": "VAR_GLOBAL"},
        {"path": "GVL_Excluded.b", "type": "UINT", "value": "0", "leaf": True, "scope": "VAR_GLOBAL", "excluded_from_build": True},
    ]
    root = ps.build_tui_tree(rows, app="Application")
    leaves = {leaf.path: leaf for leaf in root.leaves()}
    assert leaves["GVL_Included.a"].excluded_from_build is False
    assert leaves["GVL_Excluded.b"].excluded_from_build is True
