# -*- coding: utf-8 -*-
"""
engine_cli.py - Command Line Interface for the Python 3 External Engine.
"""

import argparse
import os
import sys
import time

from _patch_builder import PatchBuilder, UnsupportedPatchError
from _project_layout import (
    LAYOUT_LEGACY_DUMP_VIEWS,
    LAYOUT_PROJECT_VIEW,
    LAYOUT_ROOT_VIEW,
    resolve_layout,
)
from _project_profiles import load_profile
from _project_settings import load_project_settings
from diff_engine import DiffEngine
from folder_reader import FolderReader
from folder_writer import FolderWriter
from report_writer import ReportWriter
from resources_report import build_resources_report
from snapshot_reader import SnapshotReader
from xml_helpers import ProjectionValidationError, normalize_guid


def _filter_guids(args):
    raw_values = getattr(args, "filter_guids", None) or []
    result = []
    seen = set()
    for raw_value in raw_values:
        for part in str(raw_value or "").replace(";", ",").split(","):
            guid = normalize_guid(part)
            if guid and guid not in seen:
                seen.add(guid)
                result.append(guid)
    return result


def _filter_diff_result(diff_result, selected_guids):
    if not selected_guids:
        return diff_result
    selected = set(selected_guids)
    filtered = {}
    for key, value in diff_result.items():
        if isinstance(value, list):
            filtered[key] = [guid for guid in value if guid in selected]
        elif isinstance(value, dict):
            filtered[key] = dict(
                (guid, data) for guid, data in value.items() if guid in selected
            )
        else:
            filtered[key] = value
    return filtered


def _timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(message):
    print("[{0}] {1}".format(_timestamp(), message))


def _settings(args):
    settings = load_project_settings(args.project_root)
    return settings


def _layout(args):
    settings = _settings(args)
    return resolve_layout(
        args.project_root,
        view_root=getattr(args, "view_root", None) or settings.get("view_root"),
        layout_mode=getattr(args, "layout", None) or settings.get("layout"),
    )


def _load_models(args, context):
    ide_reader = SnapshotReader(
        args.snapshot, project_name=os.path.basename(args.project_root)
    )
    ide_model = ide_reader.read()

    project_layout = _layout(args)
    dump_path = project_layout.dump_root
    folder_reader = FolderReader(project_layout.view_root, dump_path)
    try:
        folder_model = folder_reader.read()
    except ProjectionValidationError as error:
        print("Invalid projection edit:", error)
        sys.exit(1)
    except RuntimeError as error:
        print("Error:", error)
        sys.exit(1)

    if not ide_model or not folder_model:
        print("Failed to read models for {0}.".format(context))
        sys.exit(1)

    return ide_model, folder_model, dump_path


def _load_diff(args, context):
    ide_model, folder_model, dump_path = _load_models(args, context)
    settings = _settings(args)
    profile = load_profile(settings.get("profile"))
    differ = DiffEngine(ide_model, folder_model, profile=profile)
    return differ.compare(), ide_model, folder_model, dump_path


def _node_log_path(node, model):
    if node is None:
        return ""
    view_path = node.metadata.get("view_path", "")
    if not view_path:
        try:
            view_path = node.get_view_path(model, extension=".xml")
        except Exception:
            view_path = ""
    display_path = "/".join([part for part in (node.display_path or []) if part])
    return view_path or display_path or node.name or ""


def _log_diff_node(category, guid, ide_model, folder_model):
    ide_node = ide_model.get_node(guid) if ide_model is not None else None
    folder_node = folder_model.get_node(guid) if folder_model is not None else None
    node = folder_node or ide_node
    model = folder_model if folder_node is not None else ide_model
    name = node.name if node is not None else guid
    path = _node_log_path(node, model)
    details = []
    if folder_node is not None:
        changed_paths = folder_node.metadata.get("projection_changed_paths") or []
        if changed_paths:
            details.append("projection_changed=" + ", ".join(changed_paths))
        if folder_node.metadata.get("xml_changed"):
            details.append("xml_changed=true")
        if folder_node.metadata.get("projection_conflict"):
            details.append("projection_conflict=true")
    suffix = ""
    if details:
        suffix = " (" + "; ".join(details) + ")"
    _log("{0}: {1} [{2}] {3}{4}".format(category, name, guid, path, suffix))


def _log_compare_details(diff_result, ide_model, folder_model):
    _log(
        "Compare model sizes: ide={0}, disk={1}".format(
            len(ide_model.nodes),
            len(folder_model.nodes),
        )
    )
    summary_keys = [
        "modified",
        "added",
        "deleted",
        "unchanged",
        "projection_conflicts",
        "unsupported_projection_changes",
    ]
    summary_parts = []
    for key in summary_keys:
        value = diff_result.get(key, [])
        summary_parts.append("{0}={1}".format(key, len(value)))
    _log("Compare summary: " + ", ".join(summary_parts))

    for category in ("modified", "added", "deleted", "projection_conflicts"):
        for guid in diff_result.get(category, []):
            _log_diff_node(category, guid, ide_model, folder_model)

    for guid, paths in sorted(
        (diff_result.get("unsupported_projection_changes") or {}).items()
    ):
        _log_diff_node("unsupported_projection_changes", guid, ide_model, folder_model)
        for path in paths:
            _log("unsupported_projection_path: {0} -> {1}".format(guid, path))


