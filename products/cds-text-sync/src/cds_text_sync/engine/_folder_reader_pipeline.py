# -*- coding: utf-8 -*-
"""FolderReader entry-model assembly pipeline."""

import os

from _project_model import ProjectModel


def read(reader):
    """Build a ProjectModel from the manifest and managed files."""
    self = reader
    manifest = self._load_manifest_for_read()
    if manifest is None:
        return None

    text_first = (
        str(manifest.get("sync_mode") or "").strip().lower() == "text_first"
    )
    ns = manifest.get("ns", "")
    model = ProjectModel(namespace=ns)
    managed_paths = set()

    for entry in manifest.get("entries", []):
        node = self._node_from_manifest_entry(entry)

        xml_path = entry.get("xml_path")
        if xml_path:
            managed_paths.add(xml_path.replace("\\", "/"))
            projection_paths = list(entry.get("projection_paths") or [])
            projection_hashes = dict(entry.get("projection_hashes") or {})
            for projection_path in projection_paths:
                managed_paths.add(str(projection_path).replace("\\", "/"))
            node.metadata["view_path"] = xml_path
            xml_in_dump = (entry.get("xml_root") or "").lower() == "dump"

            if text_first and not any(
                str(path).lower().endswith(".st") for path in projection_paths
            ):
                # Text-first: probe the expected sibling .st even when the
                # manifest registered no ST projection for this entry.
                candidate = self._replace_extension(xml_path, ".st")
                if os.path.exists(self._projection_full_path(candidate)):
                    projection_paths.append(candidate)
                    managed_paths.add(str(candidate).replace("\\", "/"))

            full_path = self._xml_full_path(entry)
            xml_exists = bool(full_path) and os.path.exists(full_path)
            if xml_exists:
                node.xml_text, raw_xml_hash = self._read_xml_file(full_path)
                if xml_in_dump:
                    # The .dump mirror is tool-owned; direct edits there are
                    # not a user surface and never count as changes.
                    node.metadata["xml_changed"] = False
                else:
                    node.metadata["xml_changed"] = bool(
                        entry.get("hash") and entry.get("hash") != raw_xml_hash
                    )
                (
                    projection_changed_paths,
                    current_projection_hashes,
                    current_projection_contents,
                ) = self._projection_change_info(
                    projection_paths,
                    projection_hashes,
                    treat_missing_hash_as_changed=text_first,
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
                has_st_content = any(
                    str(path).lower().endswith(".st")
                    for path in current_projection_contents
                )
                if xml_in_dump:
                    if has_st_content:
                        # Patch must be built from the .st overlaid on the
                        # IDE baseline, never from the (possibly stale)
                        # mirror xml.
                        node.metadata["st_authoritative"] = True
                    elif not current_projection_contents:
                        # No user-editable artifact exists for this entry.
                        node.metadata["import_inert"] = True
                node.xml_text = self._rehydrate_externalized_text(
                    node.xml_text,
                    projection_paths,
                )
                node.xml_text = self._rehydrate_import_safe_csv(
                    node.xml_text,
                    projection_paths,
                    entry.get("projection_extractors") or {},
                    entry.get("projection_import_safe") or {},
                )
                exclude_from_build = self._extract_bool_property(
                    node.xml_text, "ExcludeFromBuild"
                )
                if exclude_from_build is not None:
                    node.metadata["exclude_from_build"] = exclude_from_build
            elif text_first:
                # The xml baseline is absent (fresh clone: .dump is
                # git-ignored). The entry is driven by its .st alone.
                (
                    projection_changed_paths,
                    current_projection_hashes,
                    current_projection_contents,
                ) = self._projection_change_info(
                    projection_paths,
                    projection_hashes,
                    treat_missing_hash_as_changed=True,
                )
                st_paths = [
                    path
                    for path in current_projection_contents
                    if str(path).lower().endswith(".st")
                ]
                if st_paths:
                    node.metadata["st_only"] = True
                    if projection_changed_paths:
                        node.metadata["projection_changed_paths"] = (
                            projection_changed_paths
                        )
                    node.metadata["projection_hashes"] = current_projection_hashes
                    node.metadata["projection_contents"] = (
                        current_projection_contents
                    )
                    self._st_create_metadata(
                        node,
                        st_paths[0],
                        current_projection_contents[st_paths[0]],
                    )
        else:
            self._read_view_only_entry(node, entry, managed_paths)

        model.add_node(node)

    self._discover_pending_st_creates(
        model, managed_paths, allow_sibling_xml=text_first
    )
    self._discover_pending_xml_creates(model, managed_paths)

    return model
