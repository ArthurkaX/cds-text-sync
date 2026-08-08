# -*- coding: utf-8 -*-
"""
offline_regression.py - Minimal offline regression checks for engine_cli flow.
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURE_DIR = os.path.join(ROOT_DIR, "tests", "fixtures", "offline_engine", "basic_case")
ENGINE_DIR = os.path.join(
    ROOT_DIR, "products", "cds-text-sync", "src", "cds_text_sync", "engine"
)
ENGINE_CLI = os.path.join(ENGINE_DIR, "engine_cli.py")


class RegressionFailure(Exception):
    pass


@contextlib.contextmanager
def _engine_on_path():
    """Put the engine dir on sys.path for the flat-import block, then remove it.

    The engine modules import each other flat (``from _project_model import ...``),
    so a scenario that drives them directly must prepend the dir first. This
    replaces the hand-rolled insert/try/finally that was repeated per scenario.
    """
    sys.path.insert(0, ENGINE_DIR)
    try:
        yield
    finally:
        if sys.path and sys.path[0] == ENGINE_DIR:
            del sys.path[0]


def _run(args, expect_code=0):
    cmd = [sys.executable, ENGINE_CLI] + args
    completed = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True)
    if completed.returncode != expect_code:
        raise RegressionFailure(
            "Command failed: {0}\nexit={1} expected={2}\nstdout:\n{3}\nstderr:\n{4}".format(
                " ".join(cmd),
                completed.returncode,
                expect_code,
                completed.stdout,
                completed.stderr,
            )
        )
    return completed


def _read_json(path):
    with open(path, "r") as handle:
        return json.load(handle)


def _write_json(path, data):
    with open(path, "w") as handle:
        json.dump(data, handle, indent=2)


def _normalize_manifest(data):
    normalized = {
        "ns": data.get("ns", ""),
        "entries": [],
    }
    for entry in data.get("entries", []):
        item = dict(entry)
        normalized["entries"].append(item)
    return normalized


def _normalize_xml(path):
    root = ET.parse(path).getroot()
    return ET.tostring(root, encoding="unicode")


def _guid_texts(path):
    root = ET.parse(path).getroot()
    guids = []
    for elem in root.iter():
        if elem.attrib.get("Name") == "Guid" and elem.text:
            guids.append(elem.text.strip().lower())
    return guids


def _local(tag):
    return tag.split("}", 1)[-1]


def _native_create_guids(path):
    """Guids of objects emitted as <CreateNativeObject> native-create entries.

    A brand-new object present on disk but absent from the IDE is created
    natively: its full object XML lives as a string inside <NativeXml>, so it
    must be parsed separately -- _guid_texts() walks parsed elements and cannot
    see a guid that sits inside element text.
    """
    root = ET.parse(path).getroot()
    guids = []
    for elem in root.iter():
        if _local(elem.tag) != "CreateNativeObject":
            continue
        for child in elem:
            if _local(child.tag) != "NativeXml" or not child.text:
                continue
            try:
                inner = ET.fromstring(child.text)
            except ET.ParseError:
                continue
            for node in inner.iter():
                if node.attrib.get("Name") == "Guid" and node.text:
                    guids.append(node.text.strip().lower())
    return guids


def _assert_equal(actual, expected, label):
    if actual != expected:
        raise RegressionFailure(
            "Mismatch in {0}\nactual: {1}\nexpected: {2}".format(label, actual, expected)
        )


def _replace_in_file(path, old, new):
    with open(path, "r") as handle:
        content = handle.read()
    if old not in content:
        raise RegressionFailure("Text not found in {0}: {1}".format(path, old))
    with open(path, "w") as handle:
        handle.write(content.replace(old, new, 1))


def _write_text(path, content):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(path, "w") as handle:
        handle.write(content)


def _add_view_object(views_path, dump_path):
    source_view = os.path.join(views_path, "Device", "Application", "PLC_PRG.xml")
    added_view = os.path.join(views_path, "Device", "Application", "PLC_AUX.xml")
    shutil.copyfile(source_view, added_view)
    _replace_in_file(
        added_view,
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    _replace_in_file(added_view, "PLC_PRG", "PLC_AUX")
    _replace_in_file(added_view, "x := 1;", "x := 10;")

    manifest_path = os.path.join(dump_path, "manifest.json")
    manifest = _read_json(manifest_path)
    source_entry = manifest["entries"][0]
    added_entry = {
        "guid": "22222222-2222-2222-2222-222222222222",
        "name": "PLC_AUX",
        "type_guid": "6f9dac99-8de1-4efc-8465-68ac443b7d08",
        "parent_guid": None,
        "xml_path": "Device\\Application\\PLC_AUX.xml",
        "hash": "added-by-regression",
    }
    if source_entry.get("structured_view_guid"):
        added_entry["structured_view_guid"] = source_entry.get("structured_view_guid")
    if source_entry.get("structured_view_single_attrs"):
        added_entry["structured_view_single_attrs"] = source_entry.get("structured_view_single_attrs")
    manifest["entries"].append(added_entry)
    _write_json(manifest_path, manifest)


def _scenario_baseline(work_dir):
    """Baseline export/compare/validate plus resources and modified-diff patches."""
    project_root = os.path.join(work_dir, "project")
    os.makedirs(project_root)
    snapshot_path = os.path.join(project_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), snapshot_path)
    views_path = os.path.join(project_root, ".dump", "views")
    dump_path = os.path.join(project_root, ".dump")

    _run(["export", "--project-root", project_root, "--snapshot", snapshot_path, "--views", views_path])

    manifest = _normalize_manifest(_read_json(os.path.join(dump_path, "manifest.json")))
    expected_manifest = _read_json(os.path.join(FIXTURE_DIR, "expected_manifest.json"))
    _assert_equal(manifest, expected_manifest, "manifest")

    clean_compare_path = os.path.join(dump_path, "compare_clean.json")
    _run(["compare", "--project-root", project_root, "--snapshot", snapshot_path, "--views", views_path, "--report", clean_compare_path])
    _assert_equal(
        _read_json(clean_compare_path),
        _read_json(os.path.join(FIXTURE_DIR, "expected_compare_clean.json")),
        "clean compare report",
    )

    _run(["validate", "--project-root", project_root, "--snapshot", snapshot_path, "--views", views_path])

    resources_report_path = os.path.join(dump_path, "resources_report.json")
    resources_log_path = os.path.join(dump_path, "resources_top.log")
    _run([
        "resources",
        "--project-root", project_root,
        "--snapshot", snapshot_path,
        "--views", views_path,
        "--report", resources_report_path,
        "--log", resources_log_path,
        "--limit", "5",
    ])
    resources_report = _read_json(resources_report_path)
    if resources_report.get("summary", {}).get("object_count", 0) <= 0:
        raise RegressionFailure("resources report did not include objects")
    if not resources_report.get("top"):
        raise RegressionFailure("resources report did not include top objects")
    if not os.path.exists(resources_log_path):
        raise RegressionFailure("resources log was not written")

    exported_view = os.path.join(views_path, "Device", "Application", "PLC_PRG.xml")
    _replace_in_file(exported_view, "x := 1;", "x := 2;")

    modified_compare_path = os.path.join(dump_path, "compare_modified.json")
    _run(["compare", "--project-root", project_root, "--snapshot", snapshot_path, "--views", views_path, "--report", modified_compare_path])
    _assert_equal(
        _read_json(modified_compare_path),
        _read_json(os.path.join(FIXTURE_DIR, "expected_compare_modified.json")),
        "modified compare report",
    )

    _run(["validate", "--project-root", project_root, "--snapshot", snapshot_path, "--views", views_path], expect_code=1)

    patch_path = os.path.join(dump_path, "IMPORT.xml")
    _run(["import", "--project-root", project_root, "--snapshot", snapshot_path, "--views", views_path, "--patch", patch_path])
    _assert_equal(
        _normalize_xml(patch_path),
        _normalize_xml(os.path.join(FIXTURE_DIR, "expected_import_modified.xml")),
        "generated patch",
    )

    empty_selected_patch_path = os.path.join(dump_path, "IMPORT_empty_selected.xml")
    _run([
        "import",
        "--project-root", project_root,
        "--snapshot", snapshot_path,
        "--views", views_path,
        "--patch", empty_selected_patch_path,
        "--filter-guids", "00000000-0000-0000-0000-000000000000",
    ])
    if not os.path.exists(empty_selected_patch_path):
        raise RegressionFailure("empty selected import did not create a safe patch file")
    if _guid_texts(empty_selected_patch_path):
        raise RegressionFailure("empty selected import patch unexpectedly contained object guids")


def _scenario_project_view_layout(work_dir):
    """project-view layout prunes stale managed files, keeps unmanaged ones.

    A stale managed file whose content no longer matches its manifest hash
    counts as locally modified: the default (skip-dirty) export preserves it,
    and only ``--overwrite-dirty`` prunes it.
    """
    project_view_root = os.path.join(work_dir, "project_view_layout")
    os.makedirs(project_view_root)
    project_view_snapshot = os.path.join(project_view_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), project_view_snapshot)
    _run(["export", "--project-root", project_view_root, "--snapshot", project_view_snapshot, "--layout", "project-view"])
    _run(["validate", "--project-root", project_view_root, "--snapshot", project_view_snapshot, "--layout", "project-view"])
    project_view_path = os.path.join(project_view_root, "project-view")
    if not os.path.exists(project_view_path):
        raise RegressionFailure("project-view layout did not create project-view directory")
    unmanaged_path = os.path.join(project_view_path, "README.md")
    stale_managed_path = os.path.join(project_view_path, "Old", "Removed.xml")
    _write_text(unmanaged_path, "keep me")
    project_view_manifest_path = os.path.join(project_view_root, ".dump", "manifest.json")

    def _plant_stale_entry():
        _write_text(stale_managed_path, "<removed />")
        project_view_manifest = _read_json(project_view_manifest_path)
        project_view_manifest["entries"] = [
            entry
            for entry in project_view_manifest["entries"]
            if entry.get("guid") != "33333333-3333-3333-3333-333333333333"
        ]
        project_view_manifest["entries"].append({
            "guid": "33333333-3333-3333-3333-333333333333",
            "name": "Removed",
            "type_guid": "6f9dac99-8de1-4efc-8465-68ac443b7d08",
            "parent_guid": None,
            "xml_path": "Old\\Removed.xml",
            "hash": "stale",
        })
        _write_json(project_view_manifest_path, project_view_manifest)

    # Default (skip-dirty) export preserves the dirty stale file.
    _plant_stale_entry()
    _run(["export", "--project-root", project_view_root, "--snapshot", project_view_snapshot, "--layout", "project-view"])
    if not os.path.exists(unmanaged_path):
        raise RegressionFailure("project-view export removed unmanaged file")
    if not os.path.exists(stale_managed_path):
        raise RegressionFailure("skip-dirty export removed a locally-modified managed file")

    # --overwrite-dirty prunes it (the pre-guard behavior).
    _plant_stale_entry()
    _run(["export", "--project-root", project_view_root, "--snapshot", project_view_snapshot, "--layout", "project-view", "--overwrite-dirty"])
    if not os.path.exists(unmanaged_path):
        raise RegressionFailure("project-view export removed unmanaged file")
    if os.path.exists(stale_managed_path):
        raise RegressionFailure("project-view export kept stale managed file")


def _scenario_root_view_layout(work_dir):
    """root-view layout keeps unmanaged root files and generated dot-folder files."""
    root_view_root = os.path.join(work_dir, "root_view_layout")
    os.makedirs(root_view_root)
    root_view_snapshot = os.path.join(root_view_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), root_view_snapshot)
    root_unmanaged_path = os.path.join(root_view_root, "README.md")
    root_dump_marker_path = os.path.join(root_view_root, ".dump", "keep.marker")
    _write_text(root_unmanaged_path, "keep root")
    _write_text(root_dump_marker_path, "keep dump")
    _run(["export", "--project-root", root_view_root, "--snapshot", root_view_snapshot, "--layout", "root-view"])
    _run(["validate", "--project-root", root_view_root, "--snapshot", root_view_snapshot, "--layout", "root-view"])
    if not os.path.exists(root_unmanaged_path):
        raise RegressionFailure("root-view export removed unmanaged root file")
    if not os.path.exists(root_dump_marker_path):
        raise RegressionFailure("root-view export removed generated dot folder file")


def _scenario_selected_export(work_dir):
    """Filtered export preserves unselected managed files and manifest entries."""
    selected_export_root = os.path.join(work_dir, "selected_export")
    os.makedirs(selected_export_root)
    selected_export_snapshot = os.path.join(selected_export_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), selected_export_snapshot)
    _run(["export", "--project-root", selected_export_root, "--snapshot", selected_export_snapshot, "--layout", "project-view"])
    selected_export_view = os.path.join(selected_export_root, "project-view")
    selected_export_dump = os.path.join(selected_export_root, ".dump")
    unselected_managed_path = os.path.join(selected_export_view, "Keep", "Unselected.xml")
    _write_text(unselected_managed_path, "<keep />")
    selected_manifest_path = os.path.join(selected_export_dump, "manifest.json")
    selected_manifest = _read_json(selected_manifest_path)
    selected_manifest["entries"].append({
        "guid": "44444444-4444-4444-4444-444444444444",
        "name": "Unselected",
        "type_guid": "6f9dac99-8de1-4efc-8465-68ac443b7d08",
        "parent_guid": None,
        "xml_path": "Keep\\Unselected.xml",
        "hash": "unselected",
    })
    _write_json(selected_manifest_path, selected_manifest)
    _run([
        "export",
        "--project-root", selected_export_root,
        "--snapshot", selected_export_snapshot,
        "--layout", "project-view",
        "--filter-guids", "11111111-1111-1111-1111-111111111111",
    ])
    if not os.path.exists(unselected_managed_path):
        raise RegressionFailure("selected export removed unselected managed file")
    selected_manifest_after = _read_json(selected_manifest_path)
    selected_manifest_guids = sorted(entry.get("guid") for entry in selected_manifest_after.get("entries", []))
    if selected_manifest_guids != [
        "11111111-1111-1111-1111-111111111111",
        "44444444-4444-4444-4444-444444444444",
    ]:
        raise RegressionFailure("selected export did not preserve unselected manifest entries")


def _scenario_create_standalone_st(work_dir):
    """New standalone .st files become CreateTextObject creates in parent order."""
    create_st_root = os.path.join(work_dir, "create_st")
    os.makedirs(create_st_root)
    create_st_snapshot = os.path.join(create_st_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), create_st_snapshot)
    _run(["export", "--project-root", create_st_root, "--snapshot", create_st_snapshot, "--view-root", create_st_root])
    stale_projection_path = os.path.join(create_st_root, "Device", "Application", "PLC_PRG.st")
    _write_text(stale_projection_path, "PROGRAM PLC_PRG\nEND_VAR\n")
    new_fb_path = os.path.join(create_st_root, "Device", "Application", "NewFB.st")
    _write_text(
        new_fb_path,
        "FUNCTION_BLOCK NewFB\n"
        "VAR\n"
        "    x : INT;\n"
        "END_VAR\n"
        "\n"
        "// --- implementation ---\n"
        "\n"
        "x := x + 1;\n",
    )
    _write_text(
        os.path.join(create_st_root, "Device", "Application", "NewDut.st"),
        "TYPE NewDut :\n"
        "STRUCT\n"
        "    value : INT;\n"
        "END_STRUCT\n"
        "END_TYPE\n",
    )
    _write_text(
        os.path.join(create_st_root, "Device", "Application", "NewGlobals.st"),
        "VAR_GLOBAL\n"
        "    g_value : INT;\n"
        "END_VAR\n",
    )
    _write_text(
        os.path.join(create_st_root, "Device", "Application", "NewParent.st"),
        "FUNCTION_BLOCK NewParent\n"
        "VAR\n"
        "    enabled : BOOL;\n"
        "END_VAR\n",
    )
    _write_text(
        os.path.join(create_st_root, "Device", "Application", "NewParent.Init.st"),
        "METHOD Init : BOOL\n"
        "VAR_INPUT\n"
        "END_VAR\n"
        "\n"
        "// --- implementation ---\n"
        "\n"
        "Init := enabled;\n",
    )
    create_st_report_path = os.path.join(create_st_root, ".dump", "compare_create_st.json")
    _run([
        "compare",
        "--project-root", create_st_root,
        "--snapshot", create_st_snapshot,
        "--view-root", create_st_root,
        "--report", create_st_report_path,
        "--include-objects",
    ])
    create_st_report = _read_json(create_st_report_path)
    if create_st_report.get("summary", {}).get("added") != 5:
        raise RegressionFailure("new standalone ST files were not reported as the only added objects")
    create_st_objects = create_st_report.get("objects", {}).get("added", [])
    create_st_names = sorted(obj.get("name") for obj in create_st_objects)
    if create_st_names != ["Init", "NewDut", "NewFB", "NewGlobals", "NewParent"]:
        raise RegressionFailure("new standalone ST compare objects were unexpected: {0}".format(create_st_names))
    create_st_patch_path = os.path.join(create_st_root, ".dump", "IMPORT_create_st.xml")
    _run([
        "import",
        "--project-root", create_st_root,
        "--snapshot", create_st_snapshot,
        "--view-root", create_st_root,
        "--patch", create_st_patch_path,
    ])
    create_st_patch = ET.parse(create_st_patch_path).getroot()
    create_entries = [elem for elem in create_st_patch.iter() if elem.tag == "CreateTextObject"]
    if len(create_entries) != 5:
        raise RegressionFailure("new standalone ST did not emit a CreateTextObject instruction")
    create_kinds_by_name = dict((elem.attrib.get("Name"), elem.attrib.get("Kind")) for elem in create_entries)
    if create_kinds_by_name != {
        "NewFB": "pou",
        "NewDut": "dut",
        "NewGlobals": "gvl",
        "NewParent": "pou",
        "Init": "method",
    }:
        raise RegressionFailure("new standalone ST create kinds were unexpected: {0}".format(create_kinds_by_name))
    create_names_in_order = [elem.attrib.get("Name") for elem in create_entries]
    if create_names_in_order.index("NewParent") > create_names_in_order.index("Init"):
        raise RegressionFailure("standalone ST child create was emitted before parent create")
    init_entry = [elem for elem in create_entries if elem.attrib.get("Name") == "Init"][0]
    if init_entry.attrib.get("ParentName") != "NewParent":
        raise RegressionFailure("standalone ST child create did not record parent name")


def _scenario_create_native_xml(work_dir):
    """A new standalone native .xml file becomes a CreateNativeObject create."""
    create_native_root = os.path.join(work_dir, "create_native_xml")
    os.makedirs(create_native_root)
    create_native_snapshot = os.path.join(create_native_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), create_native_snapshot)
    _run(["export", "--project-root", create_native_root, "--snapshot", create_native_snapshot, "--view-root", create_native_root])
    native_xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Single Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}" Method="IArchivable">'
        "<Single Name=\"Object\">"
        "<Single Name=\"Implementation\"><Single Name=\"TextDocument\">"
        '<Single Name="TextBlobForSerialisation">x := 1;</Single>'
        "</Single></Single>"
        "</Single>"
        "</Single>"
    )
    native_xml_path = os.path.join(create_native_root, "Device", "Application", "NewVisu.xml")
    _write_text(native_xml_path, native_xml_content)
    create_native_report_path = os.path.join(create_native_root, ".dump", "compare_create_native.json")
    _run([
        "compare",
        "--project-root", create_native_root,
        "--snapshot", create_native_snapshot,
        "--view-root", create_native_root,
        "--report", create_native_report_path,
        "--include-objects",
    ])
    create_native_report = _read_json(create_native_report_path)
    if create_native_report.get("summary", {}).get("added") != 1:
        raise RegressionFailure("standalone native XML file was not reported as the only added object")
    create_native_objects = create_native_report.get("objects", {}).get("added", [])
    create_native_names = sorted(obj.get("name") for obj in create_native_objects)
    if create_native_names != ["NewVisu"]:
        raise RegressionFailure("standalone native XML compare objects were unexpected: {0}".format(create_native_names))
    create_native_patch_path = os.path.join(create_native_root, ".dump", "IMPORT_create_native.xml")
    _run([
        "import",
        "--project-root", create_native_root,
        "--snapshot", create_native_snapshot,
        "--view-root", create_native_root,
        "--patch", create_native_patch_path,
    ])
    create_native_patch = ET.parse(create_native_patch_path).getroot()
    native_create_entries = [elem for elem in create_native_patch.iter() if elem.tag == "CreateNativeObject"]
    if len(native_create_entries) != 1:
        raise RegressionFailure("standalone native XML did not emit exactly one CreateNativeObject instruction")
    native_entry = native_create_entries[0]
    if native_entry.attrib.get("Path") != "Device/Application/NewVisu.xml":
        raise RegressionFailure("CreateNativeObject Path was unexpected: {0}".format(native_entry.attrib.get("Path")))
    if native_entry.attrib.get("Name") != "NewVisu":
        raise RegressionFailure("CreateNativeObject Name was unexpected: {0}".format(native_entry.attrib.get("Name")))
    native_xml_elem = None
    for child in native_entry:
        if child.tag == "NativeXml":
            native_xml_elem = child
            break
    if native_xml_elem is None:
        raise RegressionFailure("CreateNativeObject did not contain a NativeXml child element")
    if not (native_xml_elem.text or "").strip():
        raise RegressionFailure("CreateNativeObject NativeXml payload was empty")


def _scenario_projection_config(work_dir):
    """Project-settings layout writes/prunes ST projections and reports conflicts."""
    config_layout_root = os.path.join(work_dir, "config_layout")
    os.makedirs(config_layout_root)
    config_layout_snapshot = os.path.join(config_layout_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), config_layout_snapshot)
    _write_json(os.path.join(config_layout_root, "cds-text-sync.json"), {
        "version": 1,
        "layout": "project-view",
        "profile": "default",
        "projections": {"pou_st": {"enabled": True, "kind": "pou", "format": "st"}},
    })
    _run(["export", "--project-root", config_layout_root, "--snapshot", config_layout_snapshot])
    _run(["validate", "--project-root", config_layout_root, "--snapshot", config_layout_snapshot])
    if not os.path.exists(os.path.join(config_layout_root, "project-view")):
        raise RegressionFailure("project settings layout did not create project-view directory")
    projection_path = os.path.join(config_layout_root, "project-view", "Device", "Application", "PLC_PRG.st")
    if not os.path.exists(projection_path):
        raise RegressionFailure("enabled ST projection was not written")
    projection_xml_path = os.path.join(config_layout_root, "project-view", "Device", "Application", "PLC_PRG.xml")
    with open(projection_path, "r") as handle:
        if "x := 1;" not in handle.read():
            raise RegressionFailure("enabled ST projection did not contain textual code")
    with open(projection_xml_path, "r") as handle:
        if "x := 1;" in handle.read():
            raise RegressionFailure("ST projection text was not externalized from XML")
    projection_manifest = _read_json(os.path.join(config_layout_root, ".dump", "manifest.json"))
    if projection_manifest["entries"][0].get("projection_paths") != ["Device\\Application\\PLC_PRG.st"]:
        raise RegressionFailure("enabled ST projection was not recorded in manifest")
    if not projection_manifest["entries"][0].get("projection_hashes", {}).get("Device\\Application\\PLC_PRG.st"):
        raise RegressionFailure("enabled ST projection hash was not recorded in manifest")
    orphan_projection_path = os.path.join(config_layout_root, "project-view", "Device", "Application", "Orphan.st")
    projection_readme_path = os.path.join(config_layout_root, "project-view", "Device", "Application", "README.md")
    _write_text(orphan_projection_path, "PROGRAM Orphan\nEND_VAR\n")
    _write_text(projection_readme_path, "keep projection folder note")
    # Default export preserves hand-authored (unmanaged) projection files.
    _run(["export", "--project-root", config_layout_root, "--snapshot", config_layout_snapshot])
    if not os.path.exists(orphan_projection_path):
        raise RegressionFailure("default export removed a hand-authored ST file")
    # --overwrite-dirty alone must NOT delete orphans (decoupled).
    _run(["export", "--project-root", config_layout_root, "--snapshot", config_layout_snapshot, "--overwrite-dirty"])
    if not os.path.exists(orphan_projection_path):
        raise RegressionFailure("--overwrite-dirty unexpectedly removed an orphan ST file")
    # --remove-orphans opts into deleting unmanaged derived files.
    _run(["export", "--project-root", config_layout_root, "--snapshot", config_layout_snapshot, "--remove-orphans"])
    if os.path.exists(orphan_projection_path):
        raise RegressionFailure("--remove-orphans did not remove the orphan ST file")
    if not os.path.exists(projection_readme_path):
        raise RegressionFailure("projection export removed unmanaged non-projection file")

    projection_objects_report = os.path.join(config_layout_root, ".dump", "projection_objects.json")
    _run([
        "compare",
        "--project-root", config_layout_root,
        "--snapshot", config_layout_snapshot,
        "--report", projection_objects_report,
        "--include-objects",
    ])
    projection_objects = _read_json(projection_objects_report).get("objects", {}).get("unchanged", [])
    if not projection_objects or not projection_objects[0].get("projection_diff"):
        raise RegressionFailure("compare report did not include projection diff metadata")
    _assert_equal(
        projection_objects[0]["projection_diff"].get("path"),
        "Device\\Application\\PLC_PRG.st",
        "projection diff path",
    )

    _replace_in_file(projection_xml_path, "PLC_PRG", "PLC_PRG_XML_EDIT")
    _replace_in_file(projection_path, "x := 1;", "x := 2;")
    projection_conflict_report = os.path.join(config_layout_root, ".dump", "projection_conflict.json")
    _run([
        "compare",
        "--project-root", config_layout_root,
        "--snapshot", config_layout_snapshot,
        "--report", projection_conflict_report,
    ])
    _assert_equal(
        _read_json(projection_conflict_report).get("details", {}).get("projection_conflicts"),
        ["11111111-1111-1111-1111-111111111111"],
        "projection conflict report",
    )
    # Import policy: disk wins and .st is the canonical source of truth.
    # A projection conflict (both XML and .st edited on disk) must NOT abort
    # the import -- it warns and lets the .st text win.
    conflict_patch_path = os.path.join(
        config_layout_root, ".dump", "IMPORT_projection_conflict.xml"
    )
    _run([
        "import",
        "--project-root", config_layout_root,
        "--snapshot", config_layout_snapshot,
        "--patch", conflict_patch_path,
    ], expect_code=0)
    with open(conflict_patch_path, "r") as handle:
        conflict_patch_text = handle.read()
    if "x := 2;" not in conflict_patch_text:
        raise RegressionFailure(
            "projection-conflict patch did not take .st as source of truth "
            "(expected 'x := 2;')"
        )
    if "PLC_PRG_XML_EDIT" in conflict_patch_text:
        raise RegressionFailure(
            "projection-conflict patch leaked the conflicting XML projection "
            "edit (PLC_PRG_XML_EDIT) instead of letting .st win"
        )


def _scenario_full_pou_and_child(work_dir):
    """Full-POU and POU-child ST projections round-trip declaration and body."""
    with _engine_on_path():
        from _project_model import ProjectModel, ProjectNode
        from folder_reader import FolderReader
        from folder_writer import FolderWriter
        from xml_helpers import entry_to_xml
        full_pou_root = os.path.join(work_dir, "full_pou_projection")
        full_pou_view = os.path.join(full_pou_root, "project-view")
        full_pou_dump = os.path.join(full_pou_root, ".dump")
        full_pou_model = ProjectModel()
        full_pou_node = ProjectNode(
            "77777777-7777-7777-7777-777777777777",
            "FB_SAMPLE",
            "6f9dac99-8de1-4efc-8465-68ac443b7d08",
        )
        full_pou_node.entry_element = ET.fromstring(
            '<Single><Single Name="Object">'
            '<Single Name="Implementation"><Single Name="TextDocument">'
            '<Single Name="TextBlobForSerialisation">x := x + 1;</Single>'
            '</Single></Single>'
            '<Single Name="Interface"><Single Name="TextDocument">'
            '<Single Name="TextBlobForSerialisation">FUNCTION_BLOCK FB_SAMPLE\nVAR\n    x : INT;\nEND_VAR</Single>'
            '</Single></Single>'
            '</Single></Single>'
        )
        full_pou_model.add_node(full_pou_node)
        FolderWriter(
            full_pou_view,
            full_pou_dump,
            profile={
                "guid_aliases": {"pou": ["6f9dac99-8de1-4efc-8465-68ac443b7d08"]},
                "projections": [{
                    "id": "pou_st",
                    "kind": "pou",
                    "format": "st",
                }],
            },
            projections={"pou_st": {"enabled": True}},
        ).write(full_pou_model)
        full_pou_st_path = os.path.join(full_pou_view, "FB_SAMPLE.st")
        with open(full_pou_st_path, "r") as handle:
            full_pou_st = handle.read()
        expected_full_pou_st = (
            "FUNCTION_BLOCK FB_SAMPLE\n"
            "VAR\n"
            "    x : INT;\n"
            "END_VAR\n"
            "\n"
            "// --- implementation ---\n"
            "\n"
            "x := x + 1;\n"
        )
        if full_pou_st != expected_full_pou_st:
            raise RegressionFailure("full POU ST projection did not write declaration before implementation")
        _replace_in_file(full_pou_st_path, "x := x + 1;", "x := x + 2;")
        for node in full_pou_model.nodes.values():
            node.xml_text = entry_to_xml(node.entry_element)
        full_pou_folder_model = FolderReader(full_pou_view, full_pou_dump).read()
        full_pou_folder_node = full_pou_folder_model.get_node("77777777-7777-7777-7777-777777777777")
        if "FUNCTION_BLOCK FB_SAMPLE" not in full_pou_folder_node.xml_text:
            raise RegressionFailure("full POU ST projection did not preserve declaration")
        if "x := x + 2;" not in full_pou_folder_node.xml_text:
            raise RegressionFailure("full POU ST projection did not rehydrate implementation")
        _replace_in_file(
            full_pou_st_path,
            "// --- implementation ---",
            "// VAR_OUTPUT\n//     y : INT;\n// END_VAR\n\n// --- implementation ---",
        )
        full_pou_folder_model = FolderReader(full_pou_view, full_pou_dump).read()
        full_pou_folder_node = full_pou_folder_model.get_node("77777777-7777-7777-7777-777777777777")
        if "// VAR_OUTPUT" not in full_pou_folder_node.xml_text:
            raise RegressionFailure("full POU ST projection did not keep commented declaration before marker")
        if "TextBlobForSerialisation\">// VAR_OUTPUT" in full_pou_folder_node.xml_text:
            raise RegressionFailure("full POU ST projection put commented declaration into implementation")

        child_projection_root = os.path.join(work_dir, "child_st_projection")
        child_projection_view = os.path.join(child_projection_root, "project-view")
        child_projection_dump = os.path.join(child_projection_root, ".dump")
        child_projection_model = ProjectModel()
        parent_node = ProjectNode(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "FB",
            "6f9dac99-8de1-4efc-8465-68ac443b7d08",
        )
        parent_node.display_path = ["Device", "Application"]
        parent_node.entry_element = ET.fromstring("<Single />")
        child_node = ProjectNode(
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "FB_Method",
            "f8a58466-d7f6-439f-bbb8-d4600e41d099",
            parent_node.guid,
        )
        child_node.display_path = ["Device", "Application", "FB"]
        child_node.entry_element = ET.fromstring(
            '<Single><Single Name="Object">'
            '<Single Name="Implementation"><Single Name="TextDocument">'
            '<Single Name="TextBlobForSerialisation">FB_Method := TRUE;</Single>'
            '</Single></Single>'
            '<Single Name="Interface"><Single Name="TextDocument">'
            '<Single Name="TextBlobForSerialisation">METHOD FB_Method : BOOL\nVAR_INPUT\nEND_VAR</Single>'
            '</Single></Single>'
            '</Single></Single>'
        )
        child_projection_model.add_node(parent_node)
        child_projection_model.add_node(child_node)
        FolderWriter(
            child_projection_view,
            child_projection_dump,
            profile={
                "guid_aliases": {
                    "pou": ["6f9dac99-8de1-4efc-8465-68ac443b7d08"],
                    "method": ["f8a58466-d7f6-439f-bbb8-d4600e41d099"],
                },
                "projections": [{
                    "id": "pou_child_st",
                    "kinds": ["method"],
                    "format": "st",
                }],
            },
            projections={"pou_child_st": {"enabled": True}},
        ).write(child_projection_model)
        child_st_path = os.path.join(child_projection_view, "Device", "Application", "FB.FB_Method.st")
        child_xml_path = os.path.join(child_projection_view, "Device", "Application", "FB.FB_Method.xml")
        if not os.path.exists(child_st_path):
            raise RegressionFailure("POU child ST projection was not written with a flat path")
        if not os.path.exists(child_xml_path):
            raise RegressionFailure("POU child XML sidecar was not written with a flat path")
        with open(child_st_path, "r") as handle:
            child_st = handle.read()
        if "METHOD FB_Method : BOOL" not in child_st:
            raise RegressionFailure("POU child ST projection did not contain readable method text")
        if "END_METHOD" in child_st:
            raise RegressionFailure("POU child ST projection emitted synthetic END_METHOD")
        with open(child_xml_path, "r") as handle:
            if "FB_Method := TRUE;" in handle.read():
                raise RegressionFailure("POU child ST projection text was not externalized from XML")
        _replace_in_file(child_st_path, "FB_Method := TRUE;", "FB_Method := FALSE;")
        child_folder_model = FolderReader(child_projection_view, child_projection_dump).read()
        child_folder_node = child_folder_model.get_node("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        if "FB_Method := FALSE;" not in child_folder_node.xml_text:
            raise RegressionFailure("POU child ST projection did not rehydrate implementation")


def _scenario_projection_filter_graphical(work_dir):
    """Graphical POUs are excluded from ST projection."""
    with _engine_on_path():
        from _project_model import ProjectModel, ProjectNode
        from folder_writer import FolderWriter
        projection_filter_root = os.path.join(work_dir, "projection_filter")
        projection_filter_view = os.path.join(projection_filter_root, "project-view")
        projection_filter_dump = os.path.join(projection_filter_root, ".dump")
        projection_model = ProjectModel()
        graphical_node = ProjectNode(
            "44444444-4444-4444-4444-444444444444",
            "GRAPHICAL_POU",
            "6f9dac99-8de1-4efc-8465-68ac443b7d08",
        )
        graphical_node.code = "PROGRAM GRAPHICAL_POU\nEND_VAR"
        graphical_node.entry_element = ET.fromstring("<Single />")
        graphical_node.metadata["implementation_kind"] = "graphical"
        projection_model.add_node(graphical_node)
        FolderWriter(
            projection_filter_view,
            projection_filter_dump,
            profile={
                "guid_aliases": {"pou": ["6f9dac99-8de1-4efc-8465-68ac443b7d08"]},
                "projections": [{
                    "id": "pou_st",
                    "kind": "pou",
                    "format": "st",
                    "requires_textual_implementation": True,
                }],
            },
            projections={"pou_st": {"enabled": True}},
        ).write(projection_model)
    if os.path.exists(os.path.join(projection_filter_view, "GRAPHICAL_POU.st")):
        raise RegressionFailure("graphical POU emitted ST projection")


def _scenario_dut_projection(work_dir):
    """DUT ST projection is written with its type text."""
    with _engine_on_path():
        from _project_model import ProjectModel, ProjectNode
        from folder_writer import FolderWriter
        dut_projection_root = os.path.join(work_dir, "dut_projection")
        dut_projection_view = os.path.join(dut_projection_root, "project-view")
        dut_projection_dump = os.path.join(dut_projection_root, ".dump")
        dut_model = ProjectModel()
        dut_node = ProjectNode(
            "55555555-5555-5555-5555-555555555555",
            "DUT_SAMPLE",
            "2db5746d-d284-4425-9f7f-2663a34b0ebc",
        )
        dut_node.code = "TYPE DUT_SAMPLE :\nSTRUCT\n    value : INT;\nEND_STRUCT\nEND_TYPE"
        dut_node.entry_element = ET.fromstring("<Single />")
        dut_model.add_node(dut_node)
        FolderWriter(
            dut_projection_view,
            dut_projection_dump,
            profile={
                "guid_aliases": {"dut": ["2db5746d-d284-4425-9f7f-2663a34b0ebc"]},
                "projections": [{
                    "id": "dut_st",
                    "kind": "dut",
                    "format": "st",
                }],
            },
            projections={"dut_st": {"enabled": True}},
        ).write(dut_model)
    dut_projection_path = os.path.join(dut_projection_view, "DUT_SAMPLE.st")
    if not os.path.exists(dut_projection_path):
        raise RegressionFailure("DUT ST projection was not written")
    with open(dut_projection_path, "r") as handle:
        if "TYPE DUT_SAMPLE" not in handle.read():
            raise RegressionFailure("DUT ST projection content was not written")


def _scenario_persistent_projection(work_dir):
    """Persistent variable list ST projection is written."""
    with _engine_on_path():
        from _project_model import ProjectModel, ProjectNode
        from _project_profiles import load_profile
        from folder_writer import FolderWriter
        persistent_projection_root = os.path.join(work_dir, "persistent_projection")
        persistent_projection_view = os.path.join(persistent_projection_root, "project-view")
        persistent_projection_dump = os.path.join(persistent_projection_root, ".dump")
        persistent_model = ProjectModel()
        persistent_node = ProjectNode(
            "56565656-5656-5656-5656-565656565656",
            "PersistentVars",
            "3183921b-cc91-4712-9781-c3b6555122b5",
        )
        persistent_node.code = "VAR_GLOBAL PERSISTENT RETAIN\n    value : INT;\nEND_VAR"
        persistent_node.entry_element = ET.fromstring("<Single />")
        persistent_model.add_node(persistent_node)
        FolderWriter(
            persistent_projection_view,
            persistent_projection_dump,
            profile=load_profile("default"),
            projections={"gvl_st": {"enabled": True}},
        ).write(persistent_model)
    persistent_projection_path = os.path.join(persistent_projection_view, "PersistentVars.st")
    if not os.path.exists(persistent_projection_path):
        raise RegressionFailure("persistent variable list ST projection was not written")
    with open(persistent_projection_path, "r") as handle:
        if "VAR_GLOBAL PERSISTENT" not in handle.read():
            raise RegressionFailure("persistent variable list ST projection content was not written")


def _scenario_textlist_projection(work_dir):
    """TextList/GlobalTextList CSV projections write, round-trip and validate."""
    with _engine_on_path():
        from _project_model import ProjectModel, ProjectNode
        from folder_writer import FolderWriter

    textlist_projection_root = os.path.join(work_dir, "textlist_projection")
    textlist_projection_view = os.path.join(textlist_projection_root, "project-view")
    textlist_projection_dump = os.path.join(textlist_projection_root, ".dump")
    textlist_model = ProjectModel()
    textlist_node = ProjectNode(
        "66666666-6666-6666-6666-666666666666",
        "TextList",
        "2bef0454-1bd3-412a-ac2c-af0f31dbc40f",
    )
    textlist_node.metadata["structured_view_guid"] = "11111111-1111-1111-1111-111111111111"
    textlist_node.entry_element = ET.fromstring(
        '<Single><Single Name="Object"><List Name="TextList">'
        '<Single><Single Name="TextID">1</Single><Single Name="TextDefault">First</Single></Single>'
        '<Single><Single Name="TextID">2</Single><Single Name="TextDefault">Needs, quotes</Single></Single>'
        '</List></Single></Single>'
    )
    textlist_model.add_node(textlist_node)
    global_textlist_node = ProjectNode(
        "77777777-7777-7777-7777-777777777777",
        "GlobalTextList",
        "63784cbb-9ba0-45e6-9d69-babf3f040511",
    )
    global_textlist_node.metadata["structured_view_guid"] = "11111111-1111-1111-1111-111111111111"
    global_textlist_node.entry_element = ET.fromstring(
        '<Single><Single Name="Object">'
        '<List Name="TextList">'
        '<Single><Single Name="TextID">3</Single><Single Name="TextDefault">Global</Single>'
        '<List Name="LanguageTexts"><Single>Global EN</Single><Single>Global DE</Single></List>'
        '</Single>'
        '</List>'
        '<List Name="Languages"><Single>ENG</Single><Single>DEU</Single></List>'
        '</Single></Single>'
    )
    textlist_model.add_node(global_textlist_node)
    alarm_textlist_node = ProjectNode(
        "88888888-8888-8888-8888-888888888888",
        "AlarmGroup",
        "2bef0454-1bd3-412a-ac2c-af0f31dbc40f",
    )
    alarm_textlist_node.metadata["structured_view_guid"] = "11111111-1111-1111-1111-111111111111"
    alarm_textlist_node.entry_element = ET.fromstring(
        '<Single><Single Name="Object"><List Name="TextList">'
        '<Single><Single Name="TextID">4</Single><Single Name="TextDefault">Alarm</Single></Single>'
        '</List></Single></Single>'
    )
    textlist_model.add_node(alarm_textlist_node)
    FolderWriter(
        textlist_projection_view,
        textlist_projection_dump,
        profile={
            "guid_aliases": {
                "textlist": ["2bef0454-1bd3-412a-ac2c-af0f31dbc40f"],
                "global_text_list": ["63784cbb-9ba0-45e6-9d69-babf3f040511"],
            },
            "projections": [{
                "id": "textlist_csv",
                "kind": "textlist",
                "kinds": ["textlist", "global_text_list"],
                "format": "csv",
                "exclude_names": ["AlarmGroup"],
                "import_safe": True,
            }],
        },
        projections={"textlist_csv": {"enabled": True}},
    ).write(textlist_model)
    textlist_csv_path = os.path.join(textlist_projection_view, "TextList.csv")
    global_textlist_csv_path = os.path.join(textlist_projection_view, "GlobalTextList.csv")
    if not os.path.exists(textlist_csv_path):
        raise RegressionFailure("TextList CSV projection was not written")
    if not os.path.exists(global_textlist_csv_path):
        raise RegressionFailure("GlobalTextList CSV projection was not written")
    if os.path.exists(os.path.join(textlist_projection_view, "AlarmGroup.csv")):
        raise RegressionFailure("AlarmGroup should not emit TextList CSV projection")
    with open(textlist_csv_path, "r", encoding="utf-8") as handle:
        textlist_csv_content = handle.read()
    if 'TextID,TextDefault\n1,First\n2,"Needs, quotes"\n' != textlist_csv_content:
        raise RegressionFailure("TextList CSV projection content was unexpected")
    with open(global_textlist_csv_path, "r", encoding="utf-8") as handle:
        global_textlist_csv_content = handle.read()
    if 'TextID,TextDefault,ENG,DEU\n3,Global,Global EN,Global DE\n' != global_textlist_csv_content:
        raise RegressionFailure("TextList CSV language columns were unexpected")
    with _engine_on_path():
        from _patch_builder import PatchBuilder
        from diff_engine import DiffEngine
        from folder_reader import FolderReader
        from xml_helpers import ProjectionValidationError
        from xml_helpers import apply_textlist_csv
        from xml_helpers import entry_to_xml
        blank_textlist_entry = ET.fromstring(
            '<Single><Single Name="Object"><List Name="TextList">'
            '<Single><Single Name="TextID"></Single><Single Name="TextDefault"></Single></Single>'
            '</List></Single></Single>'
        )
        if apply_textlist_csv(blank_textlist_entry, "TextID,TextDefault\n,\n"):
            raise RegressionFailure("blank TextID CSV row should round-trip without changes")
        for node in textlist_model.nodes.values():
            node.xml_text = entry_to_xml(node.entry_element)
        _replace_in_file(textlist_csv_path, "First", "First changed")
        textlist_folder_model = FolderReader(textlist_projection_view, textlist_projection_dump).read()
        textlist_diff = DiffEngine(textlist_model, textlist_folder_model).compare()
        if "66666666-6666-6666-6666-666666666666" not in textlist_diff.get("modified", []):
            raise RegressionFailure("changed export-only CSV projection was not reported as modified")
        if textlist_diff.get("unsupported_projection_changes"):
            raise RegressionFailure("changed import-safe TextList CSV projection was reported as unsupported")
        changed_node = textlist_folder_model.get_node("66666666-6666-6666-6666-666666666666")
        if "First changed" not in changed_node.xml_text:
            raise RegressionFailure("changed TextList CSV projection was not rehydrated into XML")
        if not PatchBuilder(
            textlist_diff,
            textlist_model,
            textlist_folder_model,
        ).build_patch(os.path.join(textlist_projection_dump, "IMPORT_csv.xml")):
            raise RegressionFailure("changed TextList CSV projection did not build an import patch")

        with open(textlist_csv_path, "w", encoding="utf-8") as handle:
            handle.write('TextID,TextDefault\n1,First changed\n2,"Needs, quotes"\n3,Inserted\n')
        try:
            FolderReader(textlist_projection_view, textlist_projection_dump).read()
            raise RegressionFailure("inserted TextList CSV row was not rejected")
        except ProjectionValidationError as error:
            if "inserted TextID: 3" not in str(error):
                raise RegressionFailure("inserted TextList CSV row error was unexpected")


def _scenario_alarm_projection(work_dir):
    """Alarm-items CSV projection writes, round-trips and enforces read-only columns."""
    with _engine_on_path():
        from _project_model import ProjectModel, ProjectNode
        from folder_writer import FolderWriter

    alarm_projection_root = os.path.join(work_dir, "alarm_projection")
    alarm_projection_view = os.path.join(alarm_projection_root, "project-view")
    alarm_projection_dump = os.path.join(alarm_projection_root, ".dump")
    alarm_model = ProjectModel()
    alarm_node = ProjectNode(
        "99999999-9999-9999-9999-999999999999",
        "TEST_ALARMS",
        "21f4ed1d-ec95-4666-820e-4abf64d93d6b",
    )
    alarm_node.metadata["structured_view_guid"] = "11111111-1111-1111-1111-111111111111"
    alarm_node.entry_element = ET.fromstring(
        '<Single><Single Name="Object"><Dictionary Name="Alarms">'
        '<Entry><Key><Single Type="string">2</Single></Key><Value>'
        '<Single><Single Name="ID">2</Single>'
        '<Single Name="ObservationType"><Single Name="Comparison">Equal</Single>'
        '<Single Name="ExpressionToCompare">TRUE</Single>'
        '<Single Name="Expression">GVL.xAlarm</Single></Single>'
        '<Single Name="AlarmClass"><Single Name="Name">Error</Single></Single>'
        '<Single Name="LatchVariable1">"Error"</Single>'
        '<Single Name="LatchVariable2">"Unit, quoted"</Single>'
        '<Null Name="AdditionalMessageIDs" />'
        '</Single></Value></Entry>'
        '<Entry><Key><Single Type="string">1</Single></Key><Value>'
        '<Single><Single Name="ID">1</Single>'
        '<Single Name="ObservationType"><Single Name="Comparison">Greater</Single>'
        '<Single Name="ExpressionToCompare">5</Single>'
        '<Single Name="Expression">GVL.iValue</Single></Single>'
        '<Single Name="FullAlarmClassName">Warning</Single>'
        '<Null Name="AdditionalMessageIDs" />'
        '</Single></Value></Entry>'
        '</Dictionary></Single></Single>'
    )
    alarm_model.add_node(alarm_node)
    FolderWriter(
        alarm_projection_view,
        alarm_projection_dump,
        profile={
            "guid_aliases": {
                "alarm_config_item": ["21f4ed1d-ec95-4666-820e-4abf64d93d6b"],
            },
            "projections": [{
                "id": "alarm_items_csv",
                "kind": "alarm_config_item",
                "format": "csv",
                "extractor": "alarm_items_csv",
                "import_safe": True,
            }],
        },
        projections={"alarm_items_csv": {"enabled": True}},
    ).write(alarm_model)
    alarm_csv_path = os.path.join(alarm_projection_view, "TEST_ALARMS.csv")
    if not os.path.exists(alarm_csv_path):
        raise RegressionFailure("Alarm items CSV projection was not written")
    with open(alarm_csv_path, "r") as handle:
        alarm_csv_content = handle.read()
    expected_alarm_csv = (
        "AlarmID,Expression,Comparison,ExpressionToCompare,AlarmClass,LatchVariable1,LatchVariable2,"
        "Deactivation,MinPendingTime,OffDelayTime,HigherPrioAlarm,AdditionalMessageIDs\n"
        "1,GVL.iValue,Greater,5,Warning,,,,,,,\n"
        "2,GVL.xAlarm,Equal,TRUE,Error,\"\"\"Error\"\"\",\"\"\"Unit, quoted\"\"\",,,,,\n"
    )
    if alarm_csv_content != expected_alarm_csv:
        raise RegressionFailure("Alarm items CSV projection content was unexpected")
    alarm_manifest = _read_json(os.path.join(alarm_projection_dump, "manifest.json"))
    alarm_extractors = alarm_manifest["entries"][0].get("projection_extractors") or {}
    if alarm_extractors.get("TEST_ALARMS.csv") != "alarm_items_csv":
        raise RegressionFailure("Alarm items CSV extractor was not recorded in manifest")
    with _engine_on_path():
        from _patch_builder import PatchBuilder
        from diff_engine import DiffEngine
        from folder_reader import FolderReader
        from xml_helpers import ProjectionValidationError, apply_alarm_items_csv, entry_to_xml
        blank_alarm_entry = ET.fromstring(
            '<Single><Single Name="Object"><Dictionary Name="Alarms">'
            '<Entry><Key><Single Type="string"></Single></Key><Value>'
            '<Single><Single Name="ID"></Single></Single>'
            '</Value></Entry>'
            '</Dictionary></Single></Single>'
        )
        if apply_alarm_items_csv(
            blank_alarm_entry,
            "AlarmID,Expression,Comparison,ExpressionToCompare,AlarmClass,LatchVariable1,LatchVariable2,"
            "Deactivation,MinPendingTime,OffDelayTime,HigherPrioAlarm,AdditionalMessageIDs\n"
            ",,,,,,,,,,,\n",
        ):
            raise RegressionFailure("blank AlarmID CSV row should round-trip without changes")
        for node in alarm_model.nodes.values():
            node.xml_text = entry_to_xml(node.entry_element)
        _replace_in_file(alarm_csv_path, "GVL.iValue", "GVL.iChanged")
        alarm_folder_model = FolderReader(alarm_projection_view, alarm_projection_dump).read()
        alarm_diff = DiffEngine(alarm_model, alarm_folder_model).compare()
        if "99999999-9999-9999-9999-999999999999" not in alarm_diff.get("modified", []):
            raise RegressionFailure("changed alarm CSV projection was not reported as modified")
        if alarm_diff.get("unsupported_projection_changes"):
            raise RegressionFailure("changed import-safe alarm CSV projection was reported as unsupported")
        alarm_folder_node = alarm_folder_model.get_node("99999999-9999-9999-9999-999999999999")
        if "GVL.iChanged" not in (alarm_folder_node.xml_text or ""):
            raise RegressionFailure("alarm CSV projection was not rehydrated into XML")
        PatchBuilder(
            alarm_diff,
            alarm_model,
            alarm_folder_model,
        ).build_patch(os.path.join(alarm_projection_dump, "IMPORT_alarm_csv.xml"))

        with open(alarm_csv_path, "w") as handle:
            handle.write(
                "AlarmID,Expression,Comparison,ExpressionToCompare,AlarmClass,LatchVariable1,LatchVariable2,"
                "Deactivation,MinPendingTime,OffDelayTime,HigherPrioAlarm,AdditionalMessageIDs\n"
                "1,GVL.iChanged,Greater,5,Warning,,,,,,,\n"
            )
        try:
            FolderReader(alarm_projection_view, alarm_projection_dump).read()
            raise RegressionFailure("removed Alarm CSV row was not rejected")
        except ProjectionValidationError as error:
            if "removed AlarmID: 2" not in str(error):
                raise RegressionFailure("removed Alarm CSV row error was unexpected")

        with open(alarm_csv_path, "w") as handle:
            handle.write(
                "AlarmID,Expression,Comparison,ExpressionToCompare,AlarmClass,LatchVariable1,LatchVariable2,"
                "Deactivation,MinPendingTime,OffDelayTime,HigherPrioAlarm,AdditionalMessageIDs\n"
                "1,GVL.iChanged,Greater,5,Warning,,,,,,,custom-message\n"
                "2,GVL.xAlarm,Equal,TRUE,Error,\"\"\"Error\"\"\",\"\"\"Unit, quoted\"\"\",,,,,\n"
            )
        try:
            FolderReader(alarm_projection_view, alarm_projection_dump).read()
            raise RegressionFailure("changed Alarm AdditionalMessageIDs was not rejected")
        except ProjectionValidationError as error:
            if "AdditionalMessageIDs is read-only" not in str(error):
                raise RegressionFailure("changed Alarm AdditionalMessageIDs error was unexpected")


def _scenario_text_first_roundtrip(work_dir):
    """Text-first mode: xml mirrored into .dump, .st drives import, mode locked."""
    text_first_root = os.path.join(work_dir, "text_first")
    os.makedirs(text_first_root)
    text_first_snapshot = os.path.join(text_first_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), text_first_snapshot)
    _write_json(os.path.join(text_first_root, "cds-text-sync.json"), {
        "version": 1,
        "layout": "project-view",
        "profile": "default",
        "projections": {},
        "sync_mode": "text_first",
    })

    # Export: .st emitted (force-enabled), xml hidden in the .dump mirror.
    _run(["export", "--project-root", text_first_root, "--snapshot", text_first_snapshot])
    view_st_path = os.path.join(text_first_root, "project-view", "Device", "Application", "PLC_PRG.st")
    view_xml_path = os.path.join(text_first_root, "project-view", "Device", "Application", "PLC_PRG.xml")
    mirror_xml_path = os.path.join(text_first_root, ".dump", "xml", "Device", "Application", "PLC_PRG.xml")
    if not os.path.exists(view_st_path):
        raise RegressionFailure("text-first export did not write the .st view")
    if os.path.exists(view_xml_path):
        raise RegressionFailure("text-first export left xml in the view root")
    if not os.path.exists(mirror_xml_path):
        raise RegressionFailure("text-first export did not write the .dump/xml mirror")
    text_first_manifest = _read_json(os.path.join(text_first_root, ".dump", "manifest.json"))
    if text_first_manifest.get("sync_mode") != "text_first":
        raise RegressionFailure("text-first manifest did not record sync_mode")
    plc_entry = None
    for entry in text_first_manifest["entries"]:
        if str(entry.get("xml_path") or "").endswith("PLC_PRG.xml"):
            plc_entry = entry
            break
    if plc_entry is None or plc_entry.get("xml_root") != "dump":
        raise RegressionFailure("text-first manifest entry did not record xml_root=dump")

    # Edit the .st and import: the patch must carry the edited text.
    _replace_in_file(view_st_path, "x := 1;", "x := 2;")
    text_first_patch = os.path.join(text_first_root, ".dump", "IMPORT.xml")
    _run(["import", "--project-root", text_first_root, "--snapshot", text_first_snapshot, "--patch", text_first_patch])
    with open(text_first_patch, "r") as handle:
        patch_text = handle.read()
    if "x := 2;" not in patch_text:
        raise RegressionFailure("text-first import patch did not carry the .st edit")

    # Fresh-clone simulation: remove the git-ignored mirror; the .st alone
    # must still drive the import (st_only overlay on the IDE baseline).
    shutil.rmtree(os.path.join(text_first_root, ".dump", "xml"))
    _run(["import", "--project-root", text_first_root, "--snapshot", text_first_snapshot, "--patch", text_first_patch])
    with open(text_first_patch, "r") as handle:
        patch_text = handle.read()
    if "x := 2;" not in patch_text:
        raise RegressionFailure("st-only import patch did not carry the .st edit")

    # Hand-made .st + .xml pair resolves to one text create.
    pair_st = os.path.join(text_first_root, "project-view", "Device", "Application", "PairPou.st")
    pair_xml = os.path.join(text_first_root, "project-view", "Device", "Application", "PairPou.xml")
    _write_text(pair_st, "PROGRAM PairPou\nVAR\nEND_VAR\n// --- implementation ---\ny := 1;\n")
    _write_text(pair_xml, '<Single Name="Object" Type="{6f9dac99-8de1-4efc-8465-68ac443b7d08}"><Guid>{p}</Guid></Single>')
    _run(["import", "--project-root", text_first_root, "--snapshot", text_first_snapshot, "--patch", text_first_patch])
    with open(text_first_patch, "r") as handle:
        patch_text = handle.read()
    if patch_text.count("CreateTextObject") == 0 or "PairPou" not in patch_text:
        raise RegressionFailure("text-first pair discovery did not produce a text create")
    if "CreateNativeObject" in patch_text:
        raise RegressionFailure("text-first pair discovery leaked a native create for the sidecar xml")
    os.remove(pair_st)
    os.remove(pair_xml)

    # The mode is locked once initialized: an xml-first settings file must fail.
    _write_json(os.path.join(text_first_root, "cds-text-sync.json"), {
        "version": 1,
        "layout": "project-view",
        "profile": "default",
        "projections": {},
        "sync_mode": "xml_first",
    })
    _run(["export", "--project-root", text_first_root, "--snapshot", text_first_snapshot], expect_code=1)


def _scenario_settings_roundtrip(work_dir):
    """Project settings save/load round-trip."""
    settings_write_root = os.path.join(work_dir, "settings_write")
    os.makedirs(settings_write_root)
    with _engine_on_path():
        from _project_settings import load_project_settings, save_project_settings
        saved_settings = save_project_settings(settings_write_root, {
            "layout": "root-view",
            "view_root": None,
            "profile": "default",
            "projections": {"pou": {"format": "st"}},
            "sync_mode": "text-first",
            "xml_in_view_kinds": ["Visu", "textlist"],
        })
        loaded_settings = load_project_settings(settings_write_root)
    _assert_equal(saved_settings["layout"], "root-view", "saved settings layout")
    _assert_equal(loaded_settings["layout"], "root-view", "loaded settings layout")
    _assert_equal(loaded_settings["projections"], {"pou": {"format": "st"}}, "loaded settings projections")
    _assert_equal(loaded_settings["sync_mode"], "text_first", "loaded settings sync_mode")
    _assert_equal(loaded_settings["xml_in_view_kinds"], ["visu", "textlist"], "loaded settings xml_in_view_kinds")


def _scenario_missing_settings(work_dir):
    """Missing project settings fall back to the project-view layout defaults."""
    missing_settings_root = os.path.join(work_dir, "missing_settings")
    os.makedirs(missing_settings_root)
    with _engine_on_path():
        from _project_layout import resolve_layout
        from _project_settings import load_project_settings
        missing_settings = load_project_settings(missing_settings_root)
        missing_layout = resolve_layout(missing_settings_root, layout_mode=missing_settings.get("layout"))
    _assert_equal(missing_settings["layout"], "project-view", "missing settings layout")
    _assert_equal(
        missing_layout.view_root,
        os.path.join(missing_settings_root, "project-view"),
        "missing settings view root",
    )


def _scenario_pathless_project_object(work_dir):
    """A path-less project object gets a synthetic display path."""
    pathless_snapshot = os.path.join(work_dir, "pathless_project_objects.xml")
    _write_text(pathless_snapshot, """<?xml version='1.0' encoding='utf-8'?>
