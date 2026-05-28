# -*- coding: utf-8 -*-
"""
test_export_only.py - Standalone test for export_only sync direction filtering.

This test verifies that objects with kind marked as "export_only" in
sync_direction_overrides are correctly excluded from modified/added/deleted
diff results and demoted to unchanged.
"""

import os
import sys
import unittest

# Ensure our engine modules are importable
sys.path.insert(0, os.path.dirname(__file__))

from _project_model import ProjectModel, ProjectNode
from _project_profiles import kind_for_type_guid
from diff_engine import DiffEngine, _kind_for_node, _sync_direction

# --- GUIDs from default profile ---
POU_TYPE_GUID = "6f9dac99-8de1-4efc-8465-68ac443b7d08"
SYMBOL_CONFIG_TYPE_GUID = "21d4fe94-4123-4e23-9091-ead220afbd1f"
DEVICE_TYPE_GUID = "225bfe47-7336-4dbc-9419-4105a7c831fa"

# -- Namespace for fake XML entries --
NS = "{http://www.w3.org/1999/xhtml}"


class TestSyncDirection(unittest.TestCase):
    """Tests for the _sync_direction helper function."""

    def test_export_only_direction(self):
        profile = {"sync_direction_overrides": {"symbol_config": "export_only"}}
        self.assertEqual(_sync_direction(profile, "symbol_config"), "export_only")

    def test_empty_direction(self):
        profile = {"sync_direction_overrides": {"symbol_config": "export_only"}}
        self.assertEqual(_sync_direction(profile, "pou"), "")

    def test_no_overrides(self):
        profile = {}
        self.assertEqual(_sync_direction(profile, "symbol_config"), "")

    def test_none_profile(self):
        self.assertEqual(_sync_direction(None, "symbol_config"), "")

    def test_non_dict_overrides(self):
        profile = {"sync_direction_overrides": "not a dict"}
        self.assertEqual(_sync_direction(profile, "symbol_config"), "")


class TestKindForNode(unittest.TestCase):
    """Tests for the _kind_for_node helper function."""

    def test_known_type_guid(self):
        profile = {"guid_aliases": {"symbol_config": [SYMBOL_CONFIG_TYPE_GUID]}}
        node = ProjectNode("g1", "Symbols", SYMBOL_CONFIG_TYPE_GUID, None)
        self.assertEqual(_kind_for_node(profile, node), "symbol_config")

    def test_unknown_type_guid(self):
        profile = {"guid_aliases": {"symbol_config": [SYMBOL_CONFIG_TYPE_GUID]}}
        node = ProjectNode(
            "g2", "Unknown", "00000000-0000-0000-0000-000000000000", None
        )
        self.assertIsNone(_kind_for_node(profile, node))

    def test_none_node(self):
        profile = {"guid_aliases": {"symbol_config": [SYMBOL_CONFIG_TYPE_GUID]}}
        self.assertIsNone(_kind_for_node(profile, None))

    def test_empty_type_guid(self):
        profile = {"guid_aliases": {"symbol_config": [SYMBOL_CONFIG_TYPE_GUID]}}
        node = ProjectNode("g3", "NoType", "", None)
        self.assertIsNone(_kind_for_node(profile, node))


