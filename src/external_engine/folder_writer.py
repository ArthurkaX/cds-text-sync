# -*- coding: utf-8 -*-
"""
folder_writer.py - Writes the in-memory ProjectModel to a Git-friendly folder structure.
"""

import os
import codecs
import json
import time

from xml_helpers import (
    csv_projection_content,
    ensure_dir,
    entry_to_xml,
    externalized_text_xml,
    normalize_guid,
    sha1_hex,
    st_projection_content,
)
from _project_layout import is_reserved_root_child
from _project_profiles import enabled_projection_options, kind_for_type_guid


def _timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(message):
    print("[{0}] {1}".format(_timestamp(), message))


def _normalize_fs_path(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(path or "")))


def _absolute_view_path(path):
    return os.path.abspath(os.path.normpath(path or ""))


def _split_path_components(path):
    absolute = _absolute_view_path(path)
    drive, tail = os.path.splitdrive(absolute)
    parts = [part for part in tail.split(os.sep) if part]
    if drive and tail.startswith(os.sep):
        return drive + os.sep, parts
    if drive:
        return drive, parts
    if absolute.startswith(os.sep):
        return os.sep, parts
    return "", parts


def _rename_case_only(source_path, target_path):
    if _normalize_fs_path(source_path) != _normalize_fs_path(target_path):
        return False
    source_path = _absolute_view_path(source_path)
    target_path = _absolute_view_path(target_path)
    if source_path == target_path:
        return False
    parent_dir = os.path.dirname(source_path)
    if not parent_dir:
        return False
    temp_name = ".cds-casefix-{0}-{1}".format(os.getpid(), int(time.time() * 1000000))
    temp_path = os.path.join(parent_dir, temp_name)
    os.rename(source_path, temp_path)
    os.rename(temp_path, target_path)
    return True

