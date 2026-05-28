# -*- coding: utf-8 -*-
"""
diff_engine.py - Compares an IDE snapshot model with a Folder model.
"""

from _project_profiles import kind_for_type_guid
from xml_helpers import IMPORT_SAFE_CSV_EXTRACTORS, normalized_xml_text


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


class DiffEngine:
    def __init__(self, ide_model, folder_model, profile=None):
        self.ide_model = ide_model
        self.folder_model = folder_model
        self.profile = profile or {}

    def _is_export_only(self, guid):
        """Check if an object's kind is marked export_only in the profile."""
        node = self.folder_model.get_node(guid) or self.ide_model.get_node(guid)
        if node is None:
            return False
        kind = _kind_for_node(self.profile, node)
        if kind is None:
            return False
        return _sync_direction(self.profile, kind) == "export_only"

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

            if ide_content != folder_content or projection_changed_paths:
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

        # Filter out export_only objects from import-direction changes.
        # export_only objects must not be patched back into the IDE,
        # so we demote them from modified/added to unchanged.
        if self.profile:
            modified_only = []
            for guid in diff_result["modified"]:
                if self._is_export_only(guid):
                    diff_result["unchanged"].append(guid)
                else:
                    modified_only.append(guid)
            diff_result["modified"] = modified_only

            added_only = []
            for guid in diff_result["added"]:
                if self._is_export_only(guid):
                    diff_result["unchanged"].append(guid)
                else:
                    added_only.append(guid)
            diff_result["added"] = added_only

            # export_only objects should never be deleted through sync
            deleted_only = []
            for guid in diff_result["deleted"]:
                if self._is_export_only(guid):
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
