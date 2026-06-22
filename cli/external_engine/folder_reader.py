# -*- coding: utf-8 -*-
"""
folder_reader.py - Reads the Git-friendly folder structure into a ProjectModel.
"""

import codecs
import json
import os
import re
import xml.etree.ElementTree as ET

from _project_model import ProjectModel, ProjectNode
from _project_profiles import kind_for_type_guid
from xml_helpers import (
    IMPORT_SAFE_CSV_EXTRACTORS,
    ST_IMPLEMENTATION_MARKER,
    ProjectionValidationError,
    apply_alarm_items_csv,
    apply_textlist_csv,
    entry_to_xml,
    extract_bool_property,
    extract_cds_text_sync_type_guid,
    replace_text_blob_values,
    sha1_hex,
    split_st_projection_values,
    strip_cds_text_sync_pragmas,
    text_blob_elements,
)


def _detect_st_kind(content):
    # Check for explicit kind pragma before stripping comments.
    # Prefer new block-comment format:
    #   (* cds-text-sync: TypeGuid="{...}" *)
    # Falls back to old line-comment format for existing files:
    #   //% cds-text-sync.kind: persistent_gvl
    type_guid = extract_cds_text_sync_type_guid(content)
    if type_guid:
        # Presence of TypeGuid pragma signals an ambiguous type.
        # We won't resolve the kind here; caller handles it via profile.
        return None

    kind_pragma_re = re.compile(
        r"//%\s*cds-text-sync\.kind\s*:\s*(\S+)",
        re.IGNORECASE,
    )
    kind_match = kind_pragma_re.search(content or "")
    if kind_match:
        return kind_match.group(1).lower()

    stripped = strip_cds_text_sync_pragmas(content)
    text = re.sub(r"\(\*[\s\S]*?\*\)", "", stripped or "")
    text = re.sub(r"\{[\s\S]*?\}", "", text)
    text = re.sub(r"//.*", "", text)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        word = line.split()[0].upper()
        if word in ("PROGRAM", "FUNCTION_BLOCK", "FUNCTION"):
            return "pou"
        if word == "VAR_GLOBAL":
            return "gvl"
        if word == "TYPE":
            return "dut"
        if word == "METHOD":
            return "method"
        if word == "ACTION":
            return "action"
        if word == "PROPERTY":
            return "property"
    return None


def _split_st_create_content(content):
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    marker = "\n" + ST_IMPLEMENTATION_MARKER + "\n"
    if marker in normalized:
        declaration, implementation = normalized.split(marker, 1)
        return declaration.strip(), implementation.strip()
    if ST_IMPLEMENTATION_MARKER in normalized:
        declaration, implementation = normalized.split(ST_IMPLEMENTATION_MARKER, 1)
        return declaration.strip(), implementation.strip()
    return normalized.strip(), None


