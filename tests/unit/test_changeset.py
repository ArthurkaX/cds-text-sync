# -*- coding: utf-8 -*-
"""
test_changeset.py – Unit tests for _changeset.py.

Which files `cts patch save` hands over: the hand-authored text only. The point
of this module is exclusion, so most of these tests pin what must NOT ship.
"""

from cds_text_sync.engine._changeset import (
    authored_paths_for_entry,
    select_changeset,
)

POU_GUID = "6f9dac99-8de1-4efc-8465-68ac443b7d08"
VISU_GUID = "f18bec89-9fef-401d-9953-2f11739a6808"
DEVICE_GUID = "225bfe47-7336-11d0-92df-00a0c9055ac0"

PROFILE = {
    "guid_aliases": {
        "pou": [POU_GUID],
        "visu": [VISU_GUID],
        "device": [DEVICE_GUID],
    }
}

SETTINGS = {"xml_in_view_kinds": ["visu"], "sync_mode": "text_first"}


def _report(modified=(), added=(), deleted=()):
    return {
        "objects": {
            "modified": list(modified),
            "added": list(added),
            "deleted": list(deleted),
        }
    }


def _object(guid, name, type_guid, view_path="", projection_path=""):
    info = {
        "guid": guid,
        "name": name,
        "type_guid": type_guid,
        "path": "Application/" + name,
        "view_path": view_path,
    }
    if projection_path:
        info["projection_diff"] = {"path": projection_path, "format": "st"}
    return info


def _manifest(*entries):
    return {"entries": list(entries)}


# ===================================================================
# authored_paths_for_entry
# ===================================================================


class TestAuthoredPathsForEntry:
    def test_pou_ships_its_st_and_not_its_mirrored_xml(self):
        entry = {
            "xml_path": "Application/PLC_PRG.xml",
            "xml_root": "dump",
            "projection_paths": ["Application/PLC_PRG.st"],
        }
        authored, skipped = authored_paths_for_entry(entry, ["visu"], "pou")
        assert authored == ["Application/PLC_PRG.st"]
        assert skipped == ["Application/PLC_PRG.xml"]

    def test_visu_xml_in_the_view_is_authored(self):
        entry = {"xml_path": "HMI/Visu/Main.xml"}
        authored, skipped = authored_paths_for_entry(entry, ["visu"], "visu")
        assert authored == ["HMI/Visu/Main.xml"]
        assert skipped == []

    def test_visu_xml_in_the_dump_mirror_is_not_shipped(self):
        entry = {"xml_path": "HMI/Visu/Main.xml", "xml_root": "dump"}
        authored, _ = authored_paths_for_entry(entry, ["visu"], "visu")
        assert authored == []

    def test_view_rooted_xml_of_another_kind_is_never_authored(self):
        """Device XML sits in the view in xml-first mode but encodes the
        sender's machine state; it must not travel."""
        entry = {"xml_path": "Device.xml"}
        authored, skipped = authored_paths_for_entry(entry, ["visu"], "device")
        assert authored == []
        assert skipped == ["Device.xml"]

    def test_unknown_kind_never_ships_xml(self):
        entry = {"xml_path": "Unknown.xml"}
        authored, skipped = authored_paths_for_entry(entry, ["visu"], None)
        assert authored == []
        assert skipped == ["Unknown.xml"]

    def test_csv_projection_ships_alongside_authored_visu_xml(self):
        entry = {
            "xml_path": "HMI/TextList.xml",
            "projection_paths": ["HMI/TextList.csv"],
        }
        authored, skipped = authored_paths_for_entry(entry, ["visu"], "visu")
        assert authored == ["HMI/TextList.xml", "HMI/TextList.csv"]
        assert skipped == []

    def test_csv_ships_even_when_the_xml_does_not(self):
        entry = {
            "xml_path": "HMI/TextList.xml",
            "projection_paths": ["HMI/TextList.csv"],
        }
        authored, skipped = authored_paths_for_entry(entry, ["visu"], "textlist")
        assert authored == ["HMI/TextList.csv"]
        assert skipped == ["HMI/TextList.xml"]


# ===================================================================
# select_changeset
# ===================================================================


