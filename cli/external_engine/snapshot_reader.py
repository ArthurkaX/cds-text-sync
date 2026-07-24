# -*- coding: utf-8 -*-
"""
snapshot_reader.py - Reads and normalizes the native IDE.xml snapshot.
"""
import xml.etree.ElementTree as ET
import ntpath

from _locale_aliases import canonical_display
from _project_model import ProjectModel, ProjectNode
from xml_helpers import (
    entry_to_xml,
    extract_bool_property,
    get_namespace,
    join_text_blob_values,
    normalize_guid,
    text_blob_values,
)

PROJECT_ROOT_POUS_TYPE_GUIDS = set([
    # Project-level objects shown by CODESYS under POUs/<project name>.
    "8753fe6f-4a22-4320-8103-e553c4fc8e04",  # Project Settings
    "085afe48-c5d8-4ea5-ab0d-b35701fa6009",  # Project Information
    # Project-global text list shown by CODESYS under the POUs section.
    "63784cbb-9ba0-45e6-9d69-babf3f040511",
    "adb5cb65-8e1d-4a00-b70a-375ea27582f3",  # Library Manager
])

EMBEDDED_RESOURCE_TYPE_GUID = "9001d745-b9c5-4d77-90b7-b29c3f77a23b"
SYSTEM_TEXT_LIST_TYPE_GUID = "2bef0454-1bd3-412a-ac2c-af0f31dbc40f"
ALIAS_DEDUP_TYPE_GUIDS = set([
    # CODESYS can expose the same logical application objects through both a
    # short POU view and the concrete Device/PLC Logic/Application tree.
    "6f9dac99-8de1-4efc-8465-68ac443b7d08",  # POU
    "ffbfa93a-b94d-45fc-a329-229860183b1d",  # GVL
    "2db5746d-d284-4425-9f7f-2663a34b0ebc",  # DUT
])