class FolderWriter:
    def __init__(self, views_path, dump_path, profile=None, projections=None, selected_guids=None):
        self.views_path = views_path
        self.dump_path = dump_path
        self.manifest_path = os.path.join(dump_path, "manifest.json")
        self.profile = profile or {}
        self.projections = projections or {}
        self.selected_guids = set(normalize_guid(guid) for guid in (selected_guids or []) if normalize_guid(guid))

    def _safe_view_path(self, relative_path):
        if not relative_path:
            return None
        parts = relative_path.replace("\\", os.sep).split(os.sep)
        if parts and is_reserved_root_child(parts[0]):
            _log("Warning: Ignoring reserved root view path: {0}".format(relative_path))
            return None
        full_path = _absolute_view_path(os.path.join(self.views_path, relative_path))
        view_root = _normalize_fs_path(self.views_path)
        if _normalize_fs_path(full_path) == view_root:
            return None
        if _normalize_fs_path(full_path) and not _normalize_fs_path(full_path).startswith(view_root + os.sep):
            _log("Warning: Ignoring managed path outside view root: {0}".format(relative_path))
            return None
        return full_path

    def _load_existing_manifest(self):
        if not os.path.exists(self.manifest_path):
            return None
        try:
            with open(self.manifest_path, "r") as f:
                return json.load(f)
        except Exception as e:
            _log("Warning: Could not read existing manifest: {0}".format(e))
            return None

    def _remove_empty_parent_dirs(self, path):
        view_root = _normalize_fs_path(self.views_path)
        current = _normalize_fs_path(os.path.dirname(path))
        while current.startswith(view_root + os.sep):
            try:
                os.rmdir(current)
            except Exception:
                return
            current = os.path.dirname(current)

    def _canonicalize_existing_path(self, target_path):
        target_path = _absolute_view_path(target_path)
        root, parts = _split_path_components(target_path)
        if not root or not parts:
            return

        current_actual = root
        for index, part in enumerate(parts):
            if not os.path.exists(current_actual):
                return

            try:
                entries = os.listdir(current_actual)
            except Exception:
                return

            match = None
            for entry in entries:
                if entry.lower() == part.lower():
                    match = entry
                    break

            if match is None:
                return

            actual_child = os.path.join(current_actual, match)
            desired_child = os.path.join(current_actual, part)
            if actual_child != desired_child and _normalize_fs_path(actual_child) == _normalize_fs_path(desired_child):
                _rename_case_only(actual_child, desired_child)
                actual_child = desired_child

            current_actual = actual_child

    def _remove_previous_managed_files(self, selected_guids=None):
        manifest = self._load_existing_manifest()
        if not manifest:
            return

        removed = 0
        seen = set()
        for entry in manifest.get("entries", []):
            if selected_guids is not None:
                guid = normalize_guid(entry.get("guid"))
                if guid not in selected_guids:
                    continue
            relative_paths = []
            if entry.get("xml_path") or entry.get("view_path"):
                relative_paths.append(entry.get("xml_path") or entry.get("view_path"))
            relative_paths.extend(entry.get("projection_paths") or [])

            for relative_path in relative_paths:
                full_path = self._safe_view_path(relative_path)
                if not full_path or full_path in seen:
                    continue
                seen.add(full_path)
                if os.path.isfile(full_path):
                    try:
                        os.remove(full_path)
                        removed += 1
                        self._remove_empty_parent_dirs(full_path)
                    except Exception as e:
                        _log("Warning: Could not remove managed view file: {0} {1}".format(full_path, e))

        if removed:
            _log("Removed {0} previously managed view files.".format(removed))

    def _existing_manifest_entries(self):
        manifest = self._load_existing_manifest()
        if not manifest:
            return []
        return manifest.get("entries", []) or []

    def _merge_manifest_entries(self, selected_guids, selected_entries):
        if not selected_guids:
            return selected_entries

        result = []
        selected_entry_by_guid = dict(
            (normalize_guid(entry.get("guid")), entry)
            for entry in selected_entries
        )
        emitted = set()
        for entry in self._existing_manifest_entries():
            guid = normalize_guid(entry.get("guid"))
            if guid in selected_guids:
                replacement = selected_entry_by_guid.get(guid)
                if replacement is not None:
                    result.append(replacement)
                    emitted.add(guid)
                continue
            result.append(entry)

        for guid, entry in selected_entry_by_guid.items():
            if guid not in emitted:
                result.append(entry)
        return result

    def _replace_extension(self, relative_path, extension):
        base, _ = os.path.splitext(relative_path)
        return base + extension

    def _flat_nested_path(self, project_model, node, extension):
        parent = project_model.collapsed_parent_for(node)
        if parent is None:
            return None

        parent_parts = parent.get_output_parts(project_model)
        if not parent_parts:
            return None

        node_path = [
            project_model.safe_component(part)
            for part in (node.display_path or [])
            if part
        ]
        tail_parts = node_path[len(parent_parts):] if node_path[:len(parent_parts)] == parent_parts else []
        name = project_model.safe_component(node.output_name or node.name)
        flat_name = ".".join(parent_parts[-1:] + tail_parts + [name])
        return os.path.join(*(parent_parts[:-1] + [flat_name])) + extension

    def _xml_path_for_node(self, project_model, node):
        return self._flat_nested_path(project_model, node, ".xml") or node.get_view_path(project_model, extension=".xml")

    def _node_projection_options(self, node):
        kind = kind_for_type_guid(self.profile, node.type)
        if not kind:
            return []
        result = []
        for projection in enabled_projection_options(self.profile, self.projections):
            kinds = projection.get("kinds") or [projection.get("kind")]
            if kind not in kinds:
                continue
            if node.name in (projection.get("exclude_names") or []):
                _log("Projection skipped: {0} excluded by {1}".format(node.name, projection.get("id") or projection.get("kind")))
                continue
            if projection.get("requires_textual_implementation") and node.metadata.get("implementation_kind") != "textual":
                _log("Projection skipped: {0} -> {1} requires textual implementation".format(node.name, projection.get("id") or projection.get("kind")))
                continue
            result.append(projection)
        return result

    def _projection_content(self, node, projection):
        if projection.get("format") == "st":
            blob_text = st_projection_content(node.entry_element)
            if blob_text is not None:
                return blob_text
        if projection.get("format") == "csv":
            return csv_projection_content(node.entry_element, projection.get("extractor") or projection.get("id"))
        return node.code

    def _write_projection_files(self, project_model, node, xml_path, projection_options):
        if not xml_path:
            return [], {}, {}, {}

        projection_paths = []
        projection_hashes = {}
        projection_extractors = {}
        projection_import_safe = {}
        for projection in projection_options:
            extension = "." + str(projection.get("format") or "").strip().lower()
            if extension not in (".st", ".csv"):
                continue
            content = self._projection_content(node, projection)
            if content is None:
                _log("Projection skipped: {0} -> {1} produced no content".format(node.name, projection.get("id") or extension))
                continue
            projection_path = self._flat_nested_path(project_model, node, extension) or self._replace_extension(xml_path, extension)
            full_path = self._safe_view_path(projection_path)
            if not full_path:
                _log("Projection skipped: {0} -> {1} invalid path {2}".format(node.name, projection.get("id") or extension, projection_path))
                continue
            ensure_dir(os.path.dirname(full_path))
            self._canonicalize_existing_path(full_path)
            with codecs.open(full_path, "w", "utf-8") as f:
                f.write(content)
            _log("Projection emitted: {0} -> {1}".format(node.name, projection_path))
            projection_paths.append(projection_path)
            projection_hashes[projection_path] = sha1_hex(content)
            if projection.get("extractor"):
                projection_extractors[projection_path] = projection.get("extractor")
            elif projection.get("format") == "csv":
                projection_extractors[projection_path] = projection.get("id")
            projection_import_safe[projection_path] = bool(projection.get("import_safe", False))
        return projection_paths, projection_hashes, projection_extractors, projection_import_safe

    def _has_st_projection(self, projection_options):
        for projection in projection_options:
            if str(projection.get("format") or "").strip().lower() == "st":
                return True
        return False

    def _enabled_projection_extensions(self):
        extensions = set()
        for projection in enabled_projection_options(self.profile, self.projections):
            extension = "." + str(projection.get("format") or "").strip().lower()
            if extension in (".st", ".csv"):
                extensions.add(extension)
        return extensions

    def _remove_orphan_projection_files(self, emitted_paths):
        extensions = self._enabled_projection_extensions()
        if not extensions or not os.path.exists(self.views_path):
            return

        view_root = _normalize_fs_path(self.views_path)
        emitted = set(_normalize_fs_path(path) for path in emitted_paths)
        removed = 0
        for root, dirs, files in os.walk(self.views_path):
            if _normalize_fs_path(root) == view_root:
                dirs[:] = [name for name in dirs if not is_reserved_root_child(name)]
            for filename in files:
                extension = os.path.splitext(filename)[1].lower()
                if extension not in extensions:
                    continue
                full_path = _normalize_fs_path(os.path.join(root, filename))
                if full_path in emitted:
                    continue
                try:
                    os.remove(full_path)
                    removed += 1
                    self._remove_empty_parent_dirs(full_path)
                except Exception as e:
                    print("Warning: Could not remove orphan projection file:", full_path, e)

        if removed:
            print("Removed {0} orphan projection files.".format(removed))
        
    def write(self, project_model):
        selected_guids = self.selected_guids or None
        self._remove_previous_managed_files(selected_guids=selected_guids)
        ensure_dir(self.views_path)

        manifest_entries = []
        emitted_paths = set()
        for guid, node in project_model.nodes.items():
            if selected_guids is not None and guid not in selected_guids:
                continue
            projection_options = self._node_projection_options(node)
            if project_model.is_nested_under_collapsed_object(node) and not projection_options:
                continue

            metadata = {
                "guid": guid,
                "name": node.name,
                "type_guid": node.type,
                "parent_guid": node.parent_guid
            }
            if node.metadata.get("structured_view_guid"):
                metadata["structured_view_guid"] = node.metadata.get("structured_view_guid")
            if node.metadata.get("structured_view_single_attrs"):
                metadata["structured_view_single_attrs"] = node.metadata.get("structured_view_single_attrs")

            xml_path = self._xml_path_for_node(project_model, node)
            projection_paths, projection_hashes, projection_extractors, projection_import_safe = self._write_projection_files(
                project_model,
                node,
                xml_path,
                projection_options,
            )
            for projection_path in projection_paths:
                full_projection_path = self._safe_view_path(projection_path)
                if full_projection_path:
                    emitted_paths.add(full_projection_path)

            xml_text = entry_to_xml(node.entry_element)
            if projection_paths and self._has_st_projection(projection_options):
                xml_text = externalized_text_xml(node.entry_element)
            if xml_text is not None:
                full_path = self._safe_view_path(xml_path)
                if not full_path:
                    continue
                ensure_dir(os.path.dirname(full_path))
                self._canonicalize_existing_path(full_path)
                with codecs.open(full_path, "w", "utf-8") as f:
                    f.write(xml_text)
                emitted_paths.add(full_path)
                if projection_paths and self._has_st_projection(projection_options):
                    _log("XML externalized for projection: {0}".format(xml_path))
                
                metadata["xml_path"] = xml_path
                metadata["hash"] = sha1_hex(xml_text)
                if projection_paths:
                    metadata["projection_paths"] = projection_paths
                    metadata["projection_hashes"] = projection_hashes
                    if projection_extractors:
                        metadata["projection_extractors"] = projection_extractors
                    if projection_import_safe:
                        metadata["projection_import_safe"] = projection_import_safe
            
            manifest_entries.append(metadata)

        if selected_guids is None:
            self._remove_orphan_projection_files(emitted_paths)

        manifest_entries = self._merge_manifest_entries(selected_guids, manifest_entries)

        manifest = {
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ns": project_model.ns,
            "entries": manifest_entries
        }
        
        ensure_dir(self.dump_path)
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
            
        _log("Export to XML folder complete.")
        return True
