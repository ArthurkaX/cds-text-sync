import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE = os.path.join(ROOT, "cli", "external_engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from _project_model import ProjectModel, ProjectNode
from snapshooter_map import _is_excluded_from_build


def _make_model(*entries):
    """Build a ProjectModel from (guid, name, parent_guid, metadata) tuples."""
    model = ProjectModel(namespace="")
    for guid, name, parent_guid, metadata in entries:
        node = ProjectNode(guid, name, node_type=None, parent_guid=parent_guid)
        node.metadata.update(metadata)
        model.add_node(node)
    return model


def test_not_excluded_without_metadata():
    model = _make_model(
        ("a", "Normal", None, {}),
    )
    node = model.get_node("a")
    assert _is_excluded_from_build(node, model) is False


def test_excluded_when_own_flag_true():
    model = _make_model(
        ("a", "Excluded", None, {"exclude_from_build": True}),
    )
    node = model.get_node("a")
    assert _is_excluded_from_build(node, model) is True


def test_not_excluded_when_own_flag_false():
    model = _make_model(
        ("a", "Included", None, {"exclude_from_build": False}),
    )
    node = model.get_node("a")
    assert _is_excluded_from_build(node, model) is False


def test_excluded_inherited_from_parent():
    model = _make_model(
        ("parent", "ExcludedParent", None, {"exclude_from_build": True}),
        ("child", "ChildUnderExcluded", "parent", {}),
    )
    child = model.get_node("child")
    assert _is_excluded_from_build(child, model) is True


def test_excluded_inherited_from_grandparent():
    model = _make_model(
        ("root", "ExcludedRoot", None, {"exclude_from_build": True}),
        ("mid", "Mid", "root", {}),
        ("leaf", "Leaf", "mid", {}),
    )
    leaf = model.get_node("leaf")
    assert _is_excluded_from_build(leaf, model) is True


def test_excluded_when_ancestor_excluded_but_parent_not():
    model = _make_model(
        ("root", "ExcludedRoot", None, {"exclude_from_build": True}),
        ("mid", "MidIncluded", "root", {"exclude_from_build": False}),
        ("leaf", "Leaf", "mid", {}),
    )
    leaf = model.get_node("leaf")
    assert _is_excluded_from_build(leaf, model) is True


def test_not_excluded_when_only_sibling_excluded():
    model = _make_model(
        ("root", "Root", None, {"exclude_from_build": False}),
        ("sib", "ExcludedSibling", "root", {"exclude_from_build": True}),
        ("leaf", "Leaf", "root", {}),
    )
    leaf = model.get_node("leaf")
    assert _is_excluded_from_build(leaf, model) is False


def test_missing_parent_does_not_crash():
    node = ProjectNode("orphan", "Orphan", parent_guid="missing")
    model = ProjectModel(namespace="")
    model.add_node(node)
    assert _is_excluded_from_build(node, model) is False


def test_cycle_does_not_infinite_loop():
    model = ProjectModel(namespace="")
    a = ProjectNode("a", "A", parent_guid="b")
    b = ProjectNode("b", "B", parent_guid="a")
    model.add_node(a)
    model.add_node(b)
    assert _is_excluded_from_build(a, model) is False
