# -*- coding: utf-8 -*-
"""
test_snapshot_reader.py -- Edge-case tests for SnapshotReader.read().

Regression guard: read() must return None (not raise) when the snapshot
parses but contains no EntryList. Previously line 193 did `return model`
before `model` was defined, raising NameError on that path.
"""

import os

from cds_text_sync.engine.snapshot_reader import SnapshotReader


def test_read_returns_none_when_no_entry_list(tmp_path):
    snap = tmp_path / "no_entry_list.xml"
    snap.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<root xmlns="http://example.com/ns"><Nothing /></root>',
        encoding="utf-8",
    )
    # Must return None gracefully, matching the parse-error path, so callers
    # like resources_report (which checks `if model is None`) work.
    assert SnapshotReader(str(snap)).read() is None


def test_read_returns_none_on_parse_error(tmp_path):
    snap = tmp_path / "broken.xml"
    snap.write_text("<not-well-formed", encoding="utf-8")
    assert SnapshotReader(str(snap)).read() is None


_CASE_SPLIT_TEMPLATE = u"""<?xml version="1.0" encoding="utf-8"?>
<Project>
  <StructuredView Guid="{{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">dddddddd-dddd-dddd-dddd-dddddddddddd</Single>
            <Single Name="ParentGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>
            <Single Name="Name" Type="string">PLC_Stabur</Single>
            <Single Name="TypeGuid" Type="System.Guid">225bfe47-7336-4dbc-9419-4105a7c831fa</Single>
          </Single>
          <Array Name="Path" Type="string" />
        </Single>
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">llllllll-llll-llll-llll-llllllllllll</Single>
            <Single Name="ParentGuid" Type="System.Guid">dddddddd-dddd-dddd-dddd-dddddddddddd</Single>
            <Single Name="Name" Type="string">Plc Logic</Single>
            <Single Name="TypeGuid" Type="System.Guid">40b404f9-e5dc-42c6-907f-c89f4a517386</Single>
          </Single>
          <Array Name="Path" Type="string"><Single Type="string">PLC_Stabur</Single></Array>
        </Single>
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">aaaaaaaa-1111-1111-1111-111111111111</Single>
            <Single Name="ParentGuid" Type="System.Guid">llllllll-llll-llll-llll-llllllllllll</Single>
            <Single Name="Name" Type="string">Application</Single>
            <Single Name="TypeGuid" Type="System.Guid">639b491f-5557-464c-af91-1471bac9f549</Single>
          </Single>
          <Array Name="Path" Type="string"><Single Type="string">PLC_Stabur</Single><Single Type="string">PLC Logic</Single></Array>
        </Single>
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">bbbbbbbb-1111-1111-1111-111111111111</Single>
            <Single Name="ParentGuid" Type="System.Guid">aaaaaaaa-1111-1111-1111-111111111111</Single>
            <Single Name="Name" Type="string">Library Manager</Single>
            <Single Name="TypeGuid" Type="System.Guid">adb5cb65-8e1d-4a00-b70a-375ea27582f3</Single>
          </Single>
          <Array Name="Path" Type="string"><Single Type="string">PLC_Stabur</Single><Single Type="string">PLC Logic</Single><Single Type="string">Application</Single></Array>
        </Single>
      </List2>
    </Single>
  </StructuredView>
</Project>"""


def _read_case_split_model(tmp_path):
    snap = tmp_path / "IDE.xml"
    snap.write_text(_CASE_SPLIT_TEMPLATE, encoding="utf-8")
    model = SnapshotReader(str(snap)).read()
    assert model is not None
    return model


def test_child_display_path_follows_the_parent_name_casing(tmp_path):
    """A child Path array ("PLC Logic") that disagrees in case with the parent
    object's Name ("Plc Logic") must not become a directory of its own: the
    writer turns display_path straight into directories, so on a case-sensitive
    filesystem the two spellings split one object across two siblings and the
    IDE then reports a failed casing normalization."""
    model = _read_case_split_model(tmp_path)
    nodes = {node.name: node for node in model.nodes.values()}

    assert nodes["Application"].display_path == ["PLC_Stabur", "Plc Logic"]
    assert nodes["Library Manager"].display_path == [
        "PLC_Stabur",
        "Plc Logic",
        "Application",
    ]
    assert nodes["Plc Logic"].display_path == ["PLC_Stabur"]
    assert nodes["PLC_Stabur"].display_path == []


def test_corrected_child_path_nests_under_the_parent_view_path(tmp_path):
    model = _read_case_split_model(tmp_path)
    nodes = {node.name: node for node in model.nodes.values()}

    assert nodes["Application"].get_view_path(model) == os.path.join(
        "PLC_Stabur", "Plc Logic", "Application", ".cds-object.xml"
    )
    assert nodes["Library Manager"].get_view_path(model) == os.path.join(
        "PLC_Stabur", "Plc Logic", "Application", "Library Manager.xml"
    )


def test_path_that_does_not_match_the_parent_chain_is_left_alone(tmp_path):
    """Objects CODESYS deliberately places on another branch (embedded
    resources, pathless standard containers) keep their recorded path."""
    snap = tmp_path / "IDE.xml"
    snap.write_text(
        _CASE_SPLIT_TEMPLATE.replace(
            "<Single Type=\"string\">PLC_Stabur</Single>"
            "<Single Type=\"string\">PLC Logic</Single>"
            "<Single Type=\"string\">Application</Single>",
            "<Single Type=\"string\">Resources</Single>"
            "<Single Type=\"string\">Embedded</Single>",
        ),
        encoding="utf-8",
    )
    model = SnapshotReader(str(snap)).read()
    nodes = {node.name: node for node in model.nodes.values()}

    assert nodes["Library Manager"].display_path == ["Resources", "Embedded"]
