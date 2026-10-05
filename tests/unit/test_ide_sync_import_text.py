# -*- coding: utf-8 -*-
"""
test_ide_sync_import_text.py — the whole ``_cmd_sync_import_text`` contract.

The handler is the disk -> IDE door: it exports the live project as a baseline,
asks the external engine for an IMPORT.xml, applies the text and native creates
out of it, folds in the compare report, optionally imports a StructuredView,
optionally saves, optionally re-baselines the manifest, attests the import, and
finally hands back one result dict.

The existing tests only cover the pieces it is built out of
(``_apply_modified_st_objects``, ``_refresh_blockers``, ...).  This module pins
the assembled result: the *complete* dictionary the handler returns, and the
order and composition of its side effects (engine runs, ``project.save``,
``project.import_native``, the export refresh, the attestation, the cache
invalidation).  That is the safety net a decomposition of the orchestrator
needs, since a helper can be right while the wiring around it is wrong.

The daemon modules are IronPython-only, so their CODESYS/.NET dependencies are
stubbed before import (same loader as ``test_ide_sync_apply.py``).
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
import types

import pytest


_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

_STUBBED = (
    "ide_runtime_common",
    "ide_daemon_state",
    "ide_daemon_helpers",
    "ide_apply_patch",
)

_HELPER_NAMES = (
    "_active_app_online_state",
    "_active_application_name",
    "_find_object_by_selector",
    "_find_object_in_project",
    "_get_sync_folder",
    "_invalidate_device_cache",
)


def _load_sync_module():
    """Import ide_handlers_sync with its CODESYS-only dependencies stubbed.

    sys.modules is restored afterwards: other test modules import the real
    ide_bridge modules and must not inherit these stubs.
    """
    saved = dict((name, sys.modules.get(name)) for name in _STUBBED)
    try:
        for name in _STUBBED:
            sys.modules[name] = types.ModuleType(name)

        state = sys.modules["ide_daemon_state"]
        state._log = lambda *args, **kwargs: None
        state._get_active_project = lambda: (None, None)
        state._read_text_utf8 = lambda path: ""

        helpers = sys.modules["ide_daemon_helpers"]
        for name in _HELPER_NAMES:
            setattr(helpers, name, lambda *args, **kwargs: None)

        loader = importlib.machinery.SourceFileLoader(
            "ide_handlers_sync_import_text_under_test",
            os.path.join(_BRIDGE, "ide_handlers_sync.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


sync = _load_sync_module()


# ── IMPORT.xml fixtures ────────────────────────────────────────────────────


def _text_create(name, path, kind="POU", parent=""):
    return (
        '<CreateTextObject Path="{0}" Name="{1}" Kind="{2}" TypeGuid="guid-{1}" '
        'ParentName="{3}"/>'.format(path, name, kind, parent)
    )


def _native_create(name, path="App/Visu_Main"):
    return (
        '<CreateNativeObject Path="{0}" Name="{1}" TypeGuid="visu-guid">'
        "<NativeXml>&lt;x/&gt;</NativeXml></CreateNativeObject>"
    ).format(path, name)


def _import_xml(text_creates=(), native_creates=(), structured_view=False):
    children = []
    if text_creates:
        children.append(
            "<CreateTextObjects>" + "".join(text_creates) + "</CreateTextObjects>"
        )
    if native_creates:
        children.append(
            "<CreateNativeObjects>"
            + "".join(native_creates)
            + "</CreateNativeObjects>"
        )
    if structured_view:
        children.append("<StructuredView/>")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<Project>'
        + "".join(children)
        + "</Project>"
    )


# ── stub project / side-effect recorder ────────────────────────────────────


class _Project(object):
    def __init__(self):
        self.save_calls = 0
        self.save_error = None
        self.import_native_calls = []
        self.import_native_error = None

    def save(self):
        self.save_calls += 1
        if self.save_error is not None:
            raise self.save_error

    def import_native(self, path):
        self.import_native_calls.append(path)
        if self.import_native_error is not None:
            raise self.import_native_error


class _Bridge(object):
    """One configured run of ``_cmd_sync_import_text``."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.sync_dir = str(tmp_path / "sync")
        self.dump_dir = os.path.join(self.sync_dir, ".dump")
        self.views_dir = os.path.join(self.sync_dir, "project-view")
        os.makedirs(self.dump_dir)
        os.makedirs(self.views_dir)
        self.snapshot = os.path.join(self.dump_dir, "snapshot-1.xml")
        with open(self.snapshot, "w") as handle:
            handle.write("<Project/>")
        self.patch = os.path.join(self.dump_dir, "IMPORT.xml")
        self.compare_report = os.path.join(
            self.dump_dir, "import_compare_report.json"
        )

        self.calls = []
        self.project = _Project()
        self.online = False
        self.online_state = "connected"
        self.project_error = None
        self.import_engine_ok = True
        self.engine_notices = []
        self.backup_ok = True
        self.apply_text = None  # callable(project, entry, created) -> reused
        self.apply_modified = None  # callable(project, path) -> [names]
        self.export_text = {"ok": True, "data": {}}
        self.export_text_params = None
        self.attestation = {"complete": True, "fingerprint": "fp-1"}
        self.native_entries = []
        self.native_failures = ()
        self.saved_text_creates = []
        self.write_import_xml()

    # -- files --

    def write_import_xml(self, **kwargs):
        with open(self.patch, "w") as handle:
            handle.write(_import_xml(**kwargs))

    def write_compare_report(self, payload):
        with open(self.compare_report, "w") as handle:
            json.dump(payload, handle)

    def write_view(self, rel_path, content):
        path = os.path.join(self.views_dir, rel_path)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(content)
        return path

    # -- run --

    def run(self, params=None):
        return sync._cmd_sync_import_text({} if params is None else params)

    def effect_names(self):
        return [call[0] for call in self.calls]

    def text_creates_in_order(self):
        return [call[1] for call in self.calls if call[0] == "apply_text"]


