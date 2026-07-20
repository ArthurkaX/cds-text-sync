# -*- coding: utf-8 -*-
"""
test_engine_cli_helpers.py – Unit tests for engine_cli.py helper functions
(Priority 6).

These are helper-level unit tests, not full subprocess tests.
"""

import argparse
import io
import sys

import pytest

from engine_cli import _configure_stdio_utf8, _filter_diff_result, _filter_guids, _log

# ===================================================================
# _filter_guids
# ===================================================================


class TestFilterGuids:
    def _make_args(self, filter_guids_value):
        args = argparse.Namespace(filter_guids=filter_guids_value)
        return args

    def test_comma_separated_values(self):
        args = self._make_args(
            [
                "{a1b2c3d4-e5f6-7890-abcd-ef1234567890}, {b2c3d4e5-f6a7-8901-bcde-f12345678901}"
            ]
        )
        result = _filter_guids(args)
        assert len(result) == 2

    def test_semicolon_separated_values(self):
        args = self._make_args(
            [
                "{a1b2c3d4-e5f6-7890-abcd-ef1234567890}; {b2c3d4e5-f6a7-8901-bcde-f12345678901}"
            ]
        )
        result = _filter_guids(args)
        assert len(result) == 2

    def test_repeated_values_are_deduplicated(self):
        args = self._make_args(["abc", "abc"])
        result = _filter_guids(args)
        assert len(result) == 1

    def test_braces_and_uppercase_are_normalized(self):
        args = self._make_args(["{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"])
        result = _filter_guids(args)
        assert result[0] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_empty_list_returns_empty(self):
        args = self._make_args([])
        result = _filter_guids(args)
        assert result == []


# ===================================================================
# _filter_diff_result
# ===================================================================


class TestFilterDiffResult:
    def test_filters_list_categories(self):
        diff = {
            "modified": ["g1", "g2", "g3"],
            "added": ["g4"],
            "deleted": [],
            "unchanged": [],
        }
        result = _filter_diff_result(diff, ["g1", "g3"])
        assert result["modified"] == ["g1", "g3"]
        assert result["added"] == []

    def test_filters_dict_categories(self):
        diff = {
            "modified": ["g1"],
            "unsupported_projection_changes": {
                "g1": ["path1"],
                "g2": ["path2"],
            },
        }
        result = _filter_diff_result(diff, ["g1"])
        assert "g1" in result["unsupported_projection_changes"]
        assert "g2" not in result["unsupported_projection_changes"]

    def test_returns_original_shape_when_no_filter(self):
        diff = {
            "modified": ["g1"],
            "added": ["g2"],
            "deleted": [],
            "unchanged": [],
            "projection_conflicts": ["g1"],
        }
        result = _filter_diff_result(diff, None)
        assert result == diff


# ===================================================================
# _configure_stdio_utf8 (regression: non-ASCII diagnostic prints)
# ===================================================================


class TestConfigureStdioUtf8:
    """A legacy Windows codepage (cp1252) stdout crashes on non-ASCII log lines.

    Embedded-resource objects carry their original import path as their name,
    which is frequently Cyrillic. When compare logs such a node, the bare
    print() in _log raised UnicodeEncodeError and the engine exited non-zero,
    surfacing to the daemon as "external engine compare failed". The fix forces
    stdout/stderr to UTF-8 so those diagnostics never crash.
    """

    def test_log_survives_non_ascii_after_reconfigure(self):
        legacy = io.TextIOWrapper(
            io.BytesIO(), encoding="cp1252", errors="strict", newline=""
        )
        cyrillic = "Рабочий стол/пикчи/safety_door.png"
        saved_out, saved_err = sys.stdout, sys.stderr
        try:
            sys.stdout = legacy
            sys.stderr = legacy
            # Baseline: the legacy codepage cannot encode Cyrillic -- the crash.
            with pytest.raises(UnicodeEncodeError):
                legacy.write(cyrillic)
                legacy.flush()
            # Apply the fix and re-run the exact code path compare uses.
            _configure_stdio_utf8()
            _log("deleted: " + cyrillic)
            sys.stdout.flush()
            payload = legacy.buffer.getvalue().decode("utf-8")
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err
        assert cyrillic in payload

    def test_reconfigure_is_safe_on_streams_without_reconfigure(self):
        # Streams that predate TextIOWrapper.reconfigure (or are swapped for a
        # plain object) must be tolerated, not crash the engine at startup.
        class _NoReconfigure:
            pass

        saved_out, saved_err = sys.stdout, sys.stderr
        try:
            sys.stdout = _NoReconfigure()
            sys.stderr = _NoReconfigure()
            _configure_stdio_utf8()  # must not raise
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err
