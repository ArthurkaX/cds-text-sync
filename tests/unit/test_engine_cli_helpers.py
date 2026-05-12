# -*- coding: utf-8 -*-
"""
test_engine_cli_helpers.py – Unit tests for engine_cli.py helper functions
(Priority 6).

These are helper-level unit tests, not full subprocess tests.
"""

import argparse

from engine_cli import _filter_diff_result, _filter_guids

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
