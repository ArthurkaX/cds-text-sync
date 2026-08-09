# -*- coding: utf-8 -*-
"""
test_library_resolution.py – Unit tests for _library_resolution.py.

Harvesting the effective library set out of a project model, and spotting the
version drift that makes the IDE regenerate every visualization object.
"""

from cds_text_sync.engine._library_resolution import (
    describe_drift,
    resolution_drift,
    resolution_from_model,
)
from cds_text_sync.engine._project_model import ProjectModel, ProjectNode


def _node(guid, xml_text=None, code=None):
    node = ProjectNode(guid, "Obj" + guid)
    node.xml_text = xml_text
    node.code = code
    return node


def _model(*nodes):
    model = ProjectModel()
    for node in nodes:
        model.add_node(node)
    return model


def _library_xml(*entries):
    return "<Root>" + "".join(
        '<Single Name="LibraryId" Type="string">{0}</Single>'.format(entry)
        for entry in entries
    ) + "</Root>"


# ===================================================================
# resolution_from_model
# ===================================================================


class TestResolutionFromModel:
    def test_collects_names_and_versions_across_nodes(self):
        model = _model(
            _node("1", _library_xml("VisuElemBase, 4.5.0.0 (system)")),
            _node("2", _library_xml("cmpvisuhandler, 3.5.18.0 (system)")),
        )
        assert resolution_from_model(model) == {
            "visuelembase": ("4.5.0.0",),
            "cmpvisuhandler": ("3.5.18.0",),
        }

    def test_merges_and_sorts_multiple_versions_of_one_library(self):
        model = _model(
            _node("1", _library_xml("VisuElemsWinControls, 4.9.0.0 (system)")),
            _node("2", _library_xml("visuelemswincontrols, 4.2.0.0 (system)")),
        )
        assert resolution_from_model(model) == {
            "visuelemswincontrols": ("4.2.0.0", "4.9.0.0")
        }

    def test_skips_nodes_without_xml_text(self):
        model = _model(_node("1", None, code="PROGRAM MAIN\nEND_PROGRAM"))
        assert resolution_from_model(model) == {}

    def test_ignores_unparseable_library_entries(self):
        model = _model(_node("1", _library_xml("no version here")))
        assert resolution_from_model(model) == {}

    def test_ignores_the_declared_placeholder_default(self):
        # DefaultResolution does not move when the effective resolution does,
        # so it must never be mistaken for the signal.
        xml = (
            "<Root><Single Name=\"DefaultResolution\" Type=\"string\">"
            "VisuElemsWinControls, 4.5.0.0 (System)</Single></Root>"
        )
        assert resolution_from_model(_model(_node("1", xml))) == {}

    def test_reads_both_attribute_quoting_styles(self):
        single_quoted = (
            "<Root><Single Name='LibraryId' Type='string'>"
            "VisuElemBase, 4.5.0.0 (system)</Single></Root>"
        )
        assert resolution_from_model(_model(_node("1", single_quoted))) == {
            "visuelembase": ("4.5.0.0",)
        }

    def test_ignores_similarly_named_neighbours(self):
        xml = (
            "<Root><Null Name=\"EnumValueLibraryId\" />"
            "<Single Name=\"LibraryId\" Type=\"string\">"
            "VisuElemBase, 4.5.0.0 (system)</Single></Root>"
        )
        assert resolution_from_model(_model(_node("1", xml))) == {
            "visuelembase": ("4.5.0.0",)
        }


# ===================================================================
# resolution_drift
# ===================================================================


class TestResolutionDrift:
    def test_identical_sets_do_not_drift(self):
        resolution = {"visuelembase": ("4.5.0.0",)}
        assert resolution_drift(resolution, dict(resolution)) == []

    def test_reports_the_library_whose_version_moved(self):
        drift = resolution_drift(
            {"visuelemswincontrols": ("4.2.0.0", "4.9.0.0"), "visuelembase": ("4.5.0.0",)},
            {"visuelemswincontrols": ("4.2.0.0", "4.5.0.0"), "visuelembase": ("4.5.0.0",)},
        )
        assert drift == [
            {
                "library": "visuelemswincontrols",
                "disk": ["4.2.0.0", "4.9.0.0"],
                "ide": ["4.2.0.0", "4.5.0.0"],
            }
        ]

    def test_reports_a_library_present_on_only_one_side(self):
        drift = resolution_drift({"extra": ("1.0.0.0",)}, {})
        assert drift == [{"library": "extra", "disk": ["1.0.0.0"], "ide": []}]

    def test_rows_are_sorted_by_library_name(self):
        drift = resolution_drift(
            {"zlib": ("1.0.0.0",), "alib": ("1.0.0.0",)}, {}
        )
        assert [row["library"] for row in drift] == ["alib", "zlib"]


# ===================================================================
# describe_drift
# ===================================================================


class TestDescribeDrift:
    def test_renders_one_line_per_library(self):
        lines = describe_drift(
            [
                {
                    "library": "visuelemswincontrols",
                    "disk": ["4.9.0.0"],
                    "ide": ["4.5.0.0"],
                }
            ]
        )
        assert lines == ["visuelemswincontrols: disk 4.9.0.0 -> IDE 4.5.0.0"]

    def test_marks_a_side_that_has_no_version_at_all(self):
        lines = describe_drift([{"library": "extra", "disk": ["1.0.0.0"], "ide": []}])
        assert lines == ["extra: disk 1.0.0.0 -> IDE (absent)"]

    def test_empty_drift_renders_nothing(self):
        assert describe_drift([]) == []
