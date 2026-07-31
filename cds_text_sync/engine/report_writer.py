# -*- coding: utf-8 -*-
"""
report_writer.py - Generates machine-readable compare and diagnostic reports.
"""
import json
import os
import time

from xml_helpers import csv_projection_content, st_projection_content

MAX_INLINE_CONTENT_CHARS = 300000


class ReportWriter:
    def __init__(self, output_path):
        self.output_path = output_path

    def _timestamp(self):
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _node_content(self, node):
        if node is None:
            return ""
        xml_text = getattr(node, "xml_text", None)
        if xml_text:
            return xml_text
        return node.code or ""

    def _limited_content(self, value):
        value = value or ""
        if len(value) <= MAX_INLINE_CONTENT_CHARS:
            return value
        omitted = len(value) - MAX_INLINE_CONTENT_CHARS
        return value[:MAX_INLINE_CONTENT_CHARS] + "\n\n[cds-text-sync: content truncated; {0} characters omitted]".format(omitted)

    def _ide_projection_content(self, projection_path, ide_node, extractor_name=None):
        if ide_node is None:
            return ""
        if str(projection_path).lower().endswith(".csv"):
            return csv_projection_content(ide_node.entry_element, extractor_name) or ""
        if str(projection_path).lower().endswith(".st"):
            return st_projection_content(ide_node.entry_element) or (ide_node.code or "")
        return (ide_node.code or "")

    def _projection_diff(self, ide_node, folder_node):
        if folder_node is None:
            return None
        projection_contents = folder_node.metadata.get("projection_contents") or {}
        if not projection_contents:
            return None
        selected_path = None
        changed_paths = folder_node.metadata.get("projection_changed_paths") or []
        for projection_path in changed_paths:
            if projection_path in projection_contents:
                selected_path = projection_path
                break
        if selected_path is None:
            for projection_path in sorted(projection_contents.keys()):
                if str(projection_path).lower().endswith((".st", ".csv")):
                    selected_path = projection_path
                    break
        if not selected_path:
            return None
        format_name = os.path.splitext(selected_path)[1].lstrip(".").lower()
        projection_extractors = folder_node.metadata.get("projection_extractors") or {}
        extractor_name = projection_extractors.get(selected_path)
        return {
            "path": selected_path,
            "format": format_name,
            "disk_content": projection_contents.get(selected_path) or "",
            "ide_content": self._ide_projection_content(selected_path, ide_node, extractor_name),
        }

    def _node_info(self, guid, ide_model=None, folder_model=None):
        ide_node = ide_model.get_node(guid) if ide_model is not None else None
        folder_node = folder_model.get_node(guid) if folder_model is not None else None
        node = folder_node or ide_node
        model = folder_model if folder_node is not None else ide_model
        source = ""
        if folder_node is not None:
            source = "folder"
        elif ide_node is not None:
            source = "ide"

        if node is None:
            return {
                "guid": guid,
                "name": guid,
                "type_guid": "",
                "path": "",
                "view_path": "",
                "source": source,
                "ide_content": "",
                "disk_content": "",
            }

        view_path = node.metadata.get("view_path", "")
        if not view_path and model is not None:
            try:
                view_path = node.get_view_path(model, extension=".xml")
            except Exception:
                view_path = ""

        display_path = "/".join([part for part in (node.display_path or []) if part])
        if not display_path and view_path:
            display_path = view_path

        info = {
            "guid": guid,
            "name": node.name,
            "type_guid": node.type or "",
            "path": display_path,
            "view_path": view_path,
            "source": source,
        }
        projection_diff = self._projection_diff(ide_node, folder_node)
        if projection_diff:
            info["projection_diff"] = projection_diff
        use_projection_content = bool(
            projection_diff
            and (
                projection_diff.get("disk_content", "") != projection_diff.get("ide_content", "")
                or (folder_node is not None and folder_node.metadata.get("projection_changed_paths"))
                or (folder_node is not None and folder_node.metadata.get("projection_conflict"))
            )
        )
        if use_projection_content:
            info["ide_content"] = ""
            info["disk_content"] = ""
        else:
            info["ide_content"] = self._limited_content(self._node_content(ide_node))
            info["disk_content"] = self._limited_content(self._node_content(folder_node))
        if folder_node is not None:
            if folder_node.metadata.get("projection_changed_paths"):
                info["projection_changed_paths"] = folder_node.metadata.get("projection_changed_paths")
            if folder_node.metadata.get("projection_conflict"):
                info["projection_conflict"] = True
        return info

    def _node_summary(self, guid, ide_model=None, folder_model=None):
        info = self._node_info(guid, ide_model=ide_model, folder_model=folder_model)
        info["ide_content"] = ""
        info["disk_content"] = ""
        projection_diff = info.get("projection_diff")
        if projection_diff:
            projection_diff["ide_content"] = ""
            projection_diff["disk_content"] = ""
        return info
        
    def write_diff_report(self, diff_result, ide_model=None, folder_model=None, include_objects=False):
        report = {
            "summary": {
                "modified": len(diff_result.get("modified", [])),
                "added": len(diff_result.get("added", [])),
                "deleted": len(diff_result.get("deleted", [])),
                "unchanged": len(diff_result.get("unchanged", []))
            },
            "details": diff_result
        }

        if include_objects:
            objects = {}
            for key in ("modified", "added", "deleted"):
                objects[key] = [
                    self._node_info(guid, ide_model=ide_model, folder_model=folder_model)
                    for guid in diff_result.get(key, [])
                ]
            objects["unchanged"] = [
                self._node_summary(guid, ide_model=ide_model, folder_model=folder_model)
                for guid in diff_result.get("unchanged", [])
            ]
            report["objects"] = objects
        
        with open(self.output_path, "w") as f:
            json.dump(report, f, indent=2)
            
        print("[{0}] Report generated at: {1}".format(self._timestamp(), self.output_path))
