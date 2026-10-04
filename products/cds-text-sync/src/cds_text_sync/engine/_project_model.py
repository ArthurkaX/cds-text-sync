# -*- coding: utf-8 -*-
"""
_project_model.py - In-memory model of the CODESYS project.
"""

import os
import re

COLLAPSED_OBJECT_TYPE_GUIDS = set([
    # POU/function block/program objects. Their methods/actions/properties are
    # IDE sub-objects, but for the XML view we keep the object as one file.
    "6f9dac99-8de1-4efc-8465-68ac443b7d08",
])

class ProjectNode:
    def __init__(self, guid, name, node_type=None, parent_guid=None):
        self.guid = guid
        self.name = name
        self.type = node_type
        self.parent_guid = parent_guid
        self.children = []
        self.code = None
        self.xml_text = None
        self.display_path = []
        self.output_name = None
        self.metadata = {}
        self.entry_element = None

    def get_output_parts(self, model):
        parts = [model.safe_component(part) for part in self.display_path if part]
        name = model.safe_component(self.output_name or self.name)
        if model.has_output_name_collision(self):
            name = "{0}__{1}".format(name, self.guid[:8])
        parts.append(name)
        return parts

    def get_view_path(self, model, extension=".xml"):
        """Constructs the view path string based on the native IDE path."""
        parts = self.get_output_parts(model)
        if model.has_output_children(self):
            return os.path.join(*(parts + [".cds-object.xml"]))
        return os.path.join(*parts) + extension if parts else ""

class ProjectModel:
    def __init__(self, namespace=""):
        self.nodes = {}
        self.root_nodes = []
        self.ns = namespace
        self._children_by_parent = {}
        self._name_collision_index = {}
        self._display_path_index = {}
        self._collapsed_path_index = None

    def add_node(self, node):
        self.nodes[node.guid] = node
        self._collapsed_path_index = None
        if node.parent_guid:
            self._children_by_parent.setdefault(node.parent_guid, []).append(node)
        node_path = tuple(node.display_path or [])
        node_name = node.output_name or node.name
        self._name_collision_index.setdefault((node_path, node_name), []).append(node.guid)
        safe_display_path = tuple(self.safe_component(part) for part in (node.display_path or []) if part)
        self._display_path_index.setdefault(safe_display_path, []).append(node.guid)
        if node.parent_guid:
            parent = self.get_node(node.parent_guid)
            if parent:
                parent.children.append(node)
        else:
            self.root_nodes.append(node)

    def get_node(self, guid):
        return self.nodes.get(guid)

    def _parent_of(self, node):
        parent = self.get_node(node.parent_guid) if node.parent_guid else None
        return parent if parent is not node else None

    def _depth(self, node):
        """How far ``node`` sits below the nearest root (cycle-safe)."""
        depth = 0
        seen = set()
        current = node
        while current is not None and current.guid not in seen:
            seen.add(current.guid)
            parent = self._parent_of(current)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth

    def normalize_display_paths(self):
        """Align every node's display_path with its parent's exported name.

        CODESYS stamps each object with an absolute ``Path`` array built from
        the project tree's folder labels. Those labels can disagree in case
        with the parent object's own ``Name``: a device whose folder is
        "Plc Logic" gets children whose Path reads "PLC Logic". The folder
        writer turns display_path straight into directories, so on a
        case-sensitive filesystem one object ends up split across two sibling
        directories ("PLC Logic" and "Plc Logic") and the IDE then reports a
        failed casing normalization.

        Where the recorded path matches the parent chain apart from case --
        the ordinary case -- the parent's own strings are adopted, so one
        object maps to exactly one directory on every filesystem. A recorded
        path that does not match the parent chain is left untouched: those are
        objects CODESYS deliberately places on another branch (embedded
        resources), pathless standard containers, and dangling parents.

        Runs parent-first so a node adopts the already-corrected spelling of
        its ancestors.
        """
        for node in sorted(self.nodes.values(), key=self._depth):
            parent = self._parent_of(node)
            if parent is None:
                continue
            recorded = [part for part in (node.display_path or []) if part]
            if not recorded:
                continue
            derived = parent.get_output_parts(self)
            if len(recorded) != len(derived):
                continue
            if [part.lower() for part in recorded] != [
                part.lower() for part in derived
            ]:
                continue
            if list(recorded) != list(derived):
                node.display_path = list(derived)
        self._rebuild_path_indexes()

    def _rebuild_path_indexes(self):
        self._name_collision_index = {}
        self._display_path_index = {}
        self._collapsed_path_index = None
        for guid, node in self.nodes.items():
            node_path = tuple(node.display_path or [])
            node_name = node.output_name or node.name
            self._name_collision_index.setdefault((node_path, node_name), []).append(guid)
            safe_display_path = tuple(
                self.safe_component(part)
                for part in (node.display_path or [])
                if part
            )
            self._display_path_index.setdefault(safe_display_path, []).append(guid)

    def has_children(self, guid):
        return bool(self._children_by_parent.get(guid))

    def has_output_children(self, node):
        if self.is_collapsed_object(node):
            return False
        node_parts = tuple(node.get_output_parts(self))
        for guid in self._display_path_index.get(node_parts, []):
            if guid != node.guid:
                return True
        return self.has_children(node.guid)

    def safe_component(self, value):
        return re.sub(r'[<>:"/\\|?*]', '_', value or "object").strip(" .") or "object"

    def has_output_name_collision(self, node):
        node_path = tuple(node.display_path or [])
        node_name = node.output_name or node.name
        for guid in self._name_collision_index.get((node_path, node_name), []):
            if guid != node.guid:
                return True
        return False

    def is_collapsed_object(self, node):
        return (node.type or "").lower() in COLLAPSED_OBJECT_TYPE_GUIDS

    def is_nested_under_collapsed_object(self, node):
        return self.collapsed_parent_for(node) is not None

    def _collapsed_paths(self):
        if self._collapsed_path_index is not None:
            return self._collapsed_path_index
        result = []
        for other in self.nodes.values():
            if self.is_collapsed_object(other):
                collapsed_path = tuple(other.get_output_parts(self))
                if collapsed_path:
                    result.append((collapsed_path, other))
        result.sort(key=lambda item: len(item[0]), reverse=True)
        self._collapsed_path_index = result
        return result

    def collapsed_parent_for(self, node):
        node_path = tuple(self.safe_component(part) for part in (node.display_path or []) if part)
        if not node_path:
            return None
        for collapsed_path, other in self._collapsed_paths():
            if other.guid == node.guid:
                continue
            if collapsed_path and node_path[:len(collapsed_path)] == collapsed_path:
                return other
        return None