<Project>
  <StructuredView Guid="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">11111111-1111-1111-1111-111111111111</Single>
            <Single Name="ParentGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>
            <Single Name="Name" Type="System.String">Project Settings</Single>
            <Single Name="TypeGuid" Type="System.Guid">8753fe6f-4a22-4320-8103-e553c4fc8e04</Single>
          </Single>
          <Single Name="Object" />
        </Single>
      </List2>
    </Single>
  </StructuredView>
</Project>
""")
    with _engine_on_path():
        from snapshot_reader import SnapshotReader
        pathless_model = SnapshotReader(pathless_snapshot, project_name="VKO-Beumer").read()
    pathless_node = list(pathless_model.nodes.values())[0]
    _assert_equal(pathless_node.display_path, ["POUs"], "pathless project object display path")


def _scenario_duplicate_structured_view(work_dir):
    """Duplicate StructuredView GUIDs deduplicate to one node."""
    duplicate_view_snapshot = os.path.join(work_dir, "duplicate_structured_view_guids.xml")
    _write_text(duplicate_view_snapshot, """<?xml version='1.0' encoding='utf-8'?>
<Project>
  <StructuredView Guid="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">{22222222-2222-2222-2222-222222222222}</Single>
            <Single Name="ParentGuid" Type="System.Guid">{00000000-0000-0000-0000-000000000000}</Single>
            <Single Name="Name" Type="System.String">FB_DUPLICATE</Single>
            <Single Name="TypeGuid" Type="System.Guid">6f9dac99-8de1-4efc-8465-68ac443b7d08</Single>
          </Single>
          <Array Name="Path"><Single>FBs</Single></Array>
          <Single Name="Object" />
        </Single>
      </List2>
    </Single>
  </StructuredView>
  <StructuredView Guid="{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">22222222-2222-2222-2222-222222222222</Single>
            <Single Name="ParentGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>
            <Single Name="Name" Type="System.String">FB_DUPLICATE</Single>
            <Single Name="TypeGuid" Type="System.Guid">6f9dac99-8de1-4efc-8465-68ac443b7d08</Single>
          </Single>
          <Array Name="Path"><Single>Device</Single><Single>PLC Logic</Single><Single>Application</Single><Single>FBs</Single></Array>
          <Single Name="Object" />
        </Single>
      </List2>
    </Single>
  </StructuredView>
