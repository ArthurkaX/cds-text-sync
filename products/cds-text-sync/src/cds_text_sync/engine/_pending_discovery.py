# -*- coding: utf-8 -*-
"""Pending project-object discovery pipeline."""

import codecs
import os
import re
import xml.etree.ElementTree as ET

from _pending_files import iter_files
from _project_model import ProjectNode
from _project_profiles import kind_for_type_guid
from xml_helpers import (
    extract_cds_text_sync_type_guid,
    sha1_hex,
    strip_cds_text_sync_pragmas,
)
from folder_reader import _detect_st_kind, _split_st_create_content


def discover_pending_st(reader, model, managed_paths, allow_sibling_xml=False):
    self = reader
    if not os.path.exists(self.views_path):
        return

    for rel_path, full_path in iter_files(self.views_path, ".st"):
            filename = os.path.basename(full_path)
            if rel_path in managed_paths:
                continue
            sidecar_xml_path = os.path.splitext(full_path)[0] + ".xml"
            if os.path.exists(sidecar_xml_path) and not allow_sibling_xml:
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


def discover_pending_xml(reader, model, managed_paths):
    self = reader
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

    for rel_path, full_path in iter_files(self.views_path, ".xml"):
            filename = os.path.basename(full_path)
            # A .cds-object.xml file is always a container/object descriptor
            # sidecar, never a standalone importable native object -- skip it
            # regardless of whether it is a dotfile (.cds-object.xml) or named
            # (ObjectName.cds-object.xml).
            if filename.lower().endswith(".cds-object.xml"):
                continue
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