class TestSelectChangeset:
    def test_modified_pou_contributes_only_its_st(self):
        report = _report(modified=[_object("g1", "PLC_PRG", POU_GUID)])
        manifest = _manifest(
            {
                "guid": "g1",
                "type_guid": POU_GUID,
                "xml_path": "Application/PLC_PRG.xml",
                "xml_root": "dump",
                "projection_paths": ["Application/PLC_PRG.st"],
            }
        )
        result = select_changeset(report, manifest, SETTINGS, PROFILE)
        assert [item["path"] for item in result["files"]] == [
            "Application/PLC_PRG.st"
        ]
        assert result["files"][0]["kind"] == "pou"
        assert result["files"][0]["status"] == "modified"
        assert result["skipped_non_text"] == 1

    def test_modified_visu_contributes_its_xml(self):
        report = _report(modified=[_object("g2", "Main", VISU_GUID)])
        manifest = _manifest(
            {"guid": "g2", "type_guid": VISU_GUID, "xml_path": "HMI/Visu/Main.xml"}
        )
        result = select_changeset(report, manifest, SETTINGS, PROFILE)
        assert [item["path"] for item in result["files"]] == ["HMI/Visu/Main.xml"]

    def test_device_object_contributes_nothing_and_is_counted(self):
        report = _report(modified=[_object("g3", "Device", DEVICE_GUID)])
        manifest = _manifest(
            {"guid": "g3", "type_guid": DEVICE_GUID, "xml_path": "Device.xml"}
        )
        result = select_changeset(report, manifest, SETTINGS, PROFILE)
        assert result["files"] == []
        assert result["skipped_non_text"] == 1

    def test_added_object_without_manifest_entry_falls_back_to_the_report(self):
        report = _report(
            added=[
                _object(
                    "g4",
                    "NewPrg",
                    POU_GUID,
                    view_path="Application/NewPrg.xml",
                    projection_path="Application/NewPrg.st",
                )
            ]
        )
        result = select_changeset(report, _manifest(), SETTINGS, PROFILE)
        assert [item["path"] for item in result["files"]] == [
            "Application/NewPrg.st"
        ]
        assert result["files"][0]["status"] == "added"

    def test_added_visu_without_manifest_entry_ships_its_view_xml(self):
        report = _report(
            added=[_object("g5", "NewVisu", VISU_GUID, view_path="HMI/NewVisu.xml")]
        )
        result = select_changeset(report, None, SETTINGS, PROFILE)
        assert [item["path"] for item in result["files"]] == ["HMI/NewVisu.xml"]

    def test_deleted_objects_produce_no_files_but_are_recorded(self):
        report = _report(deleted=[_object("g6", "OldPrg", POU_GUID)])
        manifest = _manifest(
            {
                "guid": "g6",
                "type_guid": POU_GUID,
                "projection_paths": ["Application/OldPrg.st"],
            }
        )
        result = select_changeset(report, manifest, SETTINGS, PROFILE)
        assert result["files"] == []
        assert result["deleted"] == [
            {"guid": "g6", "name": "OldPrg", "path": "Application/OldPrg"}
        ]

    def test_a_path_owned_by_two_objects_is_emitted_once(self):
        report = _report(
            modified=[
                _object("g7", "A", POU_GUID),
                _object("g8", "B", POU_GUID),
            ]
        )
        shared = ["Application/Shared.st"]
        manifest = _manifest(
            {"guid": "g7", "type_guid": POU_GUID, "projection_paths": shared},
            {"guid": "g8", "type_guid": POU_GUID, "projection_paths": shared},
        )
        result = select_changeset(report, manifest, SETTINGS, PROFILE)
        assert [item["path"] for item in result["files"]] == shared

    def test_braced_manifest_guids_still_match_the_report(self):
        report = _report(modified=[_object("G9", "PLC_PRG", POU_GUID)])
        manifest = _manifest(
            {
                "guid": "{g9}",
                "type_guid": POU_GUID,
                "projection_paths": ["Application/PLC_PRG.st"],
            }
        )
        result = select_changeset(report, manifest, SETTINGS, PROFILE)
        assert [item["path"] for item in result["files"]] == [
            "Application/PLC_PRG.st"
        ]

    def test_empty_report_yields_an_empty_changeset(self):
        result = select_changeset({}, None, SETTINGS, PROFILE)
        assert result == {"files": [], "deleted": [], "skipped_non_text": 0}