class SnapshotReader:
    def __init__(self, snapshot_path, project_name=None):
        self.snapshot_path = snapshot_path
        self.project_name = project_name
        self.ns = ""
        
    def _extract_st_code(self, obj_elem):
        if obj_elem is None:
            return None
        return join_text_blob_values(text_blob_values(obj_elem))

    def _implementation_kind(self, obj_elem):
        if obj_elem is None:
            return None

        implementation = obj_elem.find("./{0}Single[@Name='Implementation']".format(self.ns))
        if implementation is None:
            return None

        if implementation.find(".//{0}List2[@Name='NetworkList']".format(self.ns)) is not None:
            return "graphical"
        if implementation.find(".//{0}Single[@Name='Items']".format(self.ns)) is not None:
            return "graphical"
        if implementation.find(".//{0}Single[@Name='TextBlobForSerialisation']".format(self.ns)) is not None:
            return "textual"
        if implementation.find(".//{0}Array[@Name='TextLines']".format(self.ns)) is not None:
            return "textual"
        return None

    def _extract_path(self, entry_elem):
        path_elem = entry_elem.find("./{0}Array[@Name='Path']".format(self.ns))
        if path_elem is None:
            return []
        parts = []
        for item in list(path_elem):
            text = (item.text or "").strip()
            if text:
                # CODESYS emits localized standard-container labels on non-English
                # UI locales; fold them back to canonical English so the on-disk
                # tree and import-time resolution stay locale-independent. English
                # segments fall through unchanged (no-op).
                parts.append(canonical_display(text))
        return parts

    def _structured_view_entry_lists(self, root):
        structured_views = root.findall(".//{0}StructuredView".format(self.ns))
        if not structured_views:
            return [(None, None, entry_list) for entry_list in root.findall(".//{0}List2[@Name='EntryList']".format(self.ns))]

        result = []
        for structured_view in structured_views:
            sv_guid = structured_view.attrib.get("Guid")
            wrapper = None
            for child in list(structured_view):
                if child.tag == "{0}Single".format(self.ns):
                    wrapper = child
                    break
            for entry_list in structured_view.findall(".//{0}List2[@Name='EntryList']".format(self.ns)):
                result.append((sv_guid, dict(wrapper.attrib) if wrapper is not None else None, entry_list))
        return result

    def _resource_output_name(self, name):
        resource_name = name.split("|", 1)[-1]
        return ntpath.basename(resource_name) or resource_name or name

    def _normalize_pathless_output(self, node):
        node_type = (node.type or "").strip().lower()
        if node.display_path:
            return
        if node_type in PROJECT_ROOT_POUS_TYPE_GUIDS:
            node.display_path = ["POUs"]
        elif node_type == EMBEDDED_RESOURCE_TYPE_GUID:
            node.display_path = ["Resources", "Embedded"]
            node.output_name = self._resource_output_name(node.name)
        elif node_type == SYSTEM_TEXT_LIST_TYPE_GUID and node.name == "System":
            node.display_path = ["Resources"]

    def _output_key_parts(self, node):
        parts = [part.strip().lower() for part in (node.display_path or []) if part and part.strip()]
        parts.append((node.output_name or node.name or "").strip().lower())
        return tuple(parts)

    def _output_log_path(self, node):
        parts = [part.strip() for part in (node.display_path or []) if part and part.strip()]
        parts.append((node.output_name or node.name or "").strip())
        return "\\".join(parts)

    def _is_path_suffix_alias(self, left, right):
        if not left or not right or left == right:
            return False
        shorter, longer = (left, right) if len(left) < len(right) else (right, left)
        return longer[-len(shorter):] == shorter

    def _alias_identity(self, node):
        node_type = (node.type or "").strip().lower()
        if node_type not in ALIAS_DEDUP_TYPE_GUIDS:
            return None
        return (node_type, (node.output_name or node.name or "").strip().lower())

    def _preferred_alias_node(self, existing, candidate):
        existing_parts = self._output_key_parts(existing)
        candidate_parts = self._output_key_parts(candidate)
        if len(candidate_parts) > len(existing_parts):
            return candidate
        return existing

    def _deduplicate_structured_view_aliases(self, nodes):
        result = []
        aliases = {}
        for node in nodes:
            identity = self._alias_identity(node)
            if not identity:
                result.append(node)
                continue

            existing_index = None
            for index in aliases.get(identity, []):
                existing = result[index]
                if self._is_path_suffix_alias(self._output_key_parts(existing), self._output_key_parts(node)):
                    existing_index = index
                    break

            if existing_index is None:
                aliases.setdefault(identity, []).append(len(result))
                result.append(node)
                continue

            preferred = self._preferred_alias_node(result[existing_index], node)
            if preferred is not result[existing_index]:
                result[existing_index] = preferred
                print(
                    "Deduplicated StructuredView alias, kept concrete path: {0} -> {1}".format(
                        node.name,
                        self._output_log_path(preferred),
                    )
                )
            else:
                print(
                    "Deduplicated StructuredView alias, ignored duplicate path: {0} -> {1}".format(
                        node.name,
                        self._output_log_path(node),
                    )
                )
        return result

    def read(self):
        try:
            tree = ET.parse(self.snapshot_path)
            root = tree.getroot()
            self.ns = get_namespace(root.tag)
        except Exception as e:
            print("Error parsing XML:", e)
            return None

        nodes = []

        # In Native XML, the tree is spread across multiple StructuredViews.
        entry_lists = self._structured_view_entry_lists(root)
        if not entry_lists:
            print("Could not find any EntryList in native XML.")
            return None

        for structured_view_guid, structured_view_single_attrs, entry_list in entry_lists:
            entries = entry_list.findall("./{0}Single".format(self.ns))
            
            for entry in entries:
                meta = entry.find("./{0}Single[@Name='MetaObject']".format(self.ns))
                if meta is None:
                    continue
                    
                guid_elem = meta.find("./{0}Single[@Name='Guid']".format(self.ns))
                parent_elem = meta.find("./{0}Single[@Name='ParentGuid']".format(self.ns))
                name_elem = meta.find("./{0}Single[@Name='Name']".format(self.ns))
                type_elem = meta.find("./{0}Single[@Name='TypeGuid']".format(self.ns))
                
                if guid_elem is None:
                    continue
                    
                guid = normalize_guid(guid_elem.text)
                    
                parent_guid = normalize_guid(parent_elem.text) if parent_elem is not None else None
                if parent_guid == "00000000-0000-0000-0000-000000000000":
                    parent_guid = None
                    
                name = (name_elem.text or "").strip() if name_elem is not None else "Unknown"
                node_type = type_elem.text if type_elem is not None else None
                
                p_node = ProjectNode(guid, name, node_type, parent_guid)
                p_node.entry_element = entry
                p_node.xml_text = entry_to_xml(entry)
                p_node.display_path = self._extract_path(entry)
                if structured_view_guid:
                    p_node.metadata["structured_view_guid"] = structured_view_guid
                if structured_view_single_attrs:
                    p_node.metadata["structured_view_single_attrs"] = structured_view_single_attrs
                exclude_from_build = extract_bool_property(entry, "ExcludeFromBuild", self.ns)
                if exclude_from_build is not None:
                    p_node.metadata["exclude_from_build"] = exclude_from_build
                self._normalize_pathless_output(p_node)
                
                obj_elem = entry.find("./{0}Single[@Name='Object']".format(self.ns))
                p_node.code = self._extract_st_code(obj_elem)
                implementation_kind = self._implementation_kind(obj_elem)
                if implementation_kind:
                    p_node.metadata["implementation_kind"] = implementation_kind
                
                nodes.append(p_node)

        model = ProjectModel(namespace=self.ns)
        for node in self._deduplicate_structured_view_aliases(nodes):
            if node.guid in model.nodes:
                continue
            model.add_node(node)
        return model
