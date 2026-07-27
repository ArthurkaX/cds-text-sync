# -*- coding: utf-8 -*-
"""
ide_handlers_sync.py -- TEXT-SYNC command handlers for the CODESYS daemon.

Extracted from ide_reverse_pipe_loop.py.  Contains the sync domain handlers
(_cmd_sync_*), POU update/delete handlers, and their private ST helpers.
All public handlers are re-imported by ide_reverse_pipe_loop so the
handle_command dispatch table is unchanged.
"""

from __future__ import print_function

import json
import os
import tempfile
import time

import ide_runtime_common as _common

from ide_daemon_state import (
    _log,
    _get_active_project,
    _read_text_utf8,
)

from ide_daemon_helpers import (
    _active_app_online_state,
    _active_application_name,
    _find_object_by_selector,
    _find_object_in_project,
    _get_sync_folder,
    _invalidate_device_cache,
)

from ide_st_text import split_st_text


# ── Sync command handlers and private ST helpers ─────────────────────────────

def _cmd_sync_info():
    """Show sync folder and sync state information."""
    sync_dir, error = _get_sync_folder()
    result = {}
    if sync_dir:
        result["sync_folder"] = sync_dir
        result["dump_folder"] = os.path.join(sync_dir, ".dump")
        # Check if .dump exists
        dump_path = os.path.join(sync_dir, ".dump")
        if os.path.exists(dump_path):
            result["dump_exists"] = True
            try:
                items = os.listdir(dump_path)
                result["dump_items"] = len(items)
            except Exception:
                pass
        else:
            result["dump_exists"] = False
        # Check for _metadata.json
        meta_path = os.path.join(sync_dir, "_metadata.json")
        if os.path.exists(meta_path):
            result["metadata_exists"] = True
    else:
        result["error"] = error
    return {"ok": True, "data": result}


