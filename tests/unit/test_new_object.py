# -*- coding: utf-8 -*-
"""``cts new``: creating a project-view object offline.

The command exists so an agent does not have to know the object's ST shape,
its type GUID, or -- the trap this module exists to pin -- that a ``.st`` with
a sibling ``.xml`` is discovered by *neither* of the reader's pending-object
passes. These tests cover the engine half: what gets written, what is refused,
and that the reader then finds the object as a pending create.

The CLI half (argument parsing, exit codes, the report) lives in
``products/cds-cli/tests/test_new_object_cli.py``.
"""

import json
import os

import pytest

from cds_text_sync.engine import new_object as no
from cds_text_sync.engine.folder_reader import FolderReader


APPLICATION = "Runtime/PLC Logic/Application"


def _make_project(tmp_path, entries=None):
    """A sync folder with a view root, an Application folder and a manifest."""
    root = str(tmp_path)
    views = os.path.join(root, "project-view")
    os.makedirs(os.path.join(views, *APPLICATION.split("/"), "POUs"))
    os.makedirs(os.path.join(root, ".dump"))
    manifest = {
        "view_root": views,
        "ns": "",
        "entries": entries
        if entries is not None
        else [
            {
                "guid": "g1",
                "name": "PLC_PRG",
                "xml_path": "{0}/POUs/PLC_PRG.xml".format(APPLICATION),
            }
        ],
    }
    with open(os.path.join(root, ".dump", "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    return root, views


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _pending(views, root):
    model = FolderReader(views, os.path.join(root, ".dump")).read()
    return [n for n in model.nodes.values() if n.metadata.get("pending_create")]


# -- where a new object lands -------------------------------------------------


class TestParentResolution:
    def test_the_application_folder_is_read_from_the_manifest(self, tmp_path):
        _root, views = _make_project(tmp_path)

        report = no.create_object(str(tmp_path), "gvl", "GVL_A")

        assert report["parent"] == APPLICATION
        assert report["path"] == "{0}/GVL_A.st".format(APPLICATION)
        assert os.path.isfile(os.path.join(views, *report["path"].split("/")))

    def test_an_explicit_parent_wins(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "gvl", "GVL_A", parent=APPLICATION + "/POUs"
        )

        assert report["parent"] == APPLICATION + "/POUs"

    def test_separators_and_dots_in_the_parent_are_normalised(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "gvl", "GVL_A", parent="./" + APPLICATION.replace("/", "\\")
        )

        assert report["parent"] == APPLICATION

    def test_a_parent_that_leaves_the_sync_folder_is_refused(self, tmp_path):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "gvl", "GVL_A", parent="../../etc")

        assert "may not leave the sync folder" in excinfo.value.message

    def test_a_missing_parent_folder_is_refused(self, tmp_path):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "gvl", "GVL_A", parent="No/Such/Folder")

        assert "Parent folder does not exist" in excinfo.value.message

    def test_a_manifest_without_an_application_folder_is_refused(self, tmp_path):
        _make_project(tmp_path, entries=[{"guid": "g", "xml_path": "Elsewhere/X.xml"}])

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "gvl", "GVL_A")

        assert "which folder is the active application" in excinfo.value.message
        assert "--parent" in excinfo.value.message

    def test_the_shortest_application_path_wins_a_tie(self):
        """Several devices each own an Application; the shallowest is the app."""
        manifest = {
            "entries": [
                {"xml_path": "DeviceA/PLC Logic/Application/X.xml"},
                {"xml_path": "App/Application/X.xml"},
            ]
        }
        assert no.default_parent(manifest) == "App/Application"

    def test_a_path_without_an_application_segment_is_not_a_candidate(self):
        manifest = {"entries": [{"xml_path": "App/X.xml"}]}
        assert no.default_parent(manifest) == ""

    def test_the_projection_path_is_consulted_too(self):
        manifest = {"entries": [{"projection_paths": ["A/Application/P.st"]}]}
        assert no.default_parent(manifest) == "A/Application"


# -- the declaration each kind gets ------------------------------------------