# ── the fixture that installs all stubs on the loaded module ───────────────


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    b = _Bridge(tmp_path)

    def record(name, *args):
        b.calls.append((name,) + args)

    def run_engine(args, notices=None, **kwargs):
        record("engine", args[0])
        if args[0] == "import":
            if notices is not None:
                notices.extend(b.engine_notices)
            return b.import_engine_ok
        return True

    def apply_text_create_entry(project, entry, created_by_name):
        record("apply_text", entry["name"])
        b.saved_text_creates.append(entry)
        if b.apply_text is not None:
            return b.apply_text(project, entry, created_by_name)
        return False

    def apply_modified_st_objects(project, report_path):
        record("apply_modified", report_path)
        if b.apply_modified is not None:
            return b.apply_modified(project, report_path)
        return []

    def export_text(params):
        b.export_text_params = params
        record("export_text")
        return b.export_text

    def write_attestation(sync_folder, project, saved=False):
        record("attestation", saved)
        return b.attestation

    def invalidate():
        record("invalidate")

    def project_edit_refusal(project, command):
        if not b.online:
            return None
        return {
            "ok": False,
            "error": (
                "The IDE is online with the PLC; editing the project while "
                "online is not supported. Run `cts disconnect`, then repeat "
                "{0}."
            ).format(command),
        }

    monkeypatch.setattr(
        sync.ide_online_guard, "project_edit_refusal", project_edit_refusal
    )
    monkeypatch.setattr(
        sync,
        "_cmd_sync_export",
        lambda params: {
            "ok": True,
            "data": {"path": b.snapshot, "sync_folder": b.sync_dir},
        },
    )
    monkeypatch.setattr(
        sync._common, "run_external_engine", run_engine, raising=False
    )
    monkeypatch.setattr(
        sync._common,
        "layout",
        lambda root, **kwargs: types.SimpleNamespace(
            backup_root=os.path.join(root, ".backup"),
            view_root=os.path.join(root, "project-view"),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        sync,
        "_get_active_project",
        lambda: (b.project_error, None)
        if b.project_error is not None
        else (b.project, None),
    )
    monkeypatch.setattr(
        sync, "_read_text_utf8", lambda path: open(path, encoding="utf-8").read()
    )
    monkeypatch.setattr(sync, "_apply_text_create_entry", apply_text_create_entry)
    monkeypatch.setattr(sync, "_apply_modified_st_objects", apply_modified_st_objects)
    monkeypatch.setattr(sync, "_cmd_sync_export_text", export_text)
    monkeypatch.setattr(sync, "_write_import_attestation", write_attestation)
    monkeypatch.setattr(sync, "_invalidate_device_cache", invalidate)

    backup_module = types.ModuleType("ide_backup")

    def ensure_pre_import_backup(project, sync_folder, backup_root, patch_path):
        record("backup")
        return b.backup_ok

    backup_module.ensure_pre_import_backup = ensure_pre_import_backup
    monkeypatch.setitem(sys.modules, "ide_backup", backup_module)

    patch_module = types.ModuleType("ide_apply_patch")
    patch_module._native_create_entries = lambda root: b.native_entries

    def apply_native(project, entry):
        record("apply_native", entry.get("name"))
        if entry.get("name") in b.native_failures:
            raise Exception("native boom for {0}".format(entry.get("name")))

    patch_module._apply_native_create = apply_native
    monkeypatch.setitem(sys.modules, "ide_apply_patch", patch_module)

    b.record = record
    return b


def _fb(name="FB_A"):
    return _text_create(name, "App/{0}.st".format(name))


# ── 1. preflight: an online application refuses before anything else ───────


def test_online_application_refuses_before_touching_the_project(bridge):
    bridge.online = True
    result = bridge.run()
    assert result["ok"] is False
    assert "cts disconnect" in result["error"]
    assert "sync_import_text" in result["error"]
    assert bridge.calls == []


def test_the_online_refusal_names_the_command_to_repeat(bridge):
    bridge.online = True
    assert bridge.run()["error"].endswith("repeat sync_import_text.")


def test_a_successful_import_marks_the_project_edited(bridge):
    """The Snapshooter tree cache cannot see an unsaved import; the marker is
    how the daemon records it, so the next `tree` rebuilds."""
    bridge.write_import_xml(text_creates=[_fb()])
    bridge.run()
    assert os.path.exists(os.path.join(bridge.sync_dir, ".dump", "project_edited"))


# ── 2. the export baseline is a precondition ───────────────────────────────


def test_export_failure_is_returned_unchanged(bridge, monkeypatch):
    refusal = {"ok": False, "error": "Sync export error: nope"}
    monkeypatch.setattr(sync, "_cmd_sync_export", lambda params: refusal)
    assert bridge.run() == refusal


# ── 3. a refused engine is reported with its own reason ────────────────────


def test_engine_failure_reports_the_notices_and_applies_nothing(bridge):
    bridge.import_engine_ok = False
    bridge.engine_notices = ["Error: cannot build the import patch: boom"]
    result = bridge.run()
    assert result["ok"] is False
    assert "boom" in result["error"]
    assert "nothing was applied" in result["error"]
    assert bridge.project.save_calls == 0
    assert bridge.project.import_native_calls == []


def test_missing_import_xml_is_reported(bridge):
    os.remove(bridge.patch)
    assert bridge.run() == {"ok": False, "error": "IMPORT.xml was not generated"}


# ── 4. the optional pre-import backup gates everything ─────────────────────


def test_failed_backup_stops_before_the_project_is_read(bridge):
    bridge.backup_ok = False
    result = bridge.run({"save": True})
    assert result["ok"] is False
    assert "Pre-import backup failed; nothing was applied." in result["error"]
    assert "disable pre_import_backup_enabled" in result["error"]
    assert result["error"].endswith("then retry.")
    assert bridge.project.save_calls == 0
    assert bridge.project.import_native_calls == []
    assert "apply_text" not in bridge.effect_names()


def test_backup_is_only_asked_for_when_saving(bridge):
    bridge.run({})
    assert "backup" not in bridge.effect_names()
    bridge.run({"save": True})
    assert "backup" in bridge.effect_names()


# ── 5. nothing to do: the "note" key and no false mutation ─────────────────


def test_nothing_to_do_reports_a_note_and_claims_no_change(bridge):
    result = bridge.run()
    data = result["data"]
    assert result["ok"] is True
    assert data["note"] == (
        "No objects were created, updated, or skipped. "
        "The compare report may show projection-only changes that "
        "cannot be applied automatically; use update-pou or edit "
        "the object in the IDE."
    )
    assert "unsaved" not in data
    assert data["saved"] is False
    assert data["created_text_objects"] == []
    assert data["manifest_refreshed"] is True
    assert bridge.project.save_calls == 0


# ── 6. text creates: created / reused / failed ─────────────────────────────


def test_text_creates_are_partitioned_and_one_failure_does_not_abort(bridge):
    bridge.write_import_xml(
        text_creates=[_fb("FB_OK"), _fb("FB_REUSED"), _fb("FB_BAD"), _fb("FB_LATE")]
    )

    def behaviour(project, entry, created_by_name):
        if entry["name"] == "FB_BAD":
            raise Exception("cannot create FB_BAD")
        return entry["name"] == "FB_REUSED"

    bridge.apply_text = behaviour
    result = bridge.run()
    data = result["data"]
    assert data["created_text_objects"] == ["FB_OK", "FB_LATE"]
    assert data["reused_text_objects"] == ["FB_REUSED"]
    assert data["failed_text_objects"] == [
        {"name": "FB_BAD", "path": "App/FB_BAD.st", "error": "cannot create FB_BAD"}
    ]
    assert bridge.text_creates_in_order() == ["FB_OK", "FB_REUSED", "FB_BAD", "FB_LATE"]


def test_property_accessors_are_read_from_sidecar_files(bridge):
    bridge.write_import_xml(
        text_creates=[_text_create("Prop", "App/Props.st", kind="Property")]
    )
    bridge.write_view(
        "App/Props.st", "FUNCTION_BLOCK Props\n\n// --- implementation ---\n\nx:=1;"
    )
    bridge.write_view(
        "App/Props.Get.st",
        "METHOD Get : INT\n\n// --- implementation ---\n\nGet := 1;",
    )
    bridge.write_view(
        "App/Props.Set.st",
        "METHOD Set\nVAR_INPUT\n    value : INT;\nEND_VAR\n\n"
        "// --- implementation ---\n\nthis.x := value;",
    )

    bridge.run()
    entry = bridge.saved_text_creates[0]
    assert entry["kind"] == "Property"
    assert entry["source_path"] == os.path.join(bridge.views_dir, "App/Props.st")
    assert set(entry["accessors"]) == {"Get", "Set"}
    assert "Get := 1;" in entry["accessors"]["Get"]["implementation"]
    assert "value : INT;" in entry["accessors"]["Set"]["declaration"]


def test_a_non_property_never_looks_for_accessors(bridge):
    bridge.write_import_xml(text_creates=[_fb("FB_A")])
    bridge.write_view(
        "App/FB_A.st", "FUNCTION_BLOCK FB_A\n\n// --- implementation ---\n\nx:=1;"
    )
    bridge.write_view(
        "App/FB_A.Get.st",
        "METHOD Get : INT\n\n// --- implementation ---\n\nGet := 1;",
    )
    bridge.run()
    assert bridge.saved_text_creates[0]["accessors"] == {}


# ── 7. native creates: created and failed ──────────────────────────────────


def test_native_creates_are_partitioned(bridge):
    bridge.write_import_xml(
        native_creates=[_native_create("Visu_A"), _native_create("Visu_Bad")]
    )
    bridge.native_entries = [
        {"name": "Visu_A", "path": "App/Visu_A"},
        {"name": "Visu_Bad", "path": "App/Visu_Bad"},
    ]
    bridge.native_failures = ("Visu_Bad",)
    data = bridge.run()["data"]
    assert data["created_native_objects"] == ["Visu_A"]
    assert data["failed_native_objects"] == [
        {
            "name": "Visu_Bad",
            "path": "App/Visu_Bad",
            "error": "native boom for Visu_Bad",
        }
    ]


# ── 8. the compare report: updated, skipped, ide-only ─────────────────────


def _compare_payload():
    return {
        "objects": {
            "modified": [
                {
                    "name": "POU_A",
                    "guid": "g1",
                    "path": "App/POU_A",
                    "projection_diff": {"format": "st", "disk_content": "x"},
                },
                {
                    "name": "GVL_HMI",
                    "guid": "g2",
                    "path": "App/GVL_HMI",
                    "projection_diff": {"format": "csv", "disk_content": "a,b"},
                },
                {
                    "name": "LEFT_BEHIND",
                    "guid": "g3",
                    "path": "App/LEFT_BEHIND",
                    "projection_diff": {"format": "st", "disk_content": "y"},
                },
            ],
            "deleted": ["gone1", "gone2"],
        }
    }


def test_compare_report_yields_updated_and_skipped(bridge):
    bridge.write_compare_report(_compare_payload())
    bridge.apply_modified = lambda project, path: ["POU_A"]
    data = bridge.run()["data"]
    assert data["updated_text_objects"] == ["POU_A"]
    assert data["skipped_projection_objects"] == [
        {
            "name": "GVL_HMI",
            "path": "App/GVL_HMI",
            "format": "csv",
            "reason": (
                "'csv' projections cannot be applied automatically; "
                "edit the object in the IDE"
            ),
        },
        {
            "name": "LEFT_BEHIND",
            "path": "App/LEFT_BEHIND",
            "format": "st",
            "reason": (
                "projection change not applied automatically; "
                "use update-pou or edit in the IDE"
            ),
        },
    ]
    # A skipped projection still lives on disk alone, so the refresh is withheld.
    assert data["manifest_refreshed"] is False
    assert "2 object(s) have projection changes" in data["manifest_refresh_skipped"]


def test_ide_only_objects_are_reported_when_the_refresh_runs(bridge):
    """The deleted list becomes a visible warning, not a silent rewrite."""
    payload = _compare_payload()
    payload["objects"]["modified"] = payload["objects"]["modified"][:1]
    bridge.write_compare_report(payload)
    bridge.apply_modified = lambda project, path: ["POU_A"]
    data = bridge.run()["data"]
    assert data["manifest_refreshed"] is True
    assert "2 object(s) existed in the IDE but not in" in data[
        "manifest_refresh_restored"
    ]


def test_a_missing_compare_report_is_not_an_error(bridge):
    data = bridge.run()["data"]
    assert data["updated_text_objects"] == []
    assert data["skipped_projection_objects"] == []


# ── 9. StructuredView: best-effort, never fatal ────────────────────────────


def test_structured_view_failure_is_skipped_not_fatal(bridge):
    bridge.write_import_xml(text_creates=[_fb()], structured_view=True)
    bridge.project.import_native_error = Exception("no native import")
    result = bridge.run()
    assert result["ok"] is True
    assert len(bridge.project.import_native_calls) == 1
    # Known behaviour: the cleanup of the temp payload sits *after* the
    # import_native call inside the try, so a raising import leaves the temp
    # file behind.  It is harmless (it is in the OS temp dir) and the handler
    # deliberately swallows the failure, but the file is not removed.
    assert os.path.exists(bridge.project.import_native_calls[0])


def test_structured_view_success_imports_and_removes_the_temp_file(bridge):
    bridge.write_import_xml(text_creates=[_fb()], structured_view=True)
    result = bridge.run()
    assert result["ok"] is True
    assert len(bridge.project.import_native_calls) == 1
    filtered_path = bridge.project.import_native_calls[0]
    assert filtered_path != bridge.patch
    assert not os.path.exists(filtered_path)


def test_a_project_of_only_creates_has_no_structured_view(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    bridge.run()
    assert bridge.project.import_native_calls == []


def test_a_structured_view_alone_counts_as_a_mutation(bridge):
    """A StructuredView applied with no creates still mutates the project, so
    the result must carry the "unsaved" warning rather than claiming nothing
    happened."""
    bridge.write_import_xml(structured_view=True)
    data = bridge.run()["data"]
    assert data["created_text_objects"] == []
    assert data["updated_text_objects"] == []
    assert "unsaved" in data
    assert bridge.project.save_calls == 0


def test_a_structured_view_alone_is_saved_when_asked(bridge):
    bridge.write_import_xml(structured_view=True)
    data = bridge.run({"save": True})["data"]
    assert data["saved"] is True
    assert "unsaved" not in data
    assert bridge.project.save_calls == 1


# ── 10. save is the user's call ────────────────────────────────────────────


def test_without_save_the_result_says_unsaved(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    result = bridge.run()
    data = result["data"]
    assert data["saved"] is False
    assert data["unsaved"].startswith(
        "The project was changed in memory but NOT saved."
    )
    assert "re-run with --save" in data["unsaved"]
    assert "save_error" not in data
    assert bridge.project.save_calls == 0


def test_with_save_success_is_reported(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    result = bridge.run({"save": True})
    assert result["data"]["saved"] is True
    assert "unsaved" not in result["data"]
    assert bridge.project.save_calls == 1


def test_a_save_failure_keeps_the_error_and_still_says_unsaved(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    bridge.project.save_error = Exception("disk full")
    data = bridge.run({"save": True})["data"]
    assert data["saved"] is False
    assert data["save_error"] == "disk full"
    assert data["unsaved"].startswith(
        "The project was changed in memory but NOT saved (disk full)."
    )


# ── 11. the manifest refresh gate ──────────────────────────────────────────


def test_refresh_is_withheld_when_a_create_failed(bridge):
    bridge.write_import_xml(text_creates=[_fb("FB_OK"), _fb("FB_BAD")])

    def behaviour(project, entry, created_by_name):
        if entry["name"] == "FB_BAD":
            raise Exception("boom")
        return False

    bridge.apply_text = behaviour
    data = bridge.run()["data"]
    assert data["created_text_objects"] == ["FB_OK"]
    assert data["manifest_refreshed"] is False
    assert "1 object(s) failed to be created" in data["manifest_refresh_skipped"]
    assert "export_text" not in bridge.effect_names()


def test_a_wholly_failed_import_still_refreshes(bridge):
    """Known behaviour: "mutated" is False when *nothing* was applied, so a run
    whose every create failed is not treated as a blocked refresh -- the
    blocker only fires once at least one edit reached the IDE."""
    bridge.write_import_xml(text_creates=[_fb("FB_BAD")])

    def behaviour(project, entry, created_by_name):
        raise Exception("boom")

    bridge.apply_text = behaviour
    data = bridge.run()["data"]
    assert data["created_text_objects"] == []
    assert data["failed_text_objects"] != []
    assert data["manifest_refreshed"] is True


def test_refresh_succeeds_and_is_recorded(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    data = bridge.run()["data"]
    assert data["manifest_refreshed"] is True
    assert "manifest_refresh_error" not in data


def test_refresh_failure_is_recorded_but_import_still_succeeds(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    bridge.export_text = {"ok": False, "error": "export blew up"}
    result = bridge.run()
    data = result["data"]
    assert result["ok"] is True
    assert data["manifest_refreshed"] is False
    assert "export blew up" in data["manifest_refresh_error"]
    assert bridge.export_text_params["overwrite_dirty"] is True


def test_refresh_can_be_turned_off_entirely(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    result = bridge.run({"refresh": False})
    assert "manifest_refreshed" not in result["data"]
    assert "export_text" not in bridge.effect_names()


# ── 12. the verify attestation ─────────────────────────────────────────────


def test_complete_attestation_records_the_fingerprint(bridge):
    bridge.write_import_xml(text_creates=[_fb()])
    entry = bridge.run()["data"]["verify_import_attestation"]
    assert entry["workspace_fingerprint"] == "fp-1"
    assert isinstance(entry["imported_at"], str) and entry["imported_at"]


def test_incomplete_attestation_records_the_reason(bridge):
    bridge.attestation = {"complete": False, "error": "no fingerprint"}
    assert bridge.run()["data"]["verify_import_attestation"] == {
        "complete": False,
        "reason": "no fingerprint",
    }


def test_attestation_failure_without_a_reason_gets_a_default(bridge):
    bridge.attestation = {"complete": False}
    assert bridge.run()["data"]["verify_import_attestation"] == {
        "complete": False,
        "reason": "workspace fingerprint unavailable",
    }


# ── 13. an exception anywhere inside the try is wrapped ────────────────────


def test_unparsable_import_xml_is_wrapped_in_the_error_shape(bridge):
    with open(bridge.patch, "w") as handle:
        handle.write("<Project><broken>")
    result = bridge.run()
    assert result["ok"] is False
    assert result["error"].startswith("Sync import error: ")


# ── side-effect order on a fully loaded run ────────────────────────────────


def test_side_effect_order_on_a_full_run(bridge):
    bridge.write_import_xml(
        text_creates=[_fb()],
        native_creates=[_native_create("Visu_A")],
        structured_view=True,
    )
    bridge.native_entries = [{"name": "Visu_A", "path": "App/Visu_A"}]
    bridge.write_compare_report(_compare_payload())
    bridge.apply_modified = lambda project, path: ["POU_A"]
    result = bridge.run({"save": True})
    assert result["ok"] is True
    assert bridge.effect_names() == [
        "engine",  # import
        "engine",  # compare
        "backup",  # only because save was requested
        "apply_text",
        "apply_native",
        "apply_modified",
        "attestation",
        "invalidate",
    ]
    assert bridge.calls[0] == ("engine", "import")
    assert bridge.calls[1] == ("engine", "compare")
    assert len(bridge.project.import_native_calls) == 1
    assert result["data"]["saved"] is True


# ── the read-only text property is a fallback, not a failure ───────────────


def test_a_read_only_text_property_reports_the_fallback(monkeypatch):
    """Live, importing MAIN logged "Could not replace text document ..." twice
    before succeeding through the replace API -- it read as a broken import."""
    logged = []
    monkeypatch.setattr(sync, "_log", logged.append)

    class _Doc(object):
        @property
        def text(self):
            return "old"

        @text.setter
        def text(self, value):
            raise AttributeError("can't assign to read-only property text")

        def replace(self, value):
            self.replaced = value

    doc = _Doc()
    assert sync._replace_text_document(doc, "new") is True
    assert doc.replaced == "new"
    assert len(logged) == 1
    assert "using the replace API" in logged[0]
    assert "Could not replace" not in logged[0]


def test_a_writable_text_property_logs_nothing(monkeypatch):
    logged = []
    monkeypatch.setattr(sync, "_log", logged.append)

    class _Doc(object):
        def __init__(self):
            self.text = "old"

    doc = _Doc()
    assert sync._replace_text_document(doc, "new") is True
    assert doc.text == "new"
    assert logged == []
