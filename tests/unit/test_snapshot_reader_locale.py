# -*- coding: utf-8 -*-
"""
test_snapshot_reader_locale.py -- SnapshotReader folds localized Path segments.

On a non-English CODESYS UI locale the native XML <Array Name="Path"> carries
localized standard-container labels (e.g. zh-CN "PLC<logic>") while the object's
own Name stays English. The reader must normalize display_path to English so the
on-disk tree and import resolution are locale-independent -- and must leave an
already-English snapshot untouched.
"""

from cds_text_sync.engine.snapshot_reader import SnapshotReader

_TEMPLATE = u"""<?xml version="1.0" encoding="utf-8"?>
<Project>
  <StructuredView Guid="{{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}}">
    <Single>
      <List2 Name="EntryList">
        <Single>
          <Single Name="MetaObject">
            <Single Name="Guid" Type="System.Guid">11111111-1111-1111-1111-111111111111</Single>
            <Single Name="ParentGuid" Type="System.Guid">00000000-0000-0000-0000-000000000000</Single>
            <Single Name="Name" Type="string">FB_Test</Single>
            <Single Name="TypeGuid" Type="System.Guid">6f9dac99-8de1-4efc-8465-68ac443b7d08</Single>
          </Single>
          <Array Name="Path"><Single Type="string">Device</Single><Single Type="string">{plc}</Single><Single Type="string">Application</Single></Array>
          <Single Name="Object">
            <Single Name="Implementation">
              <Single Name="TextDocument">
                <Single Name="TextBlobForSerialisation">x := 1;</Single>
              </Single>
            </Single>
          </Single>
        </Single>
      </List2>
    </Single>
  </StructuredView>
</Project>"""


def _read_display_path(tmp_path, plc_segment):
    snap = tmp_path / "IDE.xml"
    snap.write_text(_TEMPLATE.format(plc=plc_segment), encoding="utf-8")
    model = SnapshotReader(str(snap)).read()
    assert model is not None
    node = list(model.nodes.values())[0]
    return node.display_path


def test_localized_plc_logic_segment_is_folded_to_english(tmp_path):
    assert _read_display_path(tmp_path, u"PLC逻辑") == ["Device", "Plc Logic", "Application"]


def test_english_snapshot_is_unchanged(tmp_path):
    # No-op guarantee for the English locale (the common case).
    assert _read_display_path(tmp_path, u"Plc Logic") == ["Device", "Plc Logic", "Application"]


def test_localized_and_english_produce_identical_paths(tmp_path):
    localized = _read_display_path(tmp_path, u"PLC逻辑")
    english = _read_display_path(tmp_path, u"Plc Logic")
    assert localized == english
