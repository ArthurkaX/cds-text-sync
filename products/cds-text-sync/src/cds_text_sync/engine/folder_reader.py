# -*- coding: utf-8 -*-
"""
folder_reader.py - Reads the Git-friendly folder structure into a ProjectModel.
"""

import codecs
import json
import os
import re
import xml.etree.ElementTree as ET

from _project_model import ProjectNode
from _project_profiles import kind_for_type_guid
from _manifest_bookkeeper import entries as manifest_entries
from _path_safety import replace_extension, safe_path_in_root
from _projection_codec import decode_csv, decode_st
from _projection_changes import detect as detect_projection_changes
from _view_paths import (
    managed_relative_paths,
    manifest_view_root,
    normalize_fs_path,
)
from xml_helpers import (
    IMPORT_SAFE_CSV_EXTRACTORS,
    ST_IMPLEMENTATION_MARKER,
    ProjectionValidationError,
    entry_to_xml,
    extract_bool_property,
    extract_cds_text_sync_type_guid,
    replace_text_blob_values,
    sha1_hex,
    split_action_projection,
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
    # An ACTION carries no declaration: everything after the synthesised
    # ``ACTION <name>`` header is implementation. Checked before the marker so
    # the header itself never ends up in the declaration of a new object.
    action_body = split_action_projection(normalized)
    if action_body is not None:
        return "", action_body.strip()
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
        return normalize_fs_path(path)

    def _manifest_view_root(self, manifest):
        return manifest_view_root(manifest, self.project_root)

    def _safe_path_in_root(self, relative_path, root_path):
        return safe_path_in_root(relative_path, root_path, reject_hidden=True)

    def _managed_relative_paths(self, entry):
        return managed_relative_paths(entry)

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

        for entry in manifest_entries(manifest):
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

    def _replace_extension(self, relative_path, extension):
        return replace_extension(relative_path, extension)

    def _xml_full_path(self, entry):
        """Resolve an entry's xml file, honoring the text-first .dump mirror."""
        xml_path = entry.get("xml_path")
        if not xml_path:
            return None
        if (entry.get("xml_root") or "").lower() == "dump":
            return os.path.join(self.dump_path, "xml", xml_path)
        return os.path.join(self.views_path, xml_path)

    def _projection_change_info(
        self, projection_paths, projection_hashes, treat_missing_hash_as_changed=False
    ):
        return detect_projection_changes(
            projection_paths,
            self.views_path,
            expected_hashes=projection_hashes,
            missing_hash_is_change=treat_missing_hash_as_changed,
        )

    def _relative_path(self, full_path):
        return os.path.relpath(full_path, self.views_path).replace(os.sep, "/")

    def _discover_pending_st_creates(self, model, managed_paths, allow_sibling_xml=False):
        from _pending_discovery import discover_pending_st
        return discover_pending_st(self, model, managed_paths, allow_sibling_xml)

    def _discover_pending_xml_creates(self, model, managed_paths):
        from _pending_discovery import discover_pending_xml
        return discover_pending_xml(self, model, managed_paths)

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
        replace_text_blob_values(root, decode_st(projection_text, root))
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
                if decode_csv(csv_content, root, extractor):
                    changed = True
            except ProjectionValidationError as error:
                raise ProjectionValidationError(
                    "{0}: {1}".format(projection_path, error)
                )

        if changed:
            return entry_to_xml(root)
        return xml_text

    def _st_create_metadata(self, node, st_path, st_content):
        """Pre-populate create_* metadata so an st-only entry whose object is
        also missing from the IDE can be recreated from its text."""
        semantic_kind = kind_for_type_guid(self.profile, node.type)
        if not semantic_kind:
            semantic_kind = _detect_st_kind(st_content)
        if not semantic_kind:
            return
        base_name = os.path.splitext(os.path.basename(str(st_path)))[0]
        object_name = base_name
        parent_name = None
        if "." in base_name and semantic_kind in ("method", "action", "property"):
            parent_name, object_name = base_name.rsplit(".", 1)
        declaration, implementation = _split_st_create_content(
            strip_cds_text_sync_pragmas(st_content)
        )
        node.metadata["create_kind"] = semantic_kind
        if node.type:
            node.metadata["create_type_guid"] = node.type
        node.metadata["create_path"] = str(st_path).replace("\\", "/")
        node.metadata["create_name"] = object_name
        node.metadata["create_parent_name"] = parent_name
        node.metadata["create_declaration"] = declaration
        node.metadata["create_implementation"] = implementation

    def _load_manifest_for_read(self):
        """Load the manifest and enforce its view-root invariant."""
        if not os.path.exists(self.manifest_path):
            print("Manifest not found at:", self.manifest_path)
            return None
        with open(self.manifest_path, "r") as handle:
            manifest = json.load(handle)
        self._ensure_view_root_is_current(manifest)
        return manifest

    @staticmethod
    def _node_from_manifest_entry(entry):
        """Create a model node from the manifest's stable identity fields."""
        node = ProjectNode(
            entry.get("guid"),
            entry.get("name"),
            entry.get("type_guid"),
            entry.get("parent_guid"),
        )
        node.metadata["original_hash"] = entry.get("hash")
        for key in ("structured_view_guid", "structured_view_single_attrs"):
            if entry.get(key):
                node.metadata[key] = entry.get(key)
        return node

    def _read_view_only_entry(self, node, entry, managed_paths):
        """Read a non-XML view entry and update its managed path metadata."""
        view_path = entry.get("view_path")
        if not view_path:
            return
        normalized_path = view_path.replace("\\", "/")
        managed_paths.add(normalized_path)
        node.metadata["view_path"] = view_path
        full_path = os.path.join(self.views_path, view_path)
        if os.path.exists(full_path):
            with codecs.open(full_path, "r", "utf-8") as handle:
                node.code = handle.read()

    @staticmethod
    def _read_xml_file(path):
        """Read UTF-8 XML and return ``(text, sha1)``."""
        with codecs.open(path, "r", "utf-8") as handle:
            text = handle.read()
        return text, sha1_hex(text)

    def read(self):
        from _folder_reader_pipeline import read as read_pipeline
        return read_pipeline(self)