</Project>
""")
    with _engine_on_path():
        from snapshot_reader import SnapshotReader
        duplicate_view_model = SnapshotReader(duplicate_view_snapshot, project_name="VKO-Beumer").read()
    _assert_equal(len(duplicate_view_model.nodes), 1, "structured view GUID normalization deduplicates nodes")


def _scenario_alias_structured_view(work_dir):
    """StructuredView path aliases deduplicate and keep the concrete path."""
    alias_view_snapshot = os.path.join(work_dir, "alias_structured_view_paths.xml")
    _write_text(alias_view_snapshot, """<?xml version='1.0' encoding='utf-8'?>
<Project>
  <StructuredView Guid="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">33333333-3333-3333-3333-333333333333</Single>
            <Single Name="ParentGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>
            <Single Name="Name" Type="System.String">FB_ALIAS</Single>
            <Single Name="TypeGuid" Type="System.Guid">6f9dac99-8de1-4efc-8465-68ac443b7d08</Single>
          </Single>
          <Array Name="Path"><Single>FBs</Single></Array>
          <Single Name="Object">
            <Single Name="Implementation">
              <Single Name="TextBlobForSerialisation">FUNCTION_BLOCK FB_ALIAS_SHORT</Single>
            </Single>
          </Single>
        </Single>
      </List2>
    </Single>
  </StructuredView>
  <StructuredView Guid="{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">44444444-4444-4444-4444-444444444444</Single>
            <Single Name="ParentGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>
            <Single Name="Name" Type="System.String">FB_ALIAS</Single>
            <Single Name="TypeGuid" Type="System.Guid">6f9dac99-8de1-4efc-8465-68ac443b7d08</Single>
          </Single>
          <Array Name="Path"><Single>Device</Single><Single>PLC Logic</Single><Single>Application</Single><Single>FBs</Single></Array>
          <Single Name="Object">
            <Single Name="Implementation">
              <Single Name="TextBlobForSerialisation">FUNCTION_BLOCK FB_ALIAS_CONCRETE</Single>
            </Single>
          </Single>
        </Single>
      </List2>
    </Single>
  </StructuredView>