def _cmd_sync_export(params):
    """Export snapshot to sync folder / .dump.

    Args:
        --output PATH: custom output path (default: sync_folder/.dump/)
    """
    project, err = _get_active_project()
    if err:
        return err

    sync_dir, sf_err = _get_sync_folder()
    if sf_err and not params.get("output"):
        return {"ok": False, "error": sf_err}

    try:
        out_path = params.get("output", "")
        if not out_path:
            if sync_dir:
                dump_dir = os.path.join(sync_dir, ".dump")
                if not os.path.exists(dump_dir):
                    os.makedirs(dump_dir)
                out_path = os.path.join(
                    dump_dir, "snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S"))
                )
            else:
                out_path = os.path.join(
                    os.environ.get("TEMP", "C:\\Temp"),
                    "cds-snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S")),
                )

        # Same logic as _cmd_export but with sync folder awareness
        output_dir = os.path.dirname(out_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        objects = list(project.get_children(recursive=True))
        import tempfile as _tf

        fd, tmp_path = _tf.mkstemp(
            prefix="cds_export_", suffix=".xml", dir=output_dir or None
        )
        os.close(fd)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        try:
            project.export_native(objects, tmp_path, recursive=False)
            import shutil

            shutil.copy2(tmp_path, out_path)
            os.remove(tmp_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise
        size = os.path.getsize(out_path)
        _log("Exported snapshot: {0} ({1} bytes)".format(out_path, size))
        return {
            "ok": True,
            "data": {
                "path": out_path,
                "size": size,
                "sync_folder": sync_dir or "not set",
            },
        }
    except Exception as e:
        return {"ok": False, "error": "Sync export error: {0}".format(e)}


def _cmd_sync_import(params):
    """Import XML snapshot from .dump/ back into project.

    Args:
        --input PATH: specific XML file to import (default: latest from sync_folder/.dump/)
        --merge: merge instead of replace
    """
    project, err = _get_active_project()
    if err:
        return err

    in_path = params.get("input", "")
    if not in_path:
        sync_dir, sf_err = _get_sync_folder()
        if sf_err:
            return {"ok": False, "error": sf_err}
        dump_dir = os.path.join(sync_dir, ".dump")
        if not os.path.exists(dump_dir):
            return {"ok": False, "error": "No .dump directory at {0}".format(dump_dir)}
        xml_files = [
            f
            for f in os.listdir(dump_dir)
            if f.endswith(".xml") and f.startswith("snapshot-")
        ]
        if not xml_files:
            return {
                "ok": False,
                "error": "No snapshot XML files found in {0}".format(dump_dir),
            }
        xml_files.sort(reverse=True)
        in_path = os.path.join(dump_dir, xml_files[0])

    if not os.path.exists(in_path):
        return {"ok": False, "error": "File not found: {0}".format(in_path)}

    try:
        size = os.path.getsize(in_path)
        _log("Importing snapshot: {0} ({1} bytes)".format(in_path, size))

        # CODESYS API: project.import_native(path) — single arg only
        project.import_native(in_path)

        return {"ok": True, "data": {"path": in_path, "size": size}}
    except Exception as e:
        return {"ok": False, "error": "Sync import error: {0}".format(e)}


def _cmd_sync_compare(params):
    """Compare current project structure against .dump/ snapshot.

    Args:
        --against PATH: specific snapshot to compare against (default: latest from .dump/)
    """
    project, err = _get_active_project()
    if err:
        return err

    against = params.get("against", "")
    if not against:
        sync_dir, sf_err = _get_sync_folder()
        if sf_err:
            return {"ok": False, "error": sf_err}
        dump_dir = os.path.join(sync_dir, ".dump")
        if not os.path.exists(dump_dir):
            return {"ok": False, "error": "No .dump directory at {0}".format(dump_dir)}
        xml_files = [
            f
            for f in os.listdir(dump_dir)
            if f.endswith(".xml") and f.startswith("snapshot-")
        ]
        if not xml_files:
            return {
                "ok": False,
                "error": "No snapshot XML files found in {0}".format(dump_dir),
            }
        xml_files.sort(reverse=True)
        against = os.path.join(dump_dir, xml_files[0])

    if not os.path.exists(against):
        return {"ok": False, "error": "Snapshot not found: {0}".format(against)}

    try:
        # Compare by checking if import would cause changes:
        # 1. Get current project tree (list of tuples of object info)
        current_children = list(project.get_children(recursive=True))
        current_info = {}
        for child in current_children:
            try:
                name = str(getattr(child, "name", ""))
                typ = str(getattr(child, "type", ""))
                guid = str(getattr(child, "guid", ""))
                current_info[name] = {"name": name, "type": typ, "guid": guid}
            except Exception:
                pass

        # 2. Parse the XML and see what's different (basic check - just names)
        import xml.etree.ElementTree as ET

        tree = ET.parse(against)
        root = tree.getroot()

        xml_names = set()
        for elem in root.iter():
            name = elem.get("name", elem.get("Name", ""))
            if name:
                xml_names.add(name)

        current_names = set(current_info.keys())

        only_in_xml = xml_names - current_names
        only_in_project = current_names - xml_names

        # Build diff report
        diff = {
            "snapshot": against,
            "snapshot_size": os.path.getsize(against),
            "project_objects": len(current_children),
            "snapshot_objects": len(xml_names),
            "in_snapshot_only": sorted(only_in_xml)[:100],
            "in_project_only": sorted(only_in_project)[:100],
            "common_count": len(xml_names & current_names),
        }

        return {"ok": True, "data": diff}
    except Exception as e:
        return {"ok": False, "error": "Sync compare error: {0}".format(e)}


def _cmd_sync_export_text(params):
    # Step 1: Export XML
    export_result = _cmd_sync_export(params)
    if not export_result.get("ok"):
        return export_result

    out_path = export_result["data"]["path"]
    sync_folder = export_result["data"]["sync_folder"]

    # Step 1b: dirty preflight -- the daemon is headless, so locally-modified
    # view files are skipped by default (pending import) and unmanaged files
    # are kept (soft proposal) unless the caller opts in.
    overwrite_dirty = bool(params.get("overwrite_dirty"))
    remove_orphans = bool(params.get("remove_orphans"))
    pending_import = []
    removable_orphans = []
    manifest_path = os.path.join(sync_folder, ".dump", "manifest.json")
    if (not overwrite_dirty or not remove_orphans) and os.path.exists(manifest_path):
        dirty_report_path = os.path.join(sync_folder, ".dump", "dirty_report.json")
        check_args = [
            "check-dirty",
            "--project-root",
            sync_folder,
            "--report",
            dirty_report_path,
        ]
        if _common.run_external_engine(check_args):
            try:
                with open(dirty_report_path, "r") as handle:
                    report = json.load(handle)
                if not overwrite_dirty:
                    pending_import = [
                        item.get("path")
                        for item in (report.get("dirty") or [])
                        if item.get("path")
                    ]
                if not remove_orphans:
                    removable_orphans = [
                        item.get("path")
                        for item in (report.get("orphans") or [])
                        if item.get("path")
                    ]
            except Exception:
                pending_import = []
                removable_orphans = []

    # Step 2: Run engine_cli
    args = ["export", "--project-root", sync_folder, "--snapshot", out_path]
    args.append("--overwrite-dirty" if overwrite_dirty else "--skip-dirty")
    if remove_orphans:
        args.append("--remove-orphans")
    success = _common.run_external_engine(args)
    if not success:
        return {"ok": False, "error": "external engine export failed"}

    export_result["data"]["text_sync"] = "success"
    if pending_import:
        export_result["data"]["pending_import"] = pending_import
    if removable_orphans:
        export_result["data"]["removable_orphans"] = removable_orphans
    return export_result




def _cmd_sync_import_text(params):
    import xml.etree.ElementTree as ET

    # Preflight: creating/adding POU/GVL/DUT is an offline operation. If a live
    # online session is active the new objects silently won't be created, so
    # fail early with a clear instruction to disconnect first.
    online, state = _active_app_online_state()
    if online and not params.get("force_online"):
        return {
            "ok": False,
            "error": (
                "Active application is online (state: {0}). Adding/creating "
                "objects is an offline operation. Run disconnect_from_device "
                "first, then retry sync_import_text. "
                "(Pass force_online=true to override.)"
            ).format(state or "connected"),
        }

    # Step 1: Export current IDE state to use as baseline
    export_result = _cmd_sync_export(params)
    if not export_result.get("ok"):
        return export_result

    out_path = export_result["data"]["path"]
    sync_folder = export_result["data"]["sync_folder"]
    patch_path = os.path.join(sync_folder, ".dump", "IMPORT.xml")

    # Step 2: Run engine_cli import to generate IMPORT.xml
    args = [
        "import",
        "--project-root",
        sync_folder,
        "--snapshot",
        out_path,
        "--patch",
        patch_path,
    ]
    success = _common.run_external_engine(args)
    if not success:
        return {"ok": False, "error": "external engine import failed"}

    if not os.path.exists(patch_path):
        return {"ok": False, "error": "IMPORT.xml was not generated"}

    compare_report_path = os.path.join(
        sync_folder, ".dump", "import_compare_report.json"
    )
    compare_args = [
        "compare",
        "--project-root",
        sync_folder,
        "--snapshot",
        out_path,
        "--report",
        compare_report_path,
        "--include-objects",
    ]
    _common.run_external_engine(compare_args)

    # Step 3: Parse IMPORT.xml and process CreateTextObjects
    project, p_err = _get_active_project()
    if p_err:
        return p_err

    try:
        tree = ET.parse(patch_path)
        root = tree.getroot()

        # Find and process CreateTextObjects
        text_creates = []
        for creates_elem in root.iter():
            local_tag = str(creates_elem.tag).rsplit("}", 1)[-1]
            if local_tag == "CreateTextObjects":
                for create_elem in list(creates_elem):
                    local_tag2 = str(create_elem.tag).rsplit("}", 1)[-1]
                    if local_tag2 == "CreateTextObject":
                        path = create_elem.attrib.get("Path", "")
                        name = create_elem.attrib.get("Name", "")
                        kind = create_elem.attrib.get("Kind", "")
                        type_guid = create_elem.attrib.get("TypeGuid", "")
                        parent_name = create_elem.attrib.get("ParentName", "")

                        # Read declaration/implementation from .st file
                        st_path = _find_st_file(sync_folder, path)
                        decl = ""
                        impl = ""
                        if st_path and os.path.exists(st_path):
                            content = _read_text_utf8(st_path)
                            decl, impl = _split_st_content(content)

                        text_creates.append(
                            {
                                "path": path,
                                "name": name,
                                "kind": kind,
                                "type_guid": type_guid,
                                "parent_name": parent_name,
                                "declaration": decl,
                                "implementation": impl,
                                "source_path": st_path,
                            }
                        )

        if text_creates:
            _log("Creating {0} new text objects...".format(len(text_creates)))
            created = {}
            for entry in text_creates:
                try:
                    _apply_text_create_entry(project, entry, created)
                except Exception as e:
                    _log("Failed to create {0}: {1}".format(entry["name"], str(e)))
            _log(
                "Created text objects: {0}".format(
                    ", ".join(e["name"] for e in text_creates)
                )
            )

        # Step 3b: Process CreateNativeObject entries (visualizations, image
        # pools, and other native objects). Unlike text objects, these carry a
        # full IArchivable payload that must be imported into their container.
        # The create+verify logic already exists in ide_apply_patch; reuse it so
        # this handler and apply_patch stay consistent.
        import ide_apply_patch as _iap

        native_creates = _iap._native_create_entries(root)
        created_native = []
        failed_native = []
        if native_creates:
            _log("Creating {0} new native objects...".format(len(native_creates)))
            for entry in native_creates:
                try:
                    _iap._apply_native_create(project, entry)
                    created_native.append(entry.get("name"))
                except Exception as e:
                    # One bad object (e.g. a stale name/GUID that already exists
                    # in another folder) must not abort the whole import; record
                    # it and keep going so the remaining objects still apply.
                    _log(
                        "Failed to create native {0}: {1}".format(
                            entry.get("name"), str(e)
                        )
                    )
                    failed_native.append(
                        {
                            "name": entry.get("name"),
                            "path": entry.get("path"),
                            "error": str(e),
                        }
                    )
            if created_native:
                _log("Created native objects: {0}".format(", ".join(created_native)))
            if failed_native:
                _log(
                    "Native objects that failed (import continued): {0}".format(
                        ", ".join(f["name"] for f in failed_native)
                    )
                )

        updated_text = []
        skipped_projection_objects = []
        if os.path.exists(compare_report_path):
            updated_text = _apply_modified_st_objects(project, compare_report_path)
            if updated_text:
                _log("Updated text objects: {0}".format(", ".join(updated_text)))
            # Detect modified objects whose projection changes could not be
            # applied automatically (e.g. non-ST projections).
            try:
                import json as _json

                _report = _json.loads(_read_text_utf8(compare_report_path))
                _updated_names = set(updated_text)
                for obj in (_report.get("objects") or {}).get("modified") or []:
                    _name = obj.get("name") or obj.get("guid") or "?"
                    if _name in _updated_names:
                        continue
                    _pd = obj.get("projection_diff") or {}
                    if _pd.get("format") and _pd.get("disk_content") is not None:
                        _fmt = str(_pd.get("format") or "")
                        if _fmt.lower() == "st":
                            _reason = (
                                "projection change not applied automatically; "
                                "use update-pou or edit in the IDE"
                            )
                        else:
                            # update-pou only understands .st — do not send the
                            # user to a command that cannot help them.
                            _reason = (
                                "'{0}' projections cannot be applied "
                                "automatically; edit the object in the "
                                "IDE".format(_fmt)
                            )
                        skipped_projection_objects.append(
                            {
                                "name": _name,
                                "path": obj.get("path", ""),
                                "format": _pd.get("format", ""),
                                "reason": _reason,
                            }
                        )
            except Exception:
                pass

        # Step 4: Apply StructuredView (MAIN update) — skip if fails, objects are already created
        try:
            filtered_root = _strip_text_creates(root)
            if filtered_root is not None:
                handle, filtered_path = tempfile.mkstemp(suffix=".xml")
                os.close(handle)
                tree2 = ET.ElementTree(filtered_root)
                tree2.write(filtered_path, encoding="utf-8", xml_declaration=True)
                project.import_native(filtered_path)
                try:
                    os.remove(filtered_path)
                except Exception:
                    pass
        except Exception as e:
            import traceback

            _log(
                "StructuredView import skipped: {0}\n{1}".format(
                    e, traceback.format_exc()
                )
            )

        return_data = {
            "path": patch_path,
            "size": os.path.getsize(patch_path),
            "created_text_objects": [e["name"] for e in text_creates],
            "created_native_objects": created_native,
            "updated_text_objects": updated_text,
            "skipped_projection_objects": skipped_projection_objects,
            "failed_native_objects": failed_native,
        }
        if (
            not text_creates
            and not created_native
            and not updated_text
            and not skipped_projection_objects
            and not failed_native
        ):
            return_data["note"] = (
                "No objects were created, updated, or skipped. "
                "The compare report may show projection-only changes that "
                "cannot be applied automatically; use update-pou or edit "
                "the object in the IDE."
            )

        _invalidate_device_cache()

        return {
            "ok": True,
            "data": return_data,
        }
    except Exception as e:
        return {"ok": False, "error": "Sync import error: {0}".format(e)}


def _split_st_update_content(content):
    """Split a modified .st file into (declaration, implementation).

    See ide_st_text.split_st_text for the rules; update and creation must not
    diverge, so both go through it.
    """
    return split_st_text(content)


def _replace_text_document(doc, text):
    if doc is None:
        return False
    if hasattr(doc, "text"):
        try:
            doc.text = text
            return True
        except Exception:
            pass
    if hasattr(doc, "replace"):
        doc.replace(text)
        return True
    return False


def _text_section(target, attribute_name):
    """Return target.<attribute_name>, or None if it is absent or unreadable."""
    try:
        return getattr(target, attribute_name, None)
    except Exception:
        return None


def _route_sections_for_target(target, decl, impl):
    """Re-route a marker-less body onto the section the object actually has.

    .st files exported before ACTIONs carried a header are a bare implementation
    body with no marker, so the splitter classifies them as a declaration. When
    the object exposes no declaration but does expose an implementation, the
    text can only be the implementation — routing by what the object has keeps
    those legacy files working without a re-export.

    Declaration-only kinds (GVL, DUT) do expose textual_declaration, so they are
    never re-routed; that would write their declaration nowhere.
    """
    if decl and not impl:
        if (
            _text_section(target, "textual_declaration") is None
            and _text_section(target, "textual_implementation") is not None
        ):
            return "", decl
    return decl, impl


def _apply_text_to_object(target, decl, impl):
    decl_ok = True
    impl_ok = True
    if decl:
        decl_ok = False
        try:
            decl_ok = _replace_text_document(target.textual_declaration, decl)
        except Exception as e:
            _log("Warning: could not set declaration: {0}".format(e))
    if impl:
        impl_ok = False
        try:
            impl_ok = _replace_text_document(target.textual_implementation, impl)
        except Exception as e:
            _log("Warning: could not set implementation: {0}".format(e))
    return decl_ok, impl_ok


def _apply_modified_st_objects(project, report_path):
    try:
        report = json.loads(_read_text_utf8(report_path))
    except Exception as e:
        _log("Could not read import compare report: {0}".format(e))
        return []

    updated = []
    for obj in (report.get("objects") or {}).get("modified") or []:
        projection_diff = obj.get("projection_diff") or {}
        if str(projection_diff.get("format", "")).lower() != "st":
            continue
        disk_content = projection_diff.get("disk_content")
        if disk_content is None:
            continue
        target = _find_object_by_selector(
            project,
            {
                "guid": obj.get("guid", ""),
                "path": obj.get("path", ""),
                "name": obj.get("name", ""),
            },
        )
        if target is None:
            _log(
                "Could not find modified text object: {0}".format(
                    obj.get("name") or obj.get("guid")
                )
            )
            continue
        decl, impl = _split_st_update_content(disk_content)
        if not decl and not impl:
            # Nothing to write. Reporting this as "updated" would claim an IDE
            # change that never happened, so leave it out of the result.
            _log(
                "Skipped empty .st projection for {0}".format(
                    obj.get("name") or obj.get("guid")
                )
            )
            continue
        decl, impl = _route_sections_for_target(target, decl, impl)
        decl_ok, impl_ok = _apply_text_to_object(target, decl, impl)
        if decl_ok and impl_ok:
            updated.append(obj.get("name") or obj.get("guid") or "?")
        else:
            _log(
                "Text update incomplete for {0}: decl={1}, impl={2}".format(
                    obj.get("name") or obj.get("guid"), decl_ok, impl_ok
                )
            )
    return updated


def _find_st_file(sync_folder, rel_path):
    """Find the .st source file for a CreateTextObject entry."""
    try:
        views_path = _common.layout(sync_folder).view_root
    except Exception:
        views_path = os.path.join(sync_folder, "project-view")
    candidate = os.path.join(views_path, rel_path)
    if os.path.exists(candidate):
        return candidate
    # Try alternate paths
    base = os.path.basename(rel_path)
    for root, dirs, files in os.walk(views_path):
        if base in files:
            return os.path.join(root, base)
    return None


def _split_st_content(content):
    """Split .st content into declaration and implementation.

    Strips END_FUNCTION_BLOCK / END_FUNCTION / END_PROGRAM from implementation
    as CODESYS API auto-adds these.
    """
    return split_st_text(content, strip_pou_end=True)


def _strip_text_creates(root):
    """Remove create-only wrappers (CreateTextObjects / CreateNativeObjects)
    from the XML root.

    These are applied separately (text via _apply_text_create_entry, native via
    ide_apply_patch._apply_native_create) and must not be fed to the Step 4
    project.import_native pass: import_native ignores the CreateNativeObjects
    wrapper anyway, but stripping it keeps the StructuredView payload clean and
    avoids any double processing."""
    import copy

    filtered = copy.deepcopy(root)
    for child in list(filtered):
        local_tag = str(child.tag).rsplit("}", 1)[-1]
        if local_tag in ("CreateTextObjects", "CreateNativeObjects"):
            filtered.remove(child)
    if len(list(filtered)) == 0:
        return None
    return filtered


def _apply_text_create_entry(project, entry, created_by_name):
    """Create a single text object (POU, GVL, DUT) from a CreateTextObject entry."""
    import ide_apply_patch as _iap

    # Add source_path to entry for ide_apply_patch compatibility
    rel_path = entry["path"]
    container, container_chain = _iap._ensure_container_path_with_chain(
        project, rel_path
    )
    if container is None:
        raise Exception("Could not resolve container for {0}".format(rel_path))

    parent_name = entry.get("parent_name", "")
    if parent_name:
        parent = created_by_name.get(str(parent_name).lower())
        if parent is None:
            parent = _iap._find_child_transparent(container, parent_name)
        if parent is None:
            raise Exception(
                "Could not resolve parent POU '{0}' for {1}".format(
                    parent_name, rel_path
                )
            )
        container = parent

    obj_name = entry["name"]
    existing = _iap._find_child_transparent(container, obj_name)
    if existing is not None:
        obj = existing
    else:
        obj = _iap._create_text_object(
            container, entry, container_chain=container_chain
        )

    if obj is None:
        raise Exception(
            "CODESYS did not return created object for {0}".format(rel_path)
        )

    _iap._apply_textual_patch(obj, entry)
    created_by_name[_iap.object_name(obj).lower()] = obj
    _log("Created textual object: {0}".format(rel_path))


def _cmd_sync_compare_text(params):
    # Step 1: Export current IDE state
    export_result = _cmd_sync_export(params)
    if not export_result.get("ok"):
        return export_result

    out_path = export_result["data"]["path"]
    sync_folder = export_result["data"]["sync_folder"]
    report_path = os.path.join(sync_folder, ".dump", "compare_report.json")

    # Step 2: Run engine_cli compare
    args = [
        "compare",
        "--project-root",
        sync_folder,
        "--snapshot",
        out_path,
        "--report",
        report_path,
        "--include-objects",
    ]
    success = _common.run_external_engine(args)
    if not success:
        return {"ok": False, "error": "external engine compare failed"}

    if not os.path.exists(report_path):
        return {"ok": False, "error": "compare_report.json was not generated"}

    # Step 3: Read and return report
    try:
        report_data = json.loads(_read_text_utf8(report_path))
        return {"ok": True, "data": report_data}
    except Exception as e:
        return {"ok": False, "error": "failed to read report: " + str(e)}


def _cmd_update_pou(params):
    """Update a POU's textual declaration and implementation from a .st file.

    Args:
        name: POU name (e.g. "MAIN")
        app: Application name (e.g. "Application (from profile)")
        st_path: path to .st file (absolute or relative to project-view)
    """
    project, err = _get_active_project()
    if err:
        return err

    pou_name = params.get("name", "")
    app_name = params.get("app") or _active_application_name(project)
    st_path = params.get("st_path", "")

    if not pou_name or not st_path:
        return {"ok": False, "error": "name and st_path are required"}

    # Resolve st_path
    if not os.path.isabs(st_path):
        sf, sf_err = _get_sync_folder()
        if sf_err or not sf:
            return {
                "ok": False,
                "error": "Cannot resolve sync folder: {0}".format(sf_err or "unknown"),
            }
        st_path = os.path.join(sf, "project-view", st_path)

    if not os.path.exists(st_path):
        return {"ok": False, "error": "File not found: {0}".format(st_path)}

    # Read .st file
    content = _read_text_utf8(st_path)

    # Split into declaration and implementation
    decl, impl = split_st_text(content)

    # Find the POU object in the project tree
    target, _target_type = _find_object_in_project(project, pou_name, app_name)

    if target is None:
        scope = app_name or "project"
        return {
            "ok": False,
            "error": "POU '{0}' not found in application '{1}'".format(pou_name, scope),
        }

    # Update declaration
    decl, impl = _route_sections_for_target(target, decl, impl)
    decl_ok = False
    impl_ok = False
    decl_skipped = None
    impl_skipped = None
    if decl:
        try:
            dd = target.textual_declaration
            if dd is not None:
                if hasattr(dd, "text"):
                    try:
                        dd.text = decl
                        decl_ok = True
                    except Exception:
                        dd.replace(decl)
                        decl_ok = True
                elif hasattr(dd, "replace"):
                    dd.replace(decl)
                    decl_ok = True
            else:
                _log("Warning: textual_declaration not available")
        except Exception as e:
            _log("Warning: could not set declaration: {0}".format(e))
    else:
        # Nothing to apply is success, not a failure.
        decl_ok = True
        decl_skipped = "no declaration text in .st"

    # Update implementation
    if impl:
        try:
            di = target.textual_implementation
            if di is not None:
                if hasattr(di, "text"):
                    try:
                        di.text = impl
                        impl_ok = True
                    except Exception:
                        di.replace(impl)
                        impl_ok = True
                elif hasattr(di, "replace"):
                    di.replace(impl)
                    impl_ok = True
            else:
                # Object has no implementation member (GVL/DUT/interface). The
                # .st carries implementation text but it cannot be applied.
                impl_skipped = "object has no implementation section"
                _log("Warning: textual_implementation not available")
        except Exception as e:
            _log("Warning: could not set implementation: {0}".format(e))
    else:
        # No implementation in the .st (e.g. GVL/DUT/interface). Nothing to
        # apply -> success with a note, instead of a scary impl_ok:false.
        impl_ok = True
        impl_skipped = "no implementation section in .st"

    _log(
        "Updated POU: {0} (app={1}, decl={2}, impl={3})".format(
            pou_name, app_name, decl_ok, impl_ok
        )
    )
    result = {
        "ok": True,
        "data": {
            "name": pou_name,
            "app": app_name,
            "decl_ok": decl_ok,
            "impl_ok": impl_ok,
            "decl_len": len(decl),
            "impl_len": len(impl),
        },
    }
    if decl_skipped:
        result["data"]["decl_skipped"] = decl_skipped
    if impl_skipped:
        result["data"]["impl_skipped"] = impl_skipped
    return result


def _cmd_delete_pou(params):
    """Delete an object from the project (POU, GVL, DUT, etc).

    Args:
        name: Object name (e.g. "MAIN", "Globals", "MyDataType")
        app: Optional application name. Defaults to the active application.
    """
    project, err = _get_active_project()
    if err:
        return err

    obj_name = params.get("name", "")
    app_name = params.get("app") or _active_application_name(project)

    if not obj_name:
        return {"ok": False, "error": "name is required"}

    # Find the object in the project tree
    target, target_type = _find_object_in_project(project, obj_name, app_name)

    if target is None:
        scope = app_name or "project"
        return {
            "ok": False,
            "error": "Object '{0}' not found in application '{1}'".format(
                obj_name, scope
            ),
        }

    # Try to delete the object using remove() method
    try:
        if hasattr(target, "remove"):
            target.remove()
            _invalidate_device_cache()
            _log(
                "Deleted object: {0} (type={1}, app={2})".format(
                    obj_name, target_type, app_name
                )
            )
            return {
                "ok": True,
                "data": {
                    "name": obj_name,
                    "type": target_type,
                    "deleted": True,
                    "note": "Object deleted successfully",
                },
            }
        else:
            msg = "Object type '{0}' does not support remove() method".format(
                target_type
            )
            _log("Error: {0}".format(msg))
            return {"ok": False, "error": msg}
    except Exception as e:
        msg = "Failed to delete '{0}': {1}".format(obj_name, str(e))
        _log("Error deleting object: {0}".format(e))
        return {"ok": False, "error": msg}

