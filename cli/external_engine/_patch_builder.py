# -*- coding: utf-8 -*-
"""
_patch_builder.py - Generates an IMPORT.xml patch based on diff results.
"""

import os
import xml.etree.ElementTree as ET

from xml_helpers import (
    entry_to_xml,
    normalize_guid,
    replace_text_blob_values,
    split_st_projection_values,
    strip_cds_text_sync_pragmas,
    text_blob_elements,
)

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DEFAULT_STRUCTURED_VIEW_SINGLE_ATTRS = {
    XML_SPACE: "preserve",
    "Type": "{3daac5e4-660e-42e4-9cea-3711b98bfb63}",
    "Method": "IArchivable",
}
PERSISTENT_GVL_TYPE_GUIDS = set(
    [
        "261bd6e6-249c-4232-bb6f-84c2fbeef430",
        "3183921b-cc91-4712-9781-c3b6555122b5",
    ]
)


class UnsupportedPatchError(Exception):
    pass


class PatchBuilder:
    def __init__(self, diff_result, ide_model, folder_model):
        self.diff_result = diff_result
        self.ide_model = ide_model
        self.folder_model = folder_model
        self.ns = ide_model.ns

    def _structured_view_guid(self, guid):
        folder_node = self.folder_model.get_node(guid)
        ide_node = self.ide_model.get_node(guid)
        for node in (folder_node, ide_node):
            if node and node.metadata.get("structured_view_guid"):
                return node.metadata.get("structured_view_guid")
        if folder_node and folder_node.parent_guid:
            parent_guid = folder_node.parent_guid
            while parent_guid:
                parent = self.folder_model.get_node(
                    parent_guid
                ) or self.ide_model.get_node(parent_guid)
                if parent and parent.metadata.get("structured_view_guid"):
                    return parent.metadata.get("structured_view_guid")
                parent_guid = parent.parent_guid if parent else None
        raise UnsupportedPatchError(
            "Cannot resolve StructuredView Guid for object: {0}".format(guid)
        )

    def _structured_view_single_attrs(self, guid):
        folder_node = self.folder_model.get_node(guid)
        ide_node = self.ide_model.get_node(guid)
        for node in (folder_node, ide_node):
            if node and node.metadata.get("structured_view_single_attrs"):
                return dict(node.metadata.get("structured_view_single_attrs"))
        return dict(DEFAULT_STRUCTURED_VIEW_SINGLE_ATTRS)

    def _conflict_st_text(self, folder_node):
        """Return the on-disk .st projection text for a conflicting node.

        folder_reader stores changed projection contents under
        metadata['projection_contents'], keyed by projection path. Pick the
        .st projection so the caller can overlay it on the IDE baseline.
        """
        contents = (folder_node.metadata or {}).get("projection_contents") or {}
        for path, text in contents.items():
            if str(path).lower().endswith(".st"):
                return text
        return None

    def _patch_entry(self, guid):
        ide_node = self.ide_model.get_node(guid)
        folder_node = self.folder_model.get_node(guid)

        # Projection conflict: both the raw XML projection and the .st text were
        # edited on disk. Policy is .st wins -> rebuild from the IDE baseline
        # structure with the .st text blobs overlaid, ignoring the conflicting
        # raw-XML edit. (folder_node.xml_text would leak that XML edit.)
        if guid in (self.diff_result.get("projection_conflicts") or []):
            st_text = self._conflict_st_text(folder_node) if folder_node else None
            ide_xml = getattr(ide_node, "xml_text", None) if ide_node else None
            if st_text is not None and ide_xml:
                try:
                    root = ET.fromstring(ide_xml)
                    if text_blob_elements(root):
                        replace_text_blob_values(
                            root,
                            split_st_projection_values(
                                strip_cds_text_sync_pragmas(st_text), root
                            ),
                        )
                        return ET.fromstring(entry_to_xml(root))
                except Exception:
                    pass  # fall through to the default paths below

        if folder_node and getattr(folder_node, "xml_text", None):
            return ET.fromstring(folder_node.xml_text)
        if ide_node and ide_node.entry_element is not None and folder_node:
            # Legacy fallback for old .st views.
            entry = ide_node.entry_element
            new_code = folder_node.code
            blobs = entry.findall(".//{0}TextBlobForSerialisation".format(self.ns))
            if blobs and new_code is not None:
                blobs[0].text = new_code
            return entry
        raise UnsupportedPatchError(
            "Cannot build patch entry for guid: {0}".format(guid)
        )

    def _is_pending_create(self, guid):
        folder_node = self.folder_model.get_node(guid)
        return bool(folder_node and folder_node.metadata.get("pending_create"))

    def _application_scope(self, display_path):
        parts = [
            str(part or "").strip()
            for part in (display_path or [])
            if str(part or "").strip()
        ]
        for index, part in enumerate(parts):
            lowered = part.lower()
            if (
                lowered == "application"
                or lowered.endswith("_application")
                or lowered.endswith(" application")
            ):
                return tuple(value.lower() for value in parts[: index + 1])
        return tuple(value.lower() for value in parts)

    def _existing_persistent_gvl_in_scope(self, type_guid, display_path):
        normalized_type_guid = normalize_guid(type_guid)
        if (
            normalized_type_guid
            and normalized_type_guid not in PERSISTENT_GVL_TYPE_GUIDS
        ):
            return None
        scope = self._application_scope(display_path)
        for node in self.ide_model.nodes.values():
            if normalize_guid(node.type) not in PERSISTENT_GVL_TYPE_GUIDS:
                continue
            if self._application_scope(node.display_path) == scope:
                return node
        return None

    def _validate_text_create(self, guid):
        folder_node = self.folder_model.get_node(guid)
        if folder_node is None:
            return
        kind = (
            folder_node.metadata.get("create_kind") or folder_node.type or ""
        ).lower()
        if kind != "persistent_gvl":
            return
        existing = self._existing_persistent_gvl_in_scope(
            folder_node.metadata.get("create_type_guid") or folder_node.type,
            folder_node.display_path,
        )
        if existing is None:
            return

        create_path = (
            folder_node.metadata.get("create_path")
            or folder_node.metadata.get("view_path")
            or ""
        )
        existing_path_parts = [part for part in (existing.display_path or []) if part]
        existing_path_parts.append(existing.output_name or existing.name or "")
        existing_path = "/".join(existing_path_parts)
        raise UnsupportedPatchError(
            "Cannot create persistent variable list '{0}' at {1}: a persistent variable list already exists in the same application scope ({2}). CODESYS accepts only one Persistent Variables object per application; edit the existing object instead of creating a second one.".format(
                folder_node.metadata.get("create_name") or folder_node.name or guid,
                create_path,
                existing_path,
            )
        )

    def _append_text_create(self, parent, guid):
        folder_node = self.folder_model.get_node(guid)
        if folder_node is None:
            raise UnsupportedPatchError(
                "Cannot build create entry for guid: {0}".format(guid)
            )

        attrs = {
            "Path": folder_node.metadata.get("create_path")
            or folder_node.metadata.get("view_path")
            or "",
            "Name": folder_node.metadata.get("create_name") or folder_node.name or "",
            "Kind": folder_node.metadata.get("create_kind") or folder_node.type or "",
        }
        parent_name = folder_node.metadata.get("create_parent_name")
        if parent_name:
            attrs["ParentName"] = parent_name

        type_guid = folder_node.metadata.get("create_type_guid")
        if type_guid:
            tg = type_guid.strip().lower()
            if not tg.startswith("{"):
                tg = "{" + tg
            if not tg.endswith("}"):
                tg = tg + "}"
            attrs["TypeGuid"] = tg

        create_elem = ET.SubElement(parent, "CreateTextObject", attrs)
        declaration = folder_node.metadata.get("create_declaration")
        implementation = folder_node.metadata.get("create_implementation")
        if declaration is not None:
            decl_elem = ET.SubElement(create_elem, "Declaration")
            decl_elem.text = declaration
        if implementation is not None:
            impl_elem = ET.SubElement(create_elem, "Implementation")
            impl_elem.text = implementation

    def build_patch(self, output_path):
        # Import policy: disk wins, and the .st text is the canonical source of
        # truth. The .st content is already rehydrated into folder_node.xml_text
        # at read time (folder_reader._rehydrate_externalized_text), so the
        # patch built below already reflects .st. A "projection conflict" (both
        # the XML projection and the .st/CSV projection edited on disk) is no
        # longer a hard stop -- we warn and let .st win.
        projection_conflicts = self.diff_result.get("projection_conflicts", [])
        if projection_conflicts:
            print(
                "Warning: projection conflict for {0} -- taking .st text as the "
                "source of truth (XML projection edits to the same object are "
                "ignored).".format(", ".join(projection_conflicts))
            )

        # Non-.st projections (CSV/XML) that were edited on disk but have no
        # importer back into the IDE: we cannot apply these, so warn and skip
        # rather than aborting the whole import batch.
        unsupported_projection_changes = self.diff_result.get(
            "unsupported_projection_changes", {}
        )
        if unsupported_projection_changes:
            changed = []
            for guid, paths in unsupported_projection_changes.items():
                changed.append("{0}: {1}".format(guid, ", ".join(paths or [])))
            print(
                "Warning: unsupported (export-only) projection edits skipped -- "
                "no importer back into the IDE for: {0}".format(
                    "; ".join(changed)
                )
            )

        modified_guids = self.diff_result.get("modified", [])
        added_guids = self.diff_result.get("added", [])
        deleted_guids = self.diff_result.get("deleted", [])
        create_guids = [guid for guid in added_guids if self._is_pending_create(guid)]
        patch_guids = modified_guids + [
            guid for guid in added_guids if guid not in create_guids
        ]

        if deleted_guids:
            print(
                "Warning: Deleted objects are ignored because IMPORT.xml deletion is not supported yet: {0}".format(
                    ", ".join(deleted_guids)
                )
            )

        root_tag = "{0}Project".format(self.ns) if self.ns else "Project"
        patch_root = ET.Element(root_tag)

        if not patch_guids and not create_guids:
            patch_tree = ET.ElementTree(patch_root)
            patch_tree.write(output_path, encoding="utf-8", xml_declaration=True)
            print("No changes detected to patch.")
            print("Empty patch generated at", output_path)
            return False

        for guid in create_guids:
            self._validate_text_create(guid)

        print(
            "Building patch for {0} objects...".format(
                len(patch_guids) + len(create_guids)
            )
        )

        sv_tag = "{0}StructuredView".format(self.ns) if self.ns else "StructuredView"
        single_tag = "{0}Single".format(self.ns) if self.ns else "Single"
        null_tag = "{0}Null".format(self.ns) if self.ns else "Null"
        el_tag = "{0}List2".format(self.ns) if self.ns else "List2"

        grouped_guids = []
        for guid in patch_guids:
            sv_guid = self._structured_view_guid(guid)
            for item in grouped_guids:
                if item[0] == sv_guid:
                    item[1].append(guid)
                    break
            else:
                grouped_guids.append((sv_guid, [guid]))

        for sv_guid, guids in grouped_guids:
            sv = ET.SubElement(patch_root, sv_tag, {"Guid": sv_guid})
            wrapper = ET.SubElement(
                sv, single_tag, self._structured_view_single_attrs(guids[0])
            )
            ET.SubElement(wrapper, null_tag, {"Name": "Profile"})
            el = ET.SubElement(wrapper, el_tag, {"Name": "EntryList"})
            for guid in guids:
                el.append(self._patch_entry(guid))

        if create_guids:
            creates_root = ET.SubElement(patch_root, "CreateTextObjects")
            create_guids.sort(
                key=lambda guid: (
                    os.path.splitext(
                        os.path.basename(
                            self.folder_model.get_node(guid).metadata.get(
                                "create_path", ""
                            )
                        )
                    )[0].count("."),
                    self.folder_model.get_node(guid)
                    .metadata.get("create_path", "")
                    .lower(),
                )
            )
            for guid in create_guids:
                self._append_text_create(creates_root, guid)

        patch_tree = ET.ElementTree(patch_root)
        patch_tree.write(output_path, encoding="utf-8", xml_declaration=True)
        print("Patch generated at", output_path)
        return True
