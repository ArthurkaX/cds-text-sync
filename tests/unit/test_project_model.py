# -*- coding: utf-8 -*-
"""
test_project_model.py – Unit tests for _project_model.py (Priority 2).

Uses synthetic ProjectNode objects.  Does not parse real IDE XML.
"""

import os

from cds_text_sync.engine._project_model import COLLAPSED_OBJECT_TYPE_GUIDS, ProjectModel, ProjectNode

# ===================================================================
# ProjectModel.safe_component
# ===================================================================


class TestSafeComponent:
    def test_replaces_windows_invalid_filename_characters(self):
        model = ProjectModel()
        assert model.safe_component('a<>:"/\\|?*b') == "a_________b"

    def test_trims_trailing_spaces_and_dots(self):
        model = ProjectModel()
        assert model.safe_component("name . ") == "name"

    def test_falls_back_to_object_for_empty_string(self):
        model = ProjectModel()
        assert model.safe_component("") == "object"

    def test_falls_back_to_object_for_none(self):
        model = ProjectModel()
        assert model.safe_component(None) == "object"

    def test_normal_name_unchanged(self):
        model = ProjectModel()
        assert model.safe_component("MyObject") == "MyObject"


# ===================================================================
# ProjectNode.get_view_path
# ===================================================================


class TestGetViewPath:
    def _make_model_with_node(self, name="Obj", guid="aaa", **kwargs):
        model = ProjectModel()
        node = ProjectNode(guid, name, **kwargs)
        model.add_node(node)
        return model, node

    def test_normal_object_path(self):
        model, node = self._make_model_with_node()
        node.display_path = ["Folder"]
        assert node.get_view_path(model) == os.path.join("Folder", "Obj.xml")

    def test_object_with_output_children_uses_cds_object_xml(self):
        """When a node has output children, the view path ends in
        ``.cds-object.xml``."""
        model = ProjectModel()
        parent = ProjectNode("parent-guid", "Parent")
        parent.display_path = ["Folder"]
        child = ProjectNode("child-guid", "Child", parent_guid="parent-guid")
        child.display_path = ["Folder", "Parent"]
        model.add_node(parent)
        model.add_node(child)
        path = parent.get_view_path(model)
        assert path.endswith(".cds-object.xml")

    def test_output_name_collision_appends_guid_prefix(self):
        model = ProjectModel()
        node_a = ProjectNode("aaa11111-1111-1111-1111-111111111111", "SameName")
        node_a.display_path = ["Folder"]
        node_a.output_name = "SameName"
        node_b = ProjectNode("bbb22222-2222-2222-2222-222222222222", "SameName")
        node_b.display_path = ["Folder"]
        node_b.output_name = "SameName"
        model.add_node(node_a)
        model.add_node(node_b)
        path_a = node_a.get_view_path(model)
        assert "aaa11111" in path_a


# ===================================================================
# ProjectModel.normalize_display_paths
# ===================================================================


class TestNormalizeDisplayPaths:
    """Child paths follow the parent's own exported name.

    CODESYS records each object's Path array from the project tree's folder
    labels, which can disagree in case with the parent object's Name. Turning
    that array straight into directories split one object across two sibling
    folders on a case-sensitive filesystem.
    """

    def _tree(self):
        model = ProjectModel()
        device = ProjectNode("dev", "PLC_Stabur")
        device.display_path = []
        logic = ProjectNode("logic", "Plc Logic", parent_guid="dev")
        logic.display_path = ["PLC_Stabur"]
        app = ProjectNode("app", "Application", parent_guid="logic")
        app.display_path = ["PLC_Stabur", "PLC Logic"]
        for node in (device, logic, app):
            model.add_node(node)
        return model

    def test_child_adopts_the_parent_spelling(self):
        model = self._tree()
        model.normalize_display_paths()
        assert model.get_node("app").display_path == ["PLC_Stabur", "Plc Logic"]

    def test_an_already_correct_path_is_untouched(self):
        model = self._tree()
        model.get_node("logic").display_path = ["PLC_Stabur"]
        assert model.get_node("logic").display_path == ["PLC_Stabur"]
        model.normalize_display_paths()
        assert model.get_node("logic").display_path == ["PLC_Stabur"]

    def test_a_path_on_another_branch_is_left_alone(self):
        model = self._tree()
        # An object CODESYS deliberately places outside the device branch
        # (an embedded resource) must keep its recorded path.
        model.get_node("app").display_path = ["Resources", "Embedded"]
        model.normalize_display_paths()
        assert model.get_node("app").display_path == ["Resources", "Embedded"]

    def test_sibling_collision_index_is_rebuilt_for_the_new_paths(self):
        model = self._tree()
        twin = ProjectNode("app2", "Application", parent_guid="logic")
        twin.display_path = ["PLC_Stabur", "PLC Logic"]
        model.add_node(twin)
        model.normalize_display_paths()
        assert model.has_output_name_collision(model.get_node("app"))
        assert "__" in model.get_node("app").get_view_path(model)


# ===================================================================
# Collapsed object behavior
# ===================================================================


class TestCollapsedObjectBehavior:
    def _make_collapsed_parent(self, guid=None, name="CollapsedPOU"):
        guid = guid or list(COLLAPSED_OBJECT_TYPE_GUIDS)[0]
        node = ProjectNode(guid, name, node_type=guid)
        node.display_path = ["Folder"]
        return node

    def test_child_under_collapsed_pou_is_nested(self):
        model = ProjectModel()
        parent = self._make_collapsed_parent()
        child = ProjectNode("child-guid", "ChildMethod", parent_guid=parent.guid)
        child.display_path = ["Folder", "CollapsedPOU"]
        model.add_node(parent)
        model.add_node(child)
        assert model.is_nested_under_collapsed_object(child)

    def test_collapsed_parent_is_not_nested_under_itself(self):
        model = ProjectModel()
        parent = self._make_collapsed_parent()
        model.add_node(parent)
        assert not model.is_nested_under_collapsed_object(parent)

    def test_unrelated_node_not_nested(self):
        model = ProjectModel()
        parent = self._make_collapsed_parent()
        model.add_node(parent)
        other = ProjectNode("other-guid", "Standalone")
        other.display_path = ["Other"]
        model.add_node(other)
        assert not model.is_nested_under_collapsed_object(other)