def run_export(args):
    settings = _settings(args)
    project_layout = _layout(args)
    selected_guids = _filter_guids(args)
    if selected_guids:
        _log(
            f"Exporting selected objects from snapshot {args.snapshot} to view root {project_layout.view_root}"
        )
    else:
        _log(
            f"Exporting from snapshot {args.snapshot} to view root {project_layout.view_root}"
        )
    reader = SnapshotReader(
        args.snapshot, project_name=os.path.basename(args.project_root)
    )
    model = reader.read()
    if not model:
        print("Failed to read snapshot.")
        sys.exit(1)

    dump_path = project_layout.dump_root
    writer = FolderWriter(
        project_layout.view_root,
        dump_path,
        profile=load_profile(settings.get("profile")),
        projections=settings.get("projections"),
        selected_guids=selected_guids,
    )
    try:
        writer.write(model)
    except RuntimeError as error:
        print("Error:", error)
        sys.exit(1)


def run_compare(args):
    project_layout = _layout(args)
    _log(
        f"Comparing snapshot {args.snapshot} with view root {project_layout.view_root}"
    )
    diff_result, ide_model, folder_model, _ = _load_diff(args, "comparison")
    _log_compare_details(diff_result, ide_model, folder_model)

    reporter = ReportWriter(args.report)
    reporter.write_diff_report(
        diff_result,
        ide_model=ide_model,
        folder_model=folder_model,
        include_objects=bool(getattr(args, "include_objects", False)),
    )


def run_import(args):
    project_layout = _layout(args)
    selected_guids = _filter_guids(args)
    if selected_guids:
        _log(
            f"Importing selected objects from view root {project_layout.view_root} against snapshot {args.snapshot} to generate {args.patch}"
        )
    else:
        _log(
            f"Importing view root {project_layout.view_root} against snapshot {args.snapshot} to generate {args.patch}"
        )
    diff_result, ide_model, folder_model, _ = _load_diff(args, "import")
    diff_result = _filter_diff_result(diff_result, selected_guids)
    _log_compare_details(diff_result, ide_model, folder_model)

    patcher = PatchBuilder(diff_result, ide_model, folder_model)
    try:
        patcher.build_patch(args.patch)
    except UnsupportedPatchError as error:
        print("Failed to build import patch:", error)
        sys.exit(1)


def run_validate(args):
    project_layout = _layout(args)
    _log(
        f"Validating snapshot {args.snapshot} against view root {project_layout.view_root}"
    )
    diff_result, _, _, _ = _load_diff(args, "validation")

    has_diffs = any(len(v) > 0 for k, v in diff_result.items() if k != "unchanged")
    if has_diffs:
        print("Validation failed. Snapshot and folder state differ.")
        sys.exit(1)
    else:
        print("Validation successful. Snapshot matches folder state.")


def run_resources(args):
    _log(f"Analyzing resources from snapshot {args.snapshot}")
    build_resources_report(
        args.project_root,
        args.snapshot,
        args.report,
        log_path=getattr(args, "log", None),
        limit=int(getattr(args, "limit", 50) or 50),
    )


def main():
    parser = argparse.ArgumentParser(description="CODESYS Offline Sync Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # common arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--project-root", required=True, help="Path to project root"
    )
    parent_parser.add_argument(
        "--snapshot", required=True, help="Path to IDE.xml snapshot"
    )
    parent_parser.add_argument(
        "--view-root",
        "--views",
        dest="view_root",
        default=None,
        help="Path to editable project view root. --views is a backward-compatible alias.",
    )
    parent_parser.add_argument(
        "--layout",
        choices=[LAYOUT_LEGACY_DUMP_VIEWS, LAYOUT_PROJECT_VIEW, LAYOUT_ROOT_VIEW],
        default=None,
        help="Resolve default view root when --view-root is omitted.",
    )
    parent_parser.add_argument(
        "--filter-guids",
        action="append",
        default=[],
        help="Comma-separated GUID list for selected import/export operations.",
    )

    # export
    parser_export = subparsers.add_parser("export", parents=[parent_parser])

    # compare
    parser_compare = subparsers.add_parser("compare", parents=[parent_parser])
    parser_compare.add_argument("--report", required=True, help="Path to report JSON")
    parser_compare.add_argument(
        "--include-objects",
        action="store_true",
        help="Include object names and paths in the compare report",
    )

    # import
    parser_import = subparsers.add_parser("import", parents=[parent_parser])
    parser_import.add_argument(
        "--patch", required=True, help="Path to IMPORT.xml output"
    )

    # validate
    parser_validate = subparsers.add_parser("validate", parents=[parent_parser])

    # resources
    parser_resources = subparsers.add_parser("resources", parents=[parent_parser])
    parser_resources.add_argument(
        "--report", required=True, help="Path to resources report JSON"
    )
    parser_resources.add_argument(
        "--log", default=None, help="Path to human-readable top resources log"
    )
    parser_resources.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of largest objects to include in the top list",
    )

    args = parser.parse_args()

    if args.command == "export":
        run_export(args)
    elif args.command == "compare":
        run_compare(args)
    elif args.command == "import":
        run_import(args)
    elif args.command == "validate":
        run_validate(args)
    elif args.command == "resources":
        run_resources(args)


if __name__ == "__main__":
    main()