class TestBodies:
    def test_a_gvl_wraps_the_declarations_in_var_global(self, tmp_path):
        _root, views = _make_project(tmp_path)

        report = no.create_object(str(tmp_path), "gvl", "GVL_A", text="a : INT;\nb : BOOL;")

        body = _read_text(report["files"][0])
        assert body == "VAR_GLOBAL\n    a : INT;\n    b : BOOL;\nEND_VAR\n"

    def test_a_gvl_accepts_a_whole_var_global_block(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "gvl", "GVL_A", text="VAR_GLOBAL\n  a : INT;\nEND_VAR\n"
        )

        assert _read_text(report["files"][0]) == "VAR_GLOBAL\n  a : INT;\nEND_VAR\n"

    def test_an_empty_gvl_is_still_a_valid_block(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(str(tmp_path), "gvl", "GVL_A")

        assert _read_text(report["files"][0]) == "VAR_GLOBAL\nEND_VAR\n"

    @pytest.mark.parametrize(
        "pou_kind,header",
        [
            ("program", "PROGRAM P_A"),
            ("function-block", "FUNCTION_BLOCK P_A"),
            ("function", "FUNCTION P_A : BOOL"),
        ],
    )
    def test_each_pou_kind_gets_its_header(self, tmp_path, pou_kind, header):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "pou", "P_A", pou_kind=pou_kind, text="x := 1;"
        )

        body = _read_text(report["files"][0])
        assert body.splitlines()[0] == header
        assert "// --- implementation ---" in body
        assert body.rstrip().endswith("x := 1;")

    def test_a_function_uses_the_requested_return_type(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "pou", "FC_A", pou_kind="function", return_type="REAL"
        )

        assert _read_text(report["files"][0]).startswith("FUNCTION FC_A : REAL")

    def test_a_program_marks_an_empty_body(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(str(tmp_path), "pou", "P_A", pou_kind="program")

        assert "empty body" in report["note"]

    @pytest.mark.parametrize(
        "dut_kind,opener,closer",
        [
            ("struct", "STRUCT", "END_STRUCT"),
            ("union", "UNION", "END_UNION"),
        ],
    )
    def test_struct_and_union_wrap_the_members(self, tmp_path, dut_kind, opener, closer):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "dut", "T_A", dut_kind=dut_kind, text="a : INT;"
        )

        body = _read_text(report["files"][0])
        assert body.splitlines() == [
            "TYPE T_A :", opener, "a : INT;", closer, "END_TYPE",
        ]

    def test_an_empty_enum_is_seeded_with_one_member(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(str(tmp_path), "dut", "E_A", dut_kind="enum")

        body = _read_text(report["files"][0])
        assert "Member1 := 0" in body
        assert "seeded with one member" in report["note"]

    def test_an_alias_needs_a_base_type(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "dut", "T_A", dut_kind="alias")

        assert "--base-type" in excinfo.value.message

    def test_an_alias_uses_the_base_type(self, tmp_path):
        _root, _views = _make_project(tmp_path)

        report = no.create_object(
            str(tmp_path), "dut", "T_A", dut_kind="alias", base_type="UINT"
        )

        assert _read_text(report["files"][0]) == "TYPE T_A : UINT;\nEND_TYPE\n"

    def test_a_text_file_supplies_the_body(self, tmp_path):
        _root, _views = _make_project(tmp_path)
        source = tmp_path / "decls.txt"
        source.write_text("a : INT;\n", encoding="utf-8")

        report = no.create_object(
            str(tmp_path), "gvl", "GVL_A", text_file=str(source)
        )

        assert "a : INT;" in _read_text(report["files"][0])

    def test_a_missing_text_file_is_refused(self, tmp_path):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "gvl", "GVL_A", text_file="nope.txt")

        assert "Text file not found" in excinfo.value.message


# -- the refusals -------------------------------------------------------------


class TestValidation:
    @pytest.mark.parametrize("name", ["", "   ", "1Bad", "Has Space", "a-b", "a.b"])
    def test_a_non_identifier_is_refused(self, name):
        with pytest.raises(no.NewObjectError) as excinfo:
            no.validate_name(name)
        assert "identifier" in excinfo.value.message or "required" in excinfo.value.message

    def test_a_reserved_keyword_is_refused(self):
        with pytest.raises(no.NewObjectError) as excinfo:
            no.validate_name("PROGRAM")
        assert "reserved IEC keyword" in excinfo.value.message

    def test_a_valid_name_is_returned_trimmed(self):
        assert no.validate_name("  GVL_A  ") == "GVL_A"

    def test_an_unknown_kind_is_refused(self, tmp_path):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "visu", "S_A")

        assert "Unknown object kind" in excinfo.value.message

    @pytest.mark.parametrize("pou_kind", ["", "subroutine"])
    def test_a_pou_without_a_valid_subkind_is_refused(self, tmp_path, pou_kind):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "pou", "P_A", pou_kind=pou_kind)

        assert "--kind program|function|function-block" in excinfo.value.message

    def test_a_dut_without_a_valid_subkind_is_refused(self, tmp_path):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "dut", "T_A", dut_kind="class")

        assert "--kind struct|enum|union|alias" in excinfo.value.message

    def test_a_non_st_language_is_refused(self, tmp_path):
        _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "pou", "P_A", pou_kind="program", language="sfc")

        assert "Only Structured Text" in excinfo.value.message

    def test_a_missing_view_root_is_refused(self, tmp_path):
        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "gvl", "GVL_A")

        assert "Export the project once" in excinfo.value.message


