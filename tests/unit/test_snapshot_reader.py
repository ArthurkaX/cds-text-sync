# -*- coding: utf-8 -*-
"""
test_snapshot_reader.py -- Edge-case tests for SnapshotReader.read().

Regression guard: read() must return None (not raise) when the snapshot
parses but contains no EntryList. Previously line 193 did `return model`
before `model` was defined, raising NameError on that path.
"""

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
