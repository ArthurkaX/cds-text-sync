# -*- coding: utf-8 -*-
"""
diff_engine.py - Compares an IDE snapshot model with a Folder model.
"""

import xml.etree.ElementTree as ET

from _project_profiles import kind_for_type_guid
from xml_helpers import (
    IMPORT_SAFE_CSV_EXTRACTORS,
    csv_projection_content,
    normalized_xml_text,
    st_projection_content,
)


def _sync_direction(profile, kind):
    """Return the sync direction override for a given kind, or empty string if none."""
    overrides = (
        profile.get("sync_direction_overrides") if isinstance(profile, dict) else None
    )
    if isinstance(overrides, dict) and kind in overrides:
        return overrides[kind]
    return ""


def _kind_for_node(profile, node):
    """Resolve the profile kind for a node based on its type GUID."""
    type_guid = (node.type or "").strip().lower() if node else ""
    if type_guid and isinstance(profile, dict):
        return kind_for_type_guid(profile, type_guid)
    return None


def _entry_element(node):
    if node is None:
        return None
    entry = getattr(node, "entry_element", None)
    if entry is not None:
        return entry
    xml_text = getattr(node, "xml_text", None)
    if not xml_text:
        return None
    try:
        return ET.fromstring(xml_text)
    except Exception:
        return None


def _same_projection_text(left, right):
    return (left or "").replace("\r\n", "\n").replace("\r", "\n").rstrip() == (
        right or ""
    ).replace("\r\n", "\n").replace("\r", "\n").rstrip()