class TestNameCollisions:
    def test_an_existing_file_is_refused(self, tmp_path):
        _root, views = _make_project(tmp_path)
        no.create_object(str(tmp_path), "gvl", "GVL_A")

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(str(tmp_path), "gvl", "GVL_A")

        assert "already exists" in excinfo.value.message
        # And the first file was not touched.
        body = _read_text(os.path.join(views, *APPLICATION.split("/"), "GVL_A.st"))
        assert body == "VAR_GLOBAL\nEND_VAR\n"

    def test_the_collision_check_ignores_case(self, tmp_path):
        _make_project(tmp_path)
        no.create_object(str(tmp_path), "gvl", "GVL_A")

        with pytest.raises(no.NewObjectError):
            no.create_object(str(tmp_path), "gvl", "gvl_a")

    def test_a_name_the_manifest_knows_is_refused(self, tmp_path):
        """The object may have no files in the view (moved, or xml in .dump)."""
        _make_project(
            tmp_path,
            entries=[
                {
                    "guid": "g1",
                    "name": "PLC_PRG",
                    "xml_path": "{0}/POUs/PLC_PRG.xml".format(APPLICATION),
                }
            ],
        )

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(
                str(tmp_path), "pou", "PLC_PRG", pou_kind="program", parent=APPLICATION + "/POUs"
            )

        assert "already exists" in excinfo.value.message

    def test_a_name_in_another_folder_is_not_a_collision(self, tmp_path):
        _root, _views = _make_project(tmp_path)
        no.create_object(str(tmp_path), "gvl", "GVL_A")

        report = no.create_object(
            str(tmp_path), "gvl", "GVL_A", parent=APPLICATION + "/POUs"
        )

        assert report["path"].endswith("/POUs/GVL_A.st")

    def test_a_cds_object_sidecar_does_not_reserve_a_name(self, tmp_path):
        root, views = _make_project(tmp_path)
        target = os.path.join(views, *APPLICATION.split("/"))
        with open(os.path.join(target, "GVL_A.cds-object.xml"), "w") as fh:
            fh.write("<x/>")

        report = no.create_object(root, "gvl", "GVL_A")

        assert report["name"] == "GVL_A"


# -- the disk state the rest of the flow depends on --------------------------