class FolderReader:
    def __init__(self, views_path, dump_path, profile=None):
        self.views_path = views_path
        self.dump_path = dump_path
        self.project_root = os.path.dirname(
            os.path.abspath(os.path.normpath(dump_path or ""))
        )
        self.manifest_path = os.path.join(dump_path, "manifest.json")
        self.profile = profile or {}

    def _normalize_fs_path(self, path):
        return os.path.normcase(os.path.abspath(os.path.normpath(path or "")))

    def _manifest_view_root(self, manifest):
        value = manifest.get("view_root") or manifest.get("views_path")
        if not value:
            return None
        text = str(value)
        if text == ".":
            return self.project_root
        if os.path.isabs(text):
            return os.path.abspath(os.path.normpath(text))
        return os.path.abspath(os.path.normpath(os.path.join(self.project_root, text)))

    def _safe_path_in_root(self, relative_path, root_path):
        if not relative_path:
            return None
        parts = relative_path.replace("\\", os.sep).split(os.sep)
        if parts and parts[0].startswith("."):
            return None
        full_path = os.path.abspath(
            os.path.normpath(os.path.join(root_path, relative_path))
        )
        normalized_root = self._normalize_fs_path(root_path)
        normalized_full = self._normalize_fs_path(full_path)
        if normalized_full == normalized_root:
            return None
        if not normalized_full.startswith(normalized_root + os.sep):
            return None
        return full_path

    def _managed_relative_paths(self, entry):
        relative_paths = []
        if entry.get("xml_path") or entry.get("view_path"):
            relative_paths.append(entry.get("xml_path") or entry.get("view_path"))
        for projection_path in entry.get("projection_paths") or []:
            relative_paths.append(projection_path)
        return relative_paths

    def _ensure_view_root_is_current(self, manifest):
        previous_root = self._manifest_view_root(manifest)
        if previous_root and self._normalize_fs_path(
            previous_root
        ) != self._normalize_fs_path(self.views_path):
            raise RuntimeError(
                "Manifest view root is {0}, but current settings point to {1}. "
                "Changing the export directory after data has been exported is blocked.".format(
                    previous_root,
                    self.views_path,
                )
            )

        if previous_root or self._normalize_fs_path(
            self.views_path
        ) == self._normalize_fs_path(self.project_root):
            return

        for entry in manifest.get("entries", []):
            for relative_path in self._managed_relative_paths(entry):
                full_path = self._safe_path_in_root(relative_path, self.project_root)
                if full_path and os.path.isfile(full_path):
                    raise RuntimeError(
                        "Possible legacy root-view export files found outside the active view root. "
                        "Changing the export directory after data has been exported is blocked."
                    )

    def _extract_bool_property(self, xml_text, property_name):
        if not xml_text:
            return None
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return None
        return extract_bool_property(root, property_name)

    def _projection_full_path(self, relative_path):
        return os.path.join(self.views_path, relative_path)

    def _projection_change_info(self, projection_paths, projection_hashes):
        changed = []
        current_hashes = {}
        current_contents = {}
        expected_hashes = projection_hashes or {}
        for projection_path in projection_paths or []:
            full_projection_path = self._projection_full_path(projection_path)
            if not os.path.exists(full_projection_path):
                continue
            with codecs.open(full_projection_path, "r", "utf-8") as f:
                content = f.read()
            current_hash = sha1_hex(content)
            current_hashes[projection_path] = current_hash
            current_contents[projection_path] = content
            expected_hash = expected_hashes.get(projection_path)
            if expected_hash and expected_hash != current_hash:
                changed.append(projection_path)
        return changed, current_hashes, current_contents

    def _relative_path(self, full_path):
        return os.path.relpath(full_path, self.views_path).replace(os.sep, "/")

    def _discover_pending_st_creates(self, model, managed_paths):
        if not os.path.exists(self.views_path):
            return

        for root, dirs, files in os.walk(self.views_path):
            if os.path.abspath(root) == os.path.abspath(self.views_path):
                dirs[:] = [name for name in dirs if not name.startswith(".")]
            for filename in files:
                if not filename.lower().endswith(".st"):
                    continue
                full_path = os.path.join(root, filename)
                rel_path = self._relative_path(full_path)
                if rel_path in managed_paths:
                    continue
                sidecar_xml_path = os.path.splitext(full_path)[0] + ".xml"
                if os.path.exists(sidecar_xml_path):
                    continue

                with codecs.open(full_path, "r", "utf-8") as f:
                    content = f.read()

                type_guid = extract_cds_text_sync_type_guid(content)
                semantic_kind = None
                if type_guid:
                    semantic_kind = kind_for_type_guid(self.profile, type_guid)
                if not semantic_kind:
                    semantic_kind = _detect_st_kind(content)

                if not semantic_kind:
                    # If TypeGuid was present but couldn't resolve a kind,
                    # treat plain VAR_GLOBAL as gvl as a fallback.
                    stripped = strip_cds_text_sync_pragmas(content)
                    text = re.sub(r"\(\*[\s\S]*?\*\)", "", stripped or "")
                    text = re.sub(r"\{[\s\S]*?\}", "", text)
                    text = re.sub(r"//.*", "", text)
                    for raw_line in text.splitlines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.split()[0].upper() == "VAR_GLOBAL":
                            semantic_kind = "gvl"
                            break

                if not semantic_kind:
                    continue

                base_name = os.path.splitext(filename)[0]
                object_name = base_name
                parent_name = None
                if "." in base_name and semantic_kind in (
                    "method",
                    "action",
                    "property",
                ):
                    parent_name, object_name = base_name.rsplit(".", 1)

                stripped_content = strip_cds_text_sync_pragmas(content)
                declaration, implementation = _split_st_create_content(stripped_content)
                guid = "create:" + sha1_hex(rel_path)
                node = ProjectNode(guid, object_name, type_guid or semantic_kind, None)
                node.code = content
                node.display_path = (
                    os.path.dirname(rel_path).replace("\\", "/").split("/")
                )
                node.display_path = [
                    part for part in node.display_path if part and part != "."
                ]
                node.metadata["view_path"] = rel_path
                node.metadata["pending_create"] = True
                node.metadata["create_kind"] = semantic_kind
                if type_guid:
                    node.metadata["create_type_guid"] = type_guid
                node.metadata["create_path"] = rel_path
                node.metadata["create_name"] = object_name
                node.metadata["create_parent_name"] = parent_name
                node.metadata["create_declaration"] = declaration
                node.metadata["create_implementation"] = implementation
                model.add_node(node)

    def _discover_pending_xml_creates(self, model, managed_paths):
        """Discover standalone native-XML objects dropped into project-view/.

        Symmetric to _discover_pending_st_creates: any *.xml under views_path
        that is not a managed object (its rel-path is absent from
        managed_paths, which holds both the .xml native projection and the .st
        projections of every manifest entry) is treated as a new native object
        to import. The file is already a CODESYS native export, so it is fed
        verbatim to import_native at apply time.

        Skips:
          - dotfiles such as .cds-object.xml (folder descriptors),
          - anything already managed (managed_paths),
          - an .xml that has a sibling .st of the same basename (that is an
            externalized-text projection; the standalone .st is handled by the
            ST discovery, which conversely skips when a sibling .xml exists --
            keeping the two discoveries mutually exclusive).
        """
        if not os.path.exists(self.views_path):
            return

        for root, dirs, files in os.walk(self.views_path):
            if os.path.abspath(root) == os.path.abspath(self.views_path):
                dirs[:] = [name for name in dirs if not name.startswith(".")]
            for filename in files:
                if not filename.lower().endswith(".xml"):
                    continue
                if filename.startswith("."):
                    continue
                # A .cds-object.xml file is always a container/object descriptor
                # sidecar, never a standalone importable native object -- skip it
                # regardless of whether it is a dotfile (.cds-object.xml) or named
                # (ObjectName.cds-object.xml).
                if filename.lower().endswith(".cds-object.xml"):
                    continue
                full_path = os.path.join(root, filename)
                rel_path = self._relative_path(full_path)
                if rel_path in managed_paths:
                    continue
                sidecar_st_path = os.path.splitext(full_path)[0] + ".st"
                if os.path.exists(sidecar_st_path):
                    continue

                with codecs.open(full_path, "r", "utf-8") as f:
                    content = f.read()

                type_guid = None
                try:
                    elem_root = ET.fromstring(content)
                    # Skip snapshot files (root <Project>) which are not native
                    # object exports.  In root-view layout the snapshot lives
                    # inside the view root and would otherwise be mis-discovered.
                    root_tag = elem_root.tag
                    if "}" in root_tag:
                        root_tag = root_tag.rsplit("}", 1)[1]
                    if root_tag == "Project":
                        continue
                    type_guid = (elem_root.attrib.get("Type") or "").strip() or None
                except Exception:
                    type_guid = None
                # A genuine standalone native-XML object export carries a
                # Type attribute (the CODESYS type GUID) on its root element.
                # Exported view files (plain <Single> without Type) and
                # unparseable files are not native object drops -- skip them
                # so the discovery does not pick up existing managed exports.
                if not type_guid:
                    continue

                base_name = os.path.splitext(filename)[0]
                self._validate_native_object_members(
                    model, rel_path, base_name, elem_root, type_guid
                )
                guid = "create:" + sha1_hex(rel_path)
                node = ProjectNode(guid, base_name, type_guid or "native_xml", None)
                node.xml_text = content
                node.display_path = (
                    os.path.dirname(rel_path).replace("\\", "/").split("/")
                )
                node.display_path = [
                    part for part in node.display_path if part and part != "."
                ]
                node.metadata["view_path"] = rel_path
                node.metadata["pending_create"] = True
                node.metadata["create_kind"] = "native_xml"
                node.metadata["create_path"] = rel_path
                node.metadata["create_name"] = base_name
                node.metadata["create_native_xml"] = content
                if type_guid:
                    node.metadata["create_type_guid"] = type_guid
                model.add_node(node)

    def _xml_top_level_member_names(self, elem_root):
        names = []
        for child in list(elem_root):
            name = child.attrib.get("Name")
            if name:
                names.append(name)
        return names

    def _native_member_whitelist(self, model, type_guid):
        """Allowed top-level member names for an object whose root wrapper Type is
        `type_guid`, derived from the genuine managed objects already in the
        project (no hardcoded schema). All CODESYS objects share the same
        wrapper type, so this is the canonical member set the IDE emits. Returns
        (allowed_names_set, reference_rel_path_or_None)."""
        cache = getattr(self, "_native_whitelist_cache", None)
        if cache is None:
            cache = {}
            self._native_whitelist_cache = cache
        key = (type_guid or "").strip().strip("{}").lower()
        if key in cache:
            return cache[key]

        allowed = set()
        reference = None
        for node in model.nodes.values():
            xml_text = getattr(node, "xml_text", None)
            if not xml_text:
                continue
            try:
                root = ET.fromstring(xml_text)
            except Exception:
                continue
            node_type = (root.attrib.get("Type") or "").strip().strip("{}").lower()
            if node_type != key:
                continue
            for name in self._xml_top_level_member_names(root):
                allowed.add(name)
            if reference is None:
                reference = node.metadata.get("view_path")
        result = (allowed, reference)
        cache[key] = result
        return result

    def _validate_native_object_members(
        self, model, rel_path, base_name, elem_root, type_guid
    ):
        """Print a precise, copyable diagnostic when a standalone native object
        carries top-level members the IDE never emits for this object type. This
        is the #1 cause of CODESYS rejecting an externally-prepared object with
        the opaque 'One of the identified items was in an invalid format'. The
        check is advisory (non-blocking): it tells whoever prepared the file what
        to fix, it does not alter the file."""
        allowed, reference = self._native_member_whitelist(model, type_guid)
        if not allowed:
            # No comparable managed object to learn the schema from -- can't
            # validate, stay silent rather than emit false positives.
            return

        members = self._xml_top_level_member_names(elem_root)
        foreign = [name for name in members if name not in allowed]
        if not foreign:
            return

        lines = []
        lines.append(
            "NATIVE IMPORT VALIDATION: '{0}' ({1}) has top-level member(s) that "
            "CODESYS does not emit for this object type and will reject on import "
            "with 'One of the identified items was in an invalid format':".format(
                base_name, rel_path
            )
        )
        for name in foreign:
            lines.append("  - unexpected top-level member: Name=\"{0}\"".format(name))
        lines.append("  expected members: {0}".format(", ".join(sorted(allowed))))
        if reference:
            lines.append(
                "  reference (a valid IDE export of the same type): {0}".format(
                    reference
                )
            )
        lines.append(
            "  the real object content is under <Single Name=\"Object\">; remove the "
            "foreign members above so the wrapper matches a genuine IDE export."
        )
        lines.append(
            "  NOTE: this file was prepared outside CODESYS -- fix it in the tool "
            "that generated it; cds-text-sync imports it verbatim."
        )
        print("\n".join(lines))

    def _rehydrate_externalized_text(self, xml_text, projection_paths):
        if not xml_text:
            return xml_text

        st_projection_path = None
        for projection_path in projection_paths or []:
            if str(projection_path).lower().endswith(".st"):
                st_projection_path = projection_path
                break
        if not st_projection_path:
            return xml_text

        full_projection_path = self._projection_full_path(st_projection_path)
        if not os.path.exists(full_projection_path):
            return xml_text

        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return xml_text

        blobs = text_blob_elements(root)
        if not blobs:
            return xml_text

        with codecs.open(full_projection_path, "r", "utf-8") as f:
            projection_text = f.read()
        projection_text = strip_cds_text_sync_pragmas(projection_text)
        replace_text_blob_values(
            root, split_st_projection_values(projection_text, root)
        )
        return entry_to_xml(root)

    def _rehydrate_import_safe_csv(
        self, xml_text, projection_paths, projection_extractors, projection_import_safe
    ):
        if not xml_text:
            return xml_text

        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return xml_text

        changed = False
        for projection_path in projection_paths or []:
            if not str(projection_path).lower().endswith(".csv"):
                continue
            extractor = (projection_extractors or {}).get(projection_path)
            if extractor not in IMPORT_SAFE_CSV_EXTRACTORS:
                continue
            full_projection_path = self._projection_full_path(projection_path)
            if not os.path.exists(full_projection_path):
                continue
            with codecs.open(full_projection_path, "r", "utf-8") as f:
                csv_content = f.read()
            try:
                if extractor == "textlist_csv" and apply_textlist_csv(
                    root, csv_content
                ):
                    changed = True
                if extractor == "alarm_items_csv" and apply_alarm_items_csv(
                    root, csv_content
                ):
                    changed = True
            except ProjectionValidationError as error:
                raise ProjectionValidationError(
                    "{0}: {1}".format(projection_path, error)
                )

        if changed:
            return entry_to_xml(root)
        return xml_text

    def read(self):
        if not os.path.exists(self.manifest_path):
            print("Manifest not found at:", self.manifest_path)
            return None

        with open(self.manifest_path, "r") as f:
            manifest = json.load(f)
        self._ensure_view_root_is_current(manifest)

        ns = manifest.get("ns", "")
        model = ProjectModel(namespace=ns)
        managed_paths = set()

        for entry in manifest.get("entries", []):
            guid = entry.get("guid")
            name = entry.get("name")
            node_type = entry.get("type_guid")
            parent_guid = entry.get("parent_guid")

            node = ProjectNode(guid, name, node_type, parent_guid)

            xml_path = entry.get("xml_path")
            if xml_path:
                managed_paths.add(xml_path.replace("\\", "/"))
                for projection_path in entry.get("projection_paths") or []:
                    managed_paths.add(str(projection_path).replace("\\", "/"))
                node.metadata["view_path"] = xml_path
                full_path = os.path.join(self.views_path, xml_path)
                if os.path.exists(full_path):
                    with codecs.open(full_path, "r", "utf-8") as f:
                        node.xml_text = f.read()
                    raw_xml_hash = sha1_hex(node.xml_text)
                    node.metadata["xml_changed"] = bool(
                        entry.get("hash") and entry.get("hash") != raw_xml_hash
                    )
                    (
                        projection_changed_paths,
                        current_projection_hashes,
                        current_projection_contents,
                    ) = self._projection_change_info(
                        entry.get("projection_paths") or [],
                        entry.get("projection_hashes") or {},
                    )
                    if projection_changed_paths:
                        node.metadata["projection_changed_paths"] = (
                            projection_changed_paths
                        )
                    if current_projection_hashes:
                        node.metadata["projection_hashes"] = current_projection_hashes
                    if current_projection_contents:
                        node.metadata["projection_contents"] = (
                            current_projection_contents
                        )
                    if entry.get("projection_extractors"):
                        node.metadata["projection_extractors"] = entry.get(
                            "projection_extractors"
                        )
                    if entry.get("projection_import_safe"):
                        node.metadata["projection_import_safe"] = entry.get(
                            "projection_import_safe"
                        )
                    if node.metadata.get("xml_changed") and projection_changed_paths:
                        node.metadata["projection_conflict"] = True
                    node.xml_text = self._rehydrate_externalized_text(
                        node.xml_text,
                        entry.get("projection_paths") or [],
                    )
                    node.xml_text = self._rehydrate_import_safe_csv(
                        node.xml_text,
                        entry.get("projection_paths") or [],
                        entry.get("projection_extractors") or {},
                        entry.get("projection_import_safe") or {},
                    )
                    exclude_from_build = self._extract_bool_property(
                        node.xml_text, "ExcludeFromBuild"
                    )
                    if exclude_from_build is not None:
                        node.metadata["exclude_from_build"] = exclude_from_build
            else:
                view_path = entry.get("view_path")
                if view_path:
                    managed_paths.add(view_path.replace("\\", "/"))
                    node.metadata["view_path"] = view_path
                    full_path = os.path.join(self.views_path, view_path)
                    if os.path.exists(full_path):
                        with codecs.open(full_path, "r", "utf-8") as f:
                            node.code = f.read()

            # Store original hash for diffing
            node.metadata["original_hash"] = entry.get("hash")
            if entry.get("structured_view_guid"):
                node.metadata["structured_view_guid"] = entry.get(
                    "structured_view_guid"
                )
            if entry.get("structured_view_single_attrs"):
                node.metadata["structured_view_single_attrs"] = entry.get(
                    "structured_view_single_attrs"
                )

            model.add_node(node)

        self._discover_pending_st_creates(model, managed_paths)
        self._discover_pending_xml_creates(model, managed_paths)

        return model
