# -*- coding: utf-8 -*-
"""
ide_handlers_build.py -- BUILD/EXPORT command handlers for ide_reverse_pipe_loop.py.

Contains handlers for project export, build, CSV/ST export, and application tree.
All CODESYS API calls happen via sys._codesys_daemon_loop (set by capture_codesys_globals).
"""
from __future__ import print_function

import json
import os
import sys
import time

from ide_daemon_state import (
    _log,
    _get_active_project,
    _obj_name,
)

from ide_daemon_helpers import (
    _get_sync_folder,
)


def _cmd_export(params):
    project, err = _get_active_project()
    if err:
        return err
    out_path = params.get("output", "")
    if not out_path:
        out_path = os.path.join(
            os.environ.get("TEMP", "C:\\Temp"),
            "cds-snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S")),
        )
    try:
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
            from ide_online_helpers import atomic_write

            with open(tmp_path, "rb") as f:
                content = f.read()
            atomic_write(out_path, content)
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
        return {"ok": True, "data": {"path": out_path, "size": size}}
    except Exception as e:
        return {"ok": False, "error": "Export error: {0}".format(e)}


def _cmd_build(params):
    """Build the active application using app.build().

    Collects build messages via system.get_messages().
    Supports --output PATH and --stdout flags.
    """
    project, err = _get_active_project()
    if err:
        return err
    try:
        import time
        import traceback

        # Get system from daemon state
        daemon_state = getattr(sys, "_codesys_daemon_loop", {})
        system_obj = daemon_state.get("system")
        if system_obj is None:
            return {
                "ok": False,
                "error": "System object not available in daemon state.",
            }

        # Find the active application (not the project)
        from System import Guid

        BUILD_CATEGORY_GUID = "97F48D64-A2A3-4856-B640-75C046E37EA9"

        app = None
        try:
            app = project.active_application
        except Exception:
            pass
        if app is None:
            for child in project.get_children(True):
                if hasattr(child, "is_application"):
                    try:
                        if child.is_application:
                            app = child
                            break
                    except Exception:
                        pass
        if app is None:
            return {"ok": False, "error": "No active application found to build."}

        app_name = "?"
        try:
            app_name = app.get_name()
        except Exception:
            pass

        # Clear build messages before build
        try:
            category_guid = Guid(BUILD_CATEGORY_GUID)
            system_obj.clear_messages(category_guid)
        except Exception:
            try:
                system_obj.clear_messages(BUILD_CATEGORY_GUID)
            except Exception:
                pass

        # Build
        start = time.time()
        try:
            app.build()
        except Exception as e:
            return {"ok": False, "error": "Build exception: {0}".format(e)}
        elapsed = time.time() - start

        # Collect messages
        messages = []
        error_count = 0
        warning_count = 0
        try:
            msg_objects = system_obj.get_message_objects(BUILD_CATEGORY_GUID)
            for msg in msg_objects:
                try:
                    msg_text = str(getattr(msg, "text", ""))
                    if "Build started" in msg_text or "Compile complete" in msg_text:
                        continue
                    severity = str(getattr(msg, "severity", ""))
                    if "Error" in severity:
                        error_count += 1
                    if "Warning" in severity:
                        warning_count += 1
                    obj_ref = None
                    obj_name = ""
                    try:
                        obj_ref = getattr(msg, "object", None)
                        if obj_ref:
                            obj_name = str(obj_ref.get_name())
                    except Exception:
                        pass
                    msg_id = ""
                    try:
                        prefix = str(getattr(msg, "prefix", ""))
                        number = int(getattr(msg, "number", 0))
                        if number > 0:
                            msg_id = "{0}{1:04d}".format(prefix, number)
                        else:
                            msg_id = prefix
                    except Exception:
                        pass
                    messages.append(
                        {
                            "severity": severity,
                            "code": msg_id,
                            "text": msg_text,
                            "object": obj_name,
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass

        result = {
            "ok": error_count == 0,
            "data": {
                "application": app_name,
                "errors": error_count,
                "warnings": warning_count,
                "elapsed_seconds": round(elapsed, 3),
                "messages": messages,
            },
        }

        # Write output file if requested
        output_path = params.get("output") if isinstance(params, dict) else None
        if output_path:
            try:
                with open(output_path, "wb") as f:
                    f.write(
                        json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")
                    )
                result["data"]["output_file"] = output_path
            except Exception as e:
                result["data"]["output_error"] = str(e)

        return result
    except Exception as e:
        _log("Build error: {0}\n{1}".format(e, traceback.format_exc()))
        return {"ok": False, "error": "Build error: {0}".format(e)}


def _cmd_export_csv(params):
    """Export PLC variable tree as CSV.

    Args:
        --output PATH: save CSV to file (default: return as text)
        --values: include current values (requires connection)
        --pattern FILTER: filter by name
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        read_values = str(params.get("values", "")).lower() in ("1", "true", "yes")
        pattern = params.get("pattern", "").lower()
        output_path = params.get("output", "")

        app_obj = getattr(oa, "application", None)
        if app_obj is None:
            return {"ok": False, "error": "oa.application not available"}

        _seen = set()
        rows = []

        def _walk(obj, prefix="", depth=0):
            if depth > 20:
                return
            name = _obj_name(obj)
            if not name:
                return
            full_path = prefix + "." + name if prefix else name
            obj_id = id(obj)
            if obj_id in _seen:
                return
            _seen.add(obj_id)

            val_str = ""
            if read_values:
                for candidate in [full_path, "Application." + full_path]:
                    try:
                        val = oa.read_value(candidate)
                        if val is not None:
                            sv = str(val)
                            if (
                                "Invalid expression" not in sv
                                and "invalid expression" not in sv.lower()
                            ):
                                val_str = sv
                                break
                    except Exception:
                        pass

            if not pattern or pattern in full_path.lower() or pattern in name.lower():
                rows.append((full_path, val_str))

            try:
                for child in list(obj.get_children()):
                    _walk(child, full_path, depth + 1)
            except Exception:
                pass

        _walk(app_obj)

        # Build CSV content
        # Build CSV content without StringIO
        lines = []
        lines.append("Path,Value")
        for path, val in rows:
            path_esc = (
                '"' + path.replace('"', '""') + '"'
                if "," in path or '"' in path
                else path
            )
            val_esc = (
                '"' + val.replace('"', '""') + '"' if "," in val or '"' in val else val
            )
            lines.append(path_esc + "," + val_esc)
        csv_text = "\r\n".join(lines) + "\r\n"

        if output_path:
            out_dir = os.path.dirname(output_path)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir)
            with open(output_path, "wb") as f:
                f.write(csv_text.encode("utf-8"))
            return {
                "ok": True,
                "data": {"path": output_path, "rows": len(rows), "saved": True},
            }
        else:
            return {"ok": True, "data": {"csv": csv_text, "rows": len(rows)}}
    except Exception as e:
        return {"ok": False, "error": "Export CSV error: {0}".format(e)}


def _cmd_export_st(params):
    """Export project POUs as .st source files.

    Walks the project tree looking for POU-like objects
    (Program, FunctionBlock, Function, GVL, DUT) and
    exports their source code to .st files.

    Args:
        --output DIR: destination directory (default: .dump/st/)
    """
    project, err = _get_active_project()
    if err:
        return err

    try:
        # Determine output directory
        out_dir = params.get("output", "")
        if not out_dir:
            sync_dir, _ = _get_sync_folder()
            if sync_dir:
                out_dir = os.path.join(sync_dir, ".dump", "st")
            else:
                out_dir = os.path.join(
                    os.environ.get("TEMP", "C:\\Temp"), "cds-st-export"
                )
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        exported = []
        errors = []

        def _walk_export(obj, folder=""):
            """Recursively walk project and export POU-like objects."""
            name = _obj_name(obj)
            if not name:
                return

            # Check if this is a POU-like object (has code to export)
            obj_type = str(type(obj).__name__)
            is_pou = False
            for t in [
                "Program",
                "FunctionBlock",
                "Function",
                "Gvl",
                "Dut",
                "POU",
                "IecTask",
                "Action",
                "Method",
                "Property",
                "GlobalVariableList",
                "IoConfig",
                "Device",
            ]:
                if t.lower() in obj_type.lower():
                    is_pou = True
                    break

            if is_pou:
                # Try to export via export_native on just this object
                safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
                subfolder = folder
                if subfolder:
                    obj_dir = os.path.join(out_dir, subfolder)
                else:
                    obj_dir = out_dir
                if not os.path.exists(obj_dir):
                    os.makedirs(obj_dir)

                st_path = os.path.join(obj_dir, safe_name + ".st")
                xml_path = os.path.join(obj_dir, safe_name + ".xml")

                try:
                    # Try save to file first (some objects support this)
                    if hasattr(obj, "save"):
                        obj.save(st_path)
                        if os.path.exists(st_path):
                            size = os.path.getsize(st_path)
                            exported.append(
                                {
                                    "name": name,
                                    "path": st_path,
                                    "size": size,
                                    "type": obj_type,
                                }
                            )
                            return

                    if hasattr(obj, "export_native"):
                        obj.export_native(st_path)
                        if os.path.exists(st_path):
                            size = os.path.getsize(st_path)
                            exported.append(
                                {
                                    "name": name,
                                    "path": st_path,
                                    "size": size,
                                    "type": obj_type,
                                }
                            )
                            return

                    # Fallback: use project.export_native with just this object
                    if hasattr(project, "export_native"):
                        project.export_native([obj], xml_path, recursive=False)
                        if os.path.exists(xml_path):
                            size = os.path.getsize(xml_path)
                            exported.append(
                                {
                                    "name": name,
                                    "path": xml_path,
                                    "size": size,
                                    "type": obj_type + " (xml)",
                                }
                            )
                            return

                    errors.append(
                        "No export method for: {0} ({1})".format(name, obj_type)
                    )
                except Exception as e:
                    errors.append(
                        "Export failed for {0}: {1}".format(name, str(e)[:100])
                    )

            # Recurse into children
            try:
                for child in list(obj.get_children()):
                    child_name = _obj_name(child) or ""
                    child_folder = folder + "/" + child_name if folder else child_name
                    _walk_export(child, child_folder)
            except Exception:
                pass

        _walk_export(project)

        return {
            "ok": True,
            "data": {
                "output_directory": out_dir,
                "exported_count": len(exported),
                "exported": exported[:50],  # first 50
                "error_count": len(errors),
                "errors": errors[:20],  # first 20 errors
            },
        }
    except Exception as e:
        return {"ok": False, "error": "Export ST error: {0}".format(e)}


def _cmd_application_tree(params):
    """Build the application OBJECT tree by walking Application children.

    Walks oa.application.get_children(), builds object paths, and optionally
    reads current values. For declared PLC variables use the variable-map /
    variable-snapshot tools instead.

    Args:
        params:
            --depth N: max recursion depth (default 10)
            --pattern FILTER: filter by name/path substring
            --values: try to read current values
            --flat: return flat list instead of tree
            --output PATH: write JSON to file (recommended for large projects)
    """
    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    try:
        read_values = str(params.get("values", "")).lower() in ("1", "true", "yes")
        pattern = params.get("pattern", "").lower()
        is_flat = str(params.get("flat", "")).lower() in ("1", "true", "yes")
        output_path = params.get("output", "")
        max_depth = 10
        try:
            max_depth = int(params.get("depth", 10))
        except (ValueError, TypeError):
            pass

        app_obj = getattr(oa, "application", None)
        if app_obj is None:
            return {"ok": False, "error": "oa.application not available"}

        _seen = set()

        def _walk(obj, prefix="", depth=0):
            """Recursively walk application children, building path."""
            if depth > max_depth:
                return None

            name = _obj_name(obj)
            if not name:
                return None

            # Build full path
            full_path = prefix + "." + name if prefix else name

            # Dedup
            obj_id = id(obj)
            if obj_id in _seen:
                return None
            _seen.add(obj_id)

            node = {"name": name, "path": full_path}

            # Try to read value
            if read_values:
                for candidate in [full_path, "Application." + full_path]:
                    try:
                        val = oa.read_value(candidate)
                        if val is not None:
                            str_val = str(val)
                            if (
                                "Invalid expression" in str_val
                                or "invalid expression" in str_val.lower()
                            ):
                                node["value_error"] = (
                                    "Invalid expression (not exported to online)"
                                )
                            else:
                                node["value"] = str_val
                            break
                    except Exception:
                        pass

            try:
                children = list(obj.get_children())
                if children:
                    child_list = []
                    for child in children:
                        child_node = _walk(child, full_path, depth + 1)
                        if child_node is not None:
                            child_list.append(child_node)
                    if child_list:
                        node["children"] = child_list
            except Exception:
                pass

            return node

        tree = _walk(app_obj)
        if tree is None:
            return {"ok": False, "error": "Empty variable tree"}

        if is_flat:
            # Flatten tree to list
            def _flatten(node, result=None):
                if result is None:
                    result = []
                entry = {"name": node["name"], "path": node["path"]}
                if "value" in node:
                    entry["value"] = node["value"]
                if pattern:
                    if (
                        pattern in node["path"].lower()
                        or pattern in node["name"].lower()
                    ):
                        result.append(entry)
                else:
                    result.append(entry)
                for child in node.get("children", []):
                    _flatten(child, result)
                return result

            flat_list = _flatten(tree)

            if output_path:
                # Write full JSON to file, return summary via pipe
                import json as _json

                export = {
                    "count": len(flat_list),
                    "variables": flat_list,
                    "mode": "flat",
                }
                try:
                    dir_name = os.path.dirname(output_path)
                    if dir_name and not os.path.exists(dir_name):
                        os.makedirs(dir_name)
                    with open(output_path, "wb") as f:
                        f.write(
                            _json.dumps(export, indent=2, ensure_ascii=False).encode(
                                "utf-8"
                            )
                        )
                    return {
                        "ok": True,
                        "data": {
                            "count": len(flat_list),
                            "output": output_path,
                            "mode": "flat",
                            "note": "Full list written to file. Use --pattern to search.",
                        },
                    }
                except Exception as e:
                    return {
                        "ok": False,
                        "error": "Write output file error: {0}".format(e),
                    }

            return {
                "ok": True,
                "data": {
                    "count": len(flat_list),
                    "variables": flat_list,
                    "mode": "flat",
                },
            }

        else:
            # Tree mode: filter if pattern given
            def _filter_tree(node):
                """Keep only nodes matching pattern."""
                children = node.get("children", [])
                filtered_children = []
                for child in children:
                    fc = _filter_tree(child)
                    if fc is not None:
                        filtered_children.append(fc)
                name_match = (
                    not pattern
                    or pattern in node["name"].lower()
                    or pattern in node.get("path", "").lower()
                )
                if name_match or filtered_children:
                    result = {"name": node["name"], "path": node["path"]}
                    if "value" in node:
                        result["value"] = node["value"]
                    if filtered_children:
                        result["children"] = filtered_children
                    return result
                return None

            filtered = _filter_tree(tree) if pattern else tree
            if filtered is None:
                return {
                    "ok": True,
                    "data": {"mode": "tree", "note": "No matches for pattern"},
                }

            if output_path:
                import json as _json

                export = filtered
                export["mode"] = "tree"
                try:
                    dir_name = os.path.dirname(output_path)
                    if dir_name and not os.path.exists(dir_name):
                        os.makedirs(dir_name)
                    with open(output_path, "wb") as f:
                        f.write(
                            _json.dumps(export, indent=2, ensure_ascii=False).encode(
                                "utf-8"
                            )
                        )
                    return {
                        "ok": True,
                        "data": {
                            "output": output_path,
                            "mode": "tree",
                            "note": "Variable tree written to file.",
                        },
                    }
                except Exception as e:
                    return {
                        "ok": False,
                        "error": "Write output file error: {0}".format(e),
                    }

            return {"ok": True, "data": filtered}

    except Exception as e:
        return {"ok": False, "error": "Variable tree error: {0}".format(e)}