class TestWhatIsWritten:
    def test_only_the_st_is_written_never_a_sibling_xml(self, tmp_path):
        """A ``.st`` with a sibling ``.xml`` is discovered by neither pass.

        The ST pass skips it (a sibling means "externalized-text projection"),
        and the XML pass skips the pair from the other side -- which is exactly
        the hand-written-manifest trap this command exists to remove.
        """
        root, views = _make_project(tmp_path)

        report = no.create_object(root, "gvl", "GVL_A")

        directory = os.path.join(views, *APPLICATION.split("/"))
        assert report["files"] == [os.path.join(directory, "GVL_A.st")]
        assert not os.path.exists(os.path.join(directory, "GVL_A.xml"))
        assert "discovery" in report

    def test_no_manifest_entry_is_written(self, tmp_path):
        root, _views = _make_project(tmp_path)
        manifest_path = os.path.join(root, ".dump", "manifest.json")
        before = _read_text(manifest_path)

        no.create_object(root, "gvl", "GVL_A")

        assert _read_text(manifest_path) == before

    def test_the_reader_discovers_every_created_kind(self, tmp_path):
        root, views = _make_project(tmp_path)
        no.create_object(root, "gvl", "GVL_A", text="a : INT;")
        no.create_object(root, "pou", "P_A", pou_kind="program")
        no.create_object(root, "dut", "T_A", dut_kind="struct")

        kinds = {n.name: n.metadata["create_kind"] for n in _pending(views, root)}

        assert kinds == {"GVL_A": "gvl", "P_A": "pou", "T_A": "dut"}

    def test_the_discovered_object_carries_its_declaration(self, tmp_path):
        root, views = _make_project(tmp_path)
        no.create_object(root, "gvl", "GVL_A", text="a : INT;")

        node = _pending(views, root)[0]

        assert node.metadata["create_declaration"] == "VAR_GLOBAL\n    a : INT;\nEND_VAR"

    def test_the_discovered_pou_splits_declaration_from_implementation(self, tmp_path):
        root, views = _make_project(tmp_path)
        no.create_object(root, "pou", "P_A", pou_kind="program", text="x := 1;")

        node = _pending(views, root)[0]

        assert "PROGRAM P_A" in node.metadata["create_declaration"]
        assert node.metadata["create_implementation"] == "x := 1;"

    def test_the_report_points_at_the_next_commands(self, tmp_path):
        root, _views = _make_project(tmp_path)

        report = no.create_object(root, "gvl", "GVL_A")

        joined = "\n".join(report["next"])
        assert "cts compare" in joined
        assert "cts import" in joined
        assert "cts download" in joined
        assert "full download" in joined

    def test_a_gvl_report_says_it_must_be_referenced_first(self, tmp_path):
        """CODESYS compiles out an object nothing calls: the reminder is the
        difference between a full download that works and one that does not."""
        root, _views = _make_project(tmp_path)

        report = no.create_object(root, "gvl", "GVL_A")

        joined = "\n".join(report["next"])
        assert "the PLC never gets it" in joined
        assert "reachable from a task's call tree" in joined

    def test_a_dut_report_has_no_reference_step(self, tmp_path):
        root, _views = _make_project(tmp_path)

        report = no.create_object(root, "dut", "ST_A", dut_kind="struct")

        joined = "\n".join(report["next"])
        assert "the PLC never gets it" not in joined
        assert "cts download" in joined

    def test_the_report_names_the_type_guid_for_this_kind(self, tmp_path):
        root, _views = _make_project(tmp_path)

        report = no.create_object(root, "gvl", "GVL_A")

        assert report["type_guid"] == no.KIND_TYPE_GUIDS["gvl"] == (
            "ffbfa93a-b94d-45fc-a329-229860183b1d"
        )

    def test_the_written_file_is_utf8_with_lf_endings(self, tmp_path):
        root, _views = _make_project(tmp_path)

        report = no.create_object(root, "gvl", "GVL_A", text="Temperatur : REAL;")

        raw = open(report["files"][0], "rb").read()
        assert b"\r\n" not in raw
        assert raw.decode("utf-8") == "VAR_GLOBAL\n    Temperatur : REAL;\nEND_VAR\n"

    def test_the_subkind_fields_appear_only_when_set(self, tmp_path):
        root, _views = _make_project(tmp_path)

        gvl = no.create_object(root, "gvl", "GVL_A")
        pou = no.create_object(root, "pou", "P_A", pou_kind="function", return_type="REAL")

        assert "pou_kind" not in gvl and "return_type" not in gvl
        assert pou["pou_kind"] == "function" and pou["return_type"] == "REAL"


class TestRootResolution:
    def test_an_explicit_view_root_is_honoured(self, tmp_path):
        root, _views = _make_project(tmp_path)
        other = os.path.join(root, "elsewhere")
        os.makedirs(os.path.join(other, *APPLICATION.split("/")))

        report = no.create_object(root, "gvl", "GVL_A", view_root=other)

        assert report["view_root"] == other
        assert os.path.isfile(os.path.join(other, *APPLICATION.split("/"), "GVL_A.st"))

    def test_the_project_settings_view_root_is_honoured(self, tmp_path):
        root, _views = _make_project(tmp_path)
        os.makedirs(os.path.join(root, "views", *APPLICATION.split("/")))
        with open(os.path.join(root, "cds-text-sync.json"), "w", encoding="utf-8") as fh:
            json.dump({"view_root": "views"}, fh)

        report = no.create_object(root, "gvl", "GVL_A")

        assert report["view_root"] == os.path.join(root, "views")

    def test_a_project_view_path_is_not_a_sync_folder(self, tmp_path):
        """The engine wants the sync root; stripping project-view is the CLI's job."""
        _root, views = _make_project(tmp_path)

        with pytest.raises(no.NewObjectError) as excinfo:
            no.create_object(views, "gvl", "GVL_A")

        assert "No view root at" in excinfo.value.message


# -- the round trip the command exists to enable -----------------------------