class DiffEngine:
    def __init__(self, ide_model, folder_model, profile=None):
        self.ide_model = ide_model
        self.folder_model = folder_model
        self.profile = profile or {}

    def _is_import_blocked(self, guid):
        """True when disk-side changes must never be patched into the IDE.

        Covers profile ``export_only`` kinds and text-first ``import_inert``
        entries (tool-owned mirror xml with no user-editable artifact).
        """
        folder_node = self.folder_model.get_node(guid)
        if folder_node is not None and folder_node.metadata.get("import_inert"):
            return True
        node = folder_node or self.ide_model.get_node(guid)
        if node is None:
            return False
        kind = _kind_for_node(self.profile, node)
        if kind is None:
            return False
        return _sync_direction(self.profile, kind) == "export_only"

    def _is_export_only(self, guid):
        """Check if an object's kind is marked export_only in the profile."""
        node = self.folder_model.get_node(guid) or self.ide_model.get_node(guid)
        if node is None:
            return False
        kind = _kind_for_node(self.profile, node)
        if kind is None:
            return False
        return _sync_direction(self.profile, kind) == "export_only"

    def _ide_projection_content(self, path, ide_node, extractor_name=None):
        entry = _entry_element(ide_node)
        if str(path).lower().endswith(".st"):
            return st_projection_content(entry) or (ide_node.code if ide_node else "") or ""
        if str(path).lower().endswith(".csv"):
            return csv_projection_content(entry, extractor_name) or ""
        return (ide_node.code if ide_node else "") or ""

    def _projection_differs(self, ide_node, folder_node, changed_paths):
        projection_contents = folder_node.metadata.get("projection_contents") or {}
        projection_extractors = folder_node.metadata.get("projection_extractors") or {}
        for path in changed_paths:
            if path not in projection_contents:
                return True
            disk_content = projection_contents.get(path) or ""
            ide_content = self._ide_projection_content(
                path, ide_node, projection_extractors.get(path)
            )
            if not _same_projection_text(disk_content, ide_content):
                return True
        return False

    def _all_projection_content_matches(self, ide_node, folder_node):
        projection_contents = folder_node.metadata.get("projection_contents") or {}
        projection_paths = [
            path
            for path in projection_contents.keys()
            if str(path).lower().endswith((".st", ".csv"))
        ]
        if not projection_paths:
            return False
        return not self._projection_differs(ide_node, folder_node, projection_paths)

    def compare(self):
        diff_result = {"modified": [], "added": [], "deleted": [], "unchanged": []}
        projection_conflicts = []
        unsupported_projection_changes = {}

        # We only look at modifications based on the folder_model
        # IDE -> Folder means we sync from IDE to Folder
        # Folder -> IDE means we sync from Folder to IDE
        # We will assume folder_model represents current user edits,
        # and ide_model represents baseline from CODESYS.

        folder_guids = set(self.folder_model.nodes.keys())
        ide_guids = set(
            guid
            for guid, node in self.ide_model.nodes.items()
            if not self.ide_model.is_nested_under_collapsed_object(node)
            or guid in folder_guids
        )

        def node_content(node):
            xml_text = getattr(node, "xml_text", None)
            if xml_text:
                cached = node.metadata.get("_normalized_xml")
                if cached is None:
                    cached = normalized_xml_text(xml_text)
                    node.metadata["_normalized_xml"] = cached
                return cached
            return node.code

        for guid in ide_guids.intersection(folder_guids):
            ide_node = self.ide_model.get_node(guid)
            folder_node = self.folder_model.get_node(guid)

            ide_content = node_content(ide_node)
            folder_content = node_content(folder_node)
            projection_changed_paths = (
                folder_node.metadata.get("projection_changed_paths") or []
            )
            projection_import_safe = (
                folder_node.metadata.get("projection_import_safe") or {}
            )
            projection_extractors = (
                folder_node.metadata.get("projection_extractors") or {}
            )
            st_only = bool(folder_node.metadata.get("st_only"))
            if st_only:
                # No xml baseline on disk: the entry is its .st text. Compare
                # every loaded projection against the IDE so drift on either
                # side surfaces as modified and an in-sync .st stays unchanged.
                all_paths = list(
                    (folder_node.metadata.get("projection_contents") or {}).keys()
                )
                projection_content_differs = self._projection_differs(
                    ide_node, folder_node, all_paths
                )
                xml_differs = False
            else:
                projection_content_differs = self._projection_differs(
                    ide_node, folder_node, projection_changed_paths
                ) if projection_changed_paths else False
                projection_content_matches = self._all_projection_content_matches(
                    ide_node, folder_node
                )
                xml_differs = ide_content != folder_content
                if (
                    projection_content_matches
                    and not folder_node.metadata.get("xml_changed")
                ):
                    xml_differs = False
            unsupported_paths = [
                path
                for path in projection_changed_paths
                if (
                    not str(path).lower().endswith(".st")
                    and not projection_import_safe.get(path)
                    and projection_extractors.get(path)
                    not in IMPORT_SAFE_CSV_EXTRACTORS
                )
            ]

            if (
                xml_differs
                or projection_content_differs
                or folder_node.metadata.get("projection_conflict")
            ):
                diff_result["modified"].append(guid)
            else:
                diff_result["unchanged"].append(guid)

            if folder_node.metadata.get("projection_conflict"):
                projection_conflicts.append(guid)
            if unsupported_paths:
                unsupported_projection_changes[guid] = unsupported_paths

        for guid in folder_guids - ide_guids:
            diff_result["added"].append(guid)

        for guid in ide_guids - folder_guids:
            diff_result["deleted"].append(guid)

        # Filter out import-blocked objects from import-direction changes.
        # export_only kinds and import_inert entries must not be patched back
        # into the IDE, so we demote them from modified/added to unchanged.
        if self.profile or any(
            node.metadata.get("import_inert")
            for node in self.folder_model.nodes.values()
        ):
            modified_only = []
            for guid in diff_result["modified"]:
                if self._is_import_blocked(guid):
                    diff_result["unchanged"].append(guid)
                else:
                    modified_only.append(guid)
            diff_result["modified"] = modified_only

            added_only = []
            for guid in diff_result["added"]:
                if self._is_import_blocked(guid):
                    diff_result["unchanged"].append(guid)
                else:
                    added_only.append(guid)
            diff_result["added"] = added_only

            # Import-blocked objects should never be deleted through sync
            deleted_only = []
            for guid in diff_result["deleted"]:
                if self._is_import_blocked(guid):
                    diff_result["unchanged"].append(guid)
                else:
                    deleted_only.append(guid)
            diff_result["deleted"] = deleted_only

        if projection_conflicts:
            diff_result["projection_conflicts"] = projection_conflicts
        if unsupported_projection_changes:
            diff_result["unsupported_projection_changes"] = (
                unsupported_projection_changes
            )

        return diff_result