class TestExportOnlyFiltering(unittest.TestCase):
    """Tests that DiffEngine correctly filters export_only objects."""

    def _make_profile(self):
        return {
            "guid_aliases": {
                "pou": [POU_TYPE_GUID],
                "symbol_config": [SYMBOL_CONFIG_TYPE_GUID],
                "device": [DEVICE_TYPE_GUID],
            },
            "sync_direction_overrides": {
                "symbol_config": "export_only",
                "device": "export_only",
            },
        }

    def _make_pou_node(self, guid, name="TestPOU", parent_guid=None, xml_text=None):
        node = ProjectNode(guid, name, POU_TYPE_GUID, parent_guid)
        node.xml_text = (
            xml_text
            or '<Single Name="Object"><Single Name="Implementation">x := 1;</Single></Single>'
        )
        node.entry_element = None
        return node

    def _make_symbol_config_node(
        self, guid, name="Symbols", parent_guid=None, xml_text=None
    ):
        node = ProjectNode(guid, name, SYMBOL_CONFIG_TYPE_GUID, parent_guid)
        node.xml_text = (
            xml_text or '<Single Name="Object"><Single Name="SelectionSigns"/></Single>'
        )
        node.entry_element = None
        return node

    def test_export_only_excluded_from_modified(self):
        """A modified symbol_config should be demoted from modified to unchanged."""
        profile = self._make_profile()
        pou_guid = "11111111-1111-1111-1111-111111111111"
        sym_cfg_guid = "22222222-2222-2222-2222-222222222222"

        ide_model = ProjectModel()
        folder_model = ProjectModel()

        pou_ide = self._make_pou_node(pou_guid, "PLC_PRG")
        pou_ide.xml_text = '<Single Name="Object"><Single Name="Implementation">x := 1;</Single></Single>'
        ide_model.add_node(pou_ide)

        pou_folder = self._make_pou_node(pou_guid, "PLC_PRG")
        pou_folder.xml_text = '<Single Name="Object"><Single Name="Implementation">x := 2;</Single></Single>'
        folder_model.add_node(pou_folder)

        sym_ide = self._make_symbol_config_node(sym_cfg_guid, "Symbols")
        sym_ide.xml_text = (
            '<Single Name="Object"><Single Name="SelectionSigns">old</Single></Single>'
        )
        ide_model.add_node(sym_ide)

        sym_folder = self._make_symbol_config_node(sym_cfg_guid, "Symbols")
        sym_folder.xml_text = (
            '<Single Name="Object"><Single Name="SelectionSigns">new</Single></Single>'
        )
        folder_model.add_node(sym_folder)

        engine = DiffEngine(ide_model, folder_model, profile=profile)
        result = engine.compare()

        self.assertIn(pou_guid, result["modified"], "POU should be in modified")
        self.assertNotIn(
            sym_cfg_guid, result["modified"], "symbol_config should NOT be in modified"
        )
        self.assertIn(
            sym_cfg_guid,
            result["unchanged"],
            "symbol_config should be demoted to unchanged",
        )

    def test_export_only_excluded_from_added(self):
        """A newly added symbol_config should be demoted from added to unchanged."""
        profile = self._make_profile()
        pou_guid = "11111111-1111-1111-1111-111111111111"
        sym_cfg_guid = "22222222-2222-2222-2222-222222222222"

        ide_model = ProjectModel()
        folder_model = ProjectModel()

        pou_ide = self._make_pou_node(pou_guid)
        pou_ide.xml_text = '<Single Name="Object"><Single Name="Implementation">x := 1;</Single></Single>'
        ide_model.add_node(pou_ide)

        pou_folder = self._make_pou_node(pou_guid)
        pou_folder.xml_text = '<Single Name="Object"><Single Name="Implementation">x := 1;</Single></Single>'
        folder_model.add_node(pou_folder)

        # symbol_config only in folder_model (added)
        sym_folder = self._make_symbol_config_node(sym_cfg_guid)
        folder_model.add_node(sym_folder)

        engine = DiffEngine(ide_model, folder_model, profile=profile)
        result = engine.compare()

        self.assertNotIn(
            sym_cfg_guid, result["added"], "symbol_config should NOT be in added"
        )
        self.assertIn(
            sym_cfg_guid,
            result["unchanged"],
            "symbol_config should be demoted to unchanged",
        )

    def test_export_only_excluded_from_deleted(self):
        """A deleted symbol_config should be demoted from deleted to unchanged."""
        profile = self._make_profile()
        sym_cfg_guid = "22222222-2222-2222-2222-222222222222"

        ide_model = ProjectModel()
        folder_model = ProjectModel()

        # symbol_config only in ide_model (deleted)
        sym_ide = self._make_symbol_config_node(sym_cfg_guid)
        ide_model.add_node(sym_ide)

        engine = DiffEngine(ide_model, folder_model, profile=profile)
        result = engine.compare()

        self.assertNotIn(
            sym_cfg_guid, result["deleted"], "symbol_config should NOT be in deleted"
        )
        self.assertIn(
            sym_cfg_guid,
            result["unchanged"],
            "symbol_config should be demoted to unchanged",
        )

    def test_non_export_only_remains_in_modified(self):
        """A modified POU should remain in modified (not export_only)."""
        profile = self._make_profile()
        pou_guid = "11111111-1111-1111-1111-111111111111"

        ide_model = ProjectModel()
        folder_model = ProjectModel()

        pou_ide = self._make_pou_node(pou_guid)
        pou_ide.xml_text = '<Single Name="Object"><Single Name="Implementation">x := 1;</Single></Single>'
        ide_model.add_node(pou_ide)

        pou_folder = self._make_pou_node(pou_guid)
        pou_folder.xml_text = '<Single Name="Object"><Single Name="Implementation">x := 2;</Single></Single>'
        folder_model.add_node(pou_folder)

        engine = DiffEngine(ide_model, folder_model, profile=profile)
        result = engine.compare()

        self.assertIn(pou_guid, result["modified"], "POU should remain in modified")

    def test_no_profile_means_no_filtering(self):
        """Without a profile, export_only filtering is skipped entirely."""
        pou_guid = "11111111-1111-1111-1111-111111111111"
        sym_cfg_guid = "22222222-2222-2222-2222-222222222222"

        ide_model = ProjectModel()
        folder_model = ProjectModel()

        sym_ide = self._make_symbol_config_node(sym_cfg_guid)
        sym_ide.xml_text = (
            '<Single Name="Object"><Single Name="SelectionSigns">old</Single></Single>'
        )
        ide_model.add_node(sym_ide)

        sym_folder = self._make_symbol_config_node(sym_cfg_guid)
        sym_folder.xml_text = (
            '<Single Name="Object"><Single Name="SelectionSigns">new</Single></Single>'
        )
        folder_model.add_node(sym_folder)

        engine = DiffEngine(ide_model, folder_model, profile=None)
        result = engine.compare()

        # Without profile, symbol_config stays in modified
        self.assertIn(
            sym_cfg_guid,
            result["modified"],
            "symbol_config should be in modified when no profile",
        )

    def test_multiple_export_only_kinds(self):
        """Both symbol_config and device should be filtered."""
        profile = self._make_profile()
        sym_cfg_guid = "22222222-2222-2222-2222-222222222222"
        device_guid = "33333333-3333-3333-3333-333333333333"

        ide_model = ProjectModel()
        folder_model = ProjectModel()

        sym_ide = self._make_symbol_config_node(sym_cfg_guid)
        sym_ide.xml_text = '<Single Name="Object">old</Single>'
        ide_model.add_node(sym_ide)

        sym_folder = self._make_symbol_config_node(sym_cfg_guid)
        sym_folder.xml_text = '<Single Name="Object">new</Single>'
        folder_model.add_node(sym_folder)

        dev_ide = ProjectNode(device_guid, "Device", DEVICE_TYPE_GUID, None)
        dev_ide.xml_text = '<Single Name="Object">old device</Single>'
        ide_model.add_node(dev_ide)

        dev_folder = ProjectNode(device_guid, "Device", DEVICE_TYPE_GUID, None)
        dev_folder.xml_text = '<Single Name="Object">new device</Single>'
        folder_model.add_node(dev_folder)

        engine = DiffEngine(ide_model, folder_model, profile=profile)
        result = engine.compare()

        self.assertNotIn(
            sym_cfg_guid, result["modified"], "symbol_config should NOT be in modified"
        )
        self.assertNotIn(
            device_guid, result["modified"], "device should NOT be in modified"
        )
        self.assertIn(
            sym_cfg_guid, result["unchanged"], "symbol_config should be in unchanged"
        )
        self.assertIn(device_guid, result["unchanged"], "device should be in unchanged")


if __name__ == "__main__":
    unittest.main()