class TestRoundTrip:
    """new -> compare -> import, offline, up to the IMPORT.xml patch.

    The daemon half (creating the object in CODESYS) needs a live IDE and is
    covered on the VM; what can be checked here is that the file the command
    writes is discovered, diffed as ``added`` and turned into a
    ``CreateTextObjects`` entry -- i.e. that no manifest entry was ever needed.
    """

    def _setup(self, tmp_path):
        """A view whose manifest knows no objects yet.

        The manifest entry ``_make_project`` adds by default is a *statement
        about the IDE* as well as about the disk, so a project that "has" an
        object the IDE does not would report it deleted and take the patch
        down a different branch. The round trip wants only the objects this
        test creates, so it starts from an empty inventory.
        """
        return _make_project(tmp_path, entries=[])

    def _diff_and_patch(self, root, views):
        from cds_text_sync.engine._project_model import ProjectModel
        from cds_text_sync.engine._patch_builder import PatchBuilder
        from cds_text_sync.engine.diff_engine import DiffEngine

        folder = FolderReader(views, os.path.join(root, ".dump")).read()
        ide = ProjectModel()
        diff = DiffEngine(ide, folder).compare()
        output = os.path.join(root, ".dump", "IMPORT.xml")
        builder = PatchBuilder(diff, ide, folder)
        emitted = builder.build_patch(output)
        return diff, emitted, _read_text(output)

    def test_a_new_object_is_added_and_becomes_a_text_create(self, tmp_path):
        import xml.etree.ElementTree as ET

        root, views = self._setup(tmp_path)
        no.create_object(
            root, "gvl", "GVL_HMI", text="xStart : BOOL;", parent=APPLICATION
        )

        diff, emitted, patch = self._diff_and_patch(root, views)

        assert len(diff["added"]) == 1
        assert diff["added"][0].startswith("create:")
        assert emitted is True
        creates = ET.fromstring(patch).findall(".//CreateTextObject")
        assert len(creates) == 1
        assert creates[0].attrib["Name"] == "GVL_HMI"
        assert creates[0].attrib["Kind"] == "gvl"
        assert creates[0].attrib["Path"] == "{0}/GVL_HMI.st".format(APPLICATION)
        declaration = creates[0].find("Declaration").text
        assert "xStart : BOOL;" in declaration

    def test_every_created_kind_reaches_the_patch(self, tmp_path):
        import xml.etree.ElementTree as ET

        root, views = self._setup(tmp_path)
        no.create_object(root, "gvl", "GVL_A", text="a : INT;", parent=APPLICATION)
        no.create_object(
            root, "pou", "P_A", pou_kind="program", text="x := 1;", parent=APPLICATION
        )
        no.create_object(
            root, "dut", "T_A", dut_kind="struct", text="a : INT;", parent=APPLICATION
        )

        diff, emitted, patch = self._diff_and_patch(root, views)

        assert len(diff["added"]) == 3
        assert emitted is True
        by_name = {
            elem.attrib["Name"]: elem
            for elem in ET.fromstring(patch).findall(".//CreateTextObject")
        }
        assert by_name["GVL_A"].attrib["Kind"] == "gvl"
        assert by_name["P_A"].attrib["Kind"] == "pou"
        assert by_name["T_A"].attrib["Kind"] == "dut"
        # The POU keeps its body on the implementation side of the marker.
        assert by_name["P_A"].find("Implementation").text == "x := 1;"

    def test_a_gvl_written_by_hand_with_a_sibling_xml_is_discovered_by_nothing(
        self, tmp_path
    ):
        """Why the command writes only the .st: the pair is invisible.

        This is the trap the hand-written workflow fell into. Pinned here so
        the reason for ``files`` holding exactly one path is not lost.
        """
        root, views = _make_project(tmp_path)
        directory = os.path.join(views, *APPLICATION.split("/"))
        with open(os.path.join(directory, "GVL_HAND.st"), "w", encoding="utf-8") as fh:
            fh.write("VAR_GLOBAL\n    a : INT;\nEND_VAR\n")
        with open(os.path.join(directory, "GVL_HAND.xml"), "w", encoding="utf-8") as fh:
            fh.write("<Single Type='{ffbfa93a-b94d-45fc-a329-229860183b1d}'/>")

        assert _pending(views, root) == []

    def test_a_lone_st_written_by_hand_is_discovered(self, tmp_path):
        """And this is what the command relies on -- no manifest entry needed."""
        root, views = _make_project(tmp_path)
        directory = os.path.join(views, *APPLICATION.split("/"))
        with open(os.path.join(directory, "GVL_HAND.st"), "w", encoding="utf-8") as fh:
            fh.write("VAR_GLOBAL\n    a : INT;\nEND_VAR\n")

        pending = _pending(views, root)

        assert len(pending) == 1
        assert pending[0].metadata["create_kind"] == "gvl"