</Project>
""")
    with _engine_on_path():
        from snapshot_reader import SnapshotReader
        alias_view_model = SnapshotReader(alias_view_snapshot, project_name="VKO-Beumer").read()
    _assert_equal(len(alias_view_model.nodes), 1, "structured view path aliases deduplicate nodes")
    alias_node = list(alias_view_model.nodes.values())[0]
    _assert_equal(
        alias_node.display_path,
        ["Device", "PLC Logic", "Application", "FBs"],
        "structured view path alias keeps concrete path",
    )


def _scenario_added_object(work_dir):
    """An object present on disk but absent from the IDE becomes a native create."""
    added_project_root = os.path.join(work_dir, "project_added")
    os.makedirs(added_project_root)
    added_snapshot_path = os.path.join(added_project_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), added_snapshot_path)
    added_views_path = os.path.join(added_project_root, ".dump", "views")
    added_dump_path = os.path.join(added_project_root, ".dump")

    _run(["export", "--project-root", added_project_root, "--snapshot", added_snapshot_path, "--views", added_views_path])
    _add_view_object(added_views_path, added_dump_path)

    added_compare_path = os.path.join(added_dump_path, "compare_added.json")
    _run(["compare", "--project-root", added_project_root, "--snapshot", added_snapshot_path, "--views", added_views_path, "--report", added_compare_path])
    _assert_equal(
        _read_json(added_compare_path),
        {
            "summary": {
                "modified": 0,
                "added": 1,
                "deleted": 0,
                "unchanged": 1,
            },
            "details": {
                "modified": [],
                "added": ["22222222-2222-2222-2222-222222222222"],
                "deleted": [],
                "unchanged": ["11111111-1111-1111-1111-111111111111"],
            },
        },
        "added compare report",
    )

    added_patch_path = os.path.join(added_dump_path, "IMPORT_added.xml")
    _run(["import", "--project-root", added_project_root, "--snapshot", added_snapshot_path, "--views", added_views_path, "--patch", added_patch_path])
    # A brand-new object present on disk but absent from the IDE is emitted
    # as a native-create entry (<CreateNativeObject>), not a StructuredView
    # guid patch. Its guid lives inside the embedded NativeXml.
    _assert_equal(
        _guid_texts(added_patch_path),
        [],
        "added patch StructuredView guids",
    )
    _assert_equal(
        _native_create_guids(added_patch_path),
        [
            "22222222-2222-2222-2222-222222222222",
        ],
        "added patch native-create guids",
    )

    selected_added_patch_path = os.path.join(added_dump_path, "IMPORT_selected_added.xml")
    _run([
        "import",
        "--project-root", added_project_root,
        "--snapshot", added_snapshot_path,
        "--views", added_views_path,
        "--patch", selected_added_patch_path,
        "--filter-guids", "11111111-1111-1111-1111-111111111111",
    ])
    if _guid_texts(selected_added_patch_path):
        raise RegressionFailure("selected import patch included unselected added object")


def _scenario_deleted_object(work_dir):
    """An object removed from the manifest becomes a delete with no guid leak."""
    deleted_project_root = os.path.join(work_dir, "project_deleted")
    os.makedirs(deleted_project_root)
    deleted_snapshot_path = os.path.join(deleted_project_root, "IDE.xml")
    shutil.copyfile(os.path.join(FIXTURE_DIR, "IDE.xml"), deleted_snapshot_path)
    deleted_views_path = os.path.join(deleted_project_root, ".dump", "views")
    deleted_dump_path = os.path.join(deleted_project_root, ".dump")

    _run(["export", "--project-root", deleted_project_root, "--snapshot", deleted_snapshot_path, "--views", deleted_views_path])
    deleted_manifest_path = os.path.join(deleted_dump_path, "manifest.json")
    deleted_manifest = _read_json(deleted_manifest_path)
    deleted_manifest["entries"] = []
    _write_json(deleted_manifest_path, deleted_manifest)

    deleted_compare_path = os.path.join(deleted_dump_path, "compare_deleted.json")
    _run(["compare", "--project-root", deleted_project_root, "--snapshot", deleted_snapshot_path, "--views", deleted_views_path, "--report", deleted_compare_path])
    _assert_equal(
        _read_json(deleted_compare_path),
        {
            "summary": {
                "modified": 0,
                "added": 0,
                "deleted": 1,
                "unchanged": 0,
            },
            "details": {
                "modified": [],
                "added": [],
                "deleted": ["11111111-1111-1111-1111-111111111111"],
                "unchanged": [],
            },
        },
        "deleted compare report",
    )

    deleted_patch_path = os.path.join(deleted_dump_path, "IMPORT_deleted.xml")
    _run(["import", "--project-root", deleted_project_root, "--snapshot", deleted_snapshot_path, "--views", deleted_views_path, "--patch", deleted_patch_path])
    if _guid_texts(deleted_patch_path):
        raise RegressionFailure("deleted-only import patch unexpectedly contained object guids")


def main():
    """Keep the historical script entry point while using pytest as runner."""
    import pytest

    test_path = os.path.join(ROOT_DIR, "tests", "regression", "test_offline_regression.py")
    return pytest.main([test_path])


if __name__ == "__main__":
    sys.exit(main())
