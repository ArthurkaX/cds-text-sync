# -*- coding: utf-8 -*-
"""
ide_handlers_project.py — Project / Device / Diagnostics command handlers.

Extracted from ide_reverse_pipe_loop.py.  All handlers here are re-imported
back into that module so handle_command's if/elif dispatch is unchanged.
"""

from __future__ import print_function

import os
import sys
import traceback

import ide_online_helpers as _helpers
import ide_runtime_common as _common  # noqa: F401 – imported for completeness; bodies may use _common

from ide_daemon_state import (
    _log,
    _get_active_project,
    _require_param,
    _obj_name,
    _build_path,
    _read_online_attr,
    _bool_or_none,
    _get_plc_status_snapshot,
    _project_file_path,
)

from ide_daemon_helpers import (
    _get_project_info_object,
    _project_info_summary,
    _project_info_properties,
    _invalidate_device_cache,
    _find_object_by_selector,
    _ensure_online_app,
    _build_tree,
    _read_text_member,
)


# ── Handlers ──────────────────────────────────────────────────────────────────


def _cmd_project_info():
    project, err = _get_active_project()
    if err:
        return err
    try:
        info = {
            "name": _obj_name(project),
            "captured_at": sys._codesys_daemon_loop.get("started_at", ""),
            "daemon_pid": os.getpid(),
            "mode": "reverse_pipe",
        }
        filename = _project_file_path(project)
        if filename:
            info["filename"] = filename
        try:
            children = project.get_children(recursive=True)
            info["object_count"] = len(list(children))
        except Exception:
            info["object_count"] = -1
        # Read Project Information dialog data: Summary tab + Properties tab.
        try:
            proj_info = _get_project_info_object(project)
            if proj_info is not None:
                summary = _project_info_summary(proj_info)
                properties = _project_info_properties(proj_info)
                info["summary"] = summary
                info["properties"] = properties
                sf = properties.get("cds-sync-folder", "")
                if sf:
                    info["sync_folder"] = str(sf)
        except Exception:
            pass
        return {"ok": True, "data": info}
    except Exception as e:
        return {"ok": False, "error": "Project info error: {0}".format(e)}


def _cmd_project_tree(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        depth = params.get("depth", 0)
        tree = _build_tree(project, depth=depth, current_depth=0)
        return {"ok": True, "data": tree}
    except Exception as e:
        return {"ok": False, "error": "Project tree error: {0}".format(e)}


def _cmd_application_state():
    try:
        import scriptengine as se

        projects = sys._codesys_daemon_loop.get("projects")
        if projects is None:
            return {"ok": False, "error": "projects not captured"}
        prj = projects.primary
        app = prj.active_application
        if app is None:
            return {
                "ok": True,
                "data": {
                    "application_state": "unknown",
                    "note": "No active application",
                },
            }
        oa = se.online.create_online_application(app)
        if oa is None:
            return {"ok": True, "data": {"application_state": "disconnected"}}
        # Cache the online app
        sys._codesys_daemon_loop["online_app"] = oa
        sys._codesys_daemon_loop["online_target_app"] = app
        info = {}
        for attr in ["application_state", "is_connected", "is_running", "is_online"]:
            if hasattr(oa, attr):
                try:
                    val = getattr(oa, attr)
                    if callable(val):
                        info[attr] = str(val())
                    else:
                        info[attr] = str(val)
                except Exception:
                    pass
        return {"ok": True, "data": info}
    except Exception as e:
        _log("app_state ERROR: {0}".format(e))
        return {"ok": False, "error": "Application state error: {0}".format(e)}


def _cmd_connect_to_device(params):
    _invalidate_device_cache()
    project, err = _get_active_project()
    if err:
        return err
    try:
        ip_address = params.get("ipAddress", params.get("ip", ""))
        gateway_name = params.get("gatewayName", params.get("gateway", "Gateway-1"))
        result = _helpers.connect_to_device_impl(project, ip_address, gateway_name)
        return {"ok": True, "data": result}
    except Exception as e:
        return {
            "ok": False,
            "error": "Connect error: {0}\n{1}".format(e, traceback.format_exc()),
        }


def _cmd_disconnect_from_device():
    _invalidate_device_cache()
    project, err = _get_active_project()
    if err:
        return err
    try:
        result = _helpers.disconnect_from_device_impl(project)
        return {"ok": True, "data": result}
    except Exception as e:
        _log("Disconnect warning: {0}".format(e))
        return {"ok": True, "data": {"state": "disconnected", "warning": str(e)}}


def _cmd_download(params):
    """Force a full download of the active application to the PLC.

    Needed after adding new objects (GVL/DUT/POU): connect_to_device only does
    an online-change login and never pushes a full download, so the PLC keeps
    running the old code. params: {"start": true|false} (default true).
    """
    _invalidate_device_cache()
    project, err = _get_active_project()
    if err:
        return err
    try:
        start = params.get("start", True)
        result = _helpers.download_impl(project, start=start)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Download error: {0}".format(e)}


def _cmd_read_variable(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        variable_name = _require_param(params, "name", str)
        result = _helpers.read_variable_impl(project, variable_name)
        return {"ok": True, "data": result}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": "Read variable error: {0}".format(e)}


def _cmd_write_variable(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        variable_name = _require_param(params, "name", str)
        value = _require_param(params, "value")
        result = _helpers.write_variable_impl(project, variable_name, value)
        return {"ok": True, "data": result}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": "Write variable error: {0}".format(e)}


def _cmd_read_variables(params):
    """Batch-read a list of expressions. params: {"names": [...]}"""
    project, err = _get_active_project()
    if err:
        return err
    try:
        names = params.get("names", [])
        if not isinstance(names, list):
            return {"ok": False, "error": "'names' must be a list"}
        result = _helpers.read_variables_impl(project, names)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Read variables error: {0}".format(e)}


def _cmd_write_variables(params):
    """Batch-write a list of {name, value}. params: {"items": [...], "raw_value": bool}.
    raw_value: when True, skip normalize_write_value (bare enum members for
    qualified-only types where TYPE#member is double-prefixed by CODESYS).
    """
    project, err = _get_active_project()
    if err:
        return err
    try:
        items = params.get("items", [])
        if not isinstance(items, list):
            return {"ok": False, "error": "'items' must be a list"}
        raw_value = bool(params.get("raw_value", False))
        result = _helpers.write_variables_impl(project, items, raw_value=raw_value)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Write variables error: {0}".format(e)}


def _cmd_read_object(params):
    project, err = _get_active_project()
    if err:
        return err
    if not (params.get("path") or params.get("name") or params.get("guid")):
        return {"ok": False, "error": "read_object requires path, name, or guid"}

    try:
        target = _find_object_by_selector(project, params)
        if target is None:
            return {"ok": False, "error": "Object not found"}

        try:
            obj_type = str(target.get_type())
        except Exception:
            obj_type = "Unknown"

        data = {
            "name": _obj_name(target),
            "path": _build_path(target),
            "type": obj_type,
        }
        try:
            data["guid"] = str(target.Guid)
        except Exception:
            pass

        decl = _read_text_member(target, "textual_declaration")
        impl = _read_text_member(target, "textual_implementation")
        if decl is not None:
            data["declaration"] = decl
        if impl is not None:
            data["implementation"] = impl

        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": "Read object error: {0}".format(e)}


def _cmd_device_status(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        device_filter = (params.get("device") or "").lower()
        status_list = []

        app = _helpers.get_active_application(project)
        if app is not None:
            try:
                name = _obj_name(app)
            except Exception:
                name = "Application"
            entry = {
                "name": name,
                "path": _build_path(app),
                "connected": "false",
            }
            online_app, _target_app, online_err = _ensure_online_app(project)
            if online_app is not None:
                entry["connected"] = "true"
                try:
                    entry["application_state"] = str(online_app.application_state)
                except Exception as e:
                    entry["application_state_error"] = str(e)
            elif online_err:
                entry["connection_error"] = online_err
            if not device_filter or device_filter in name.lower():
                status_list.append(entry)
        return {"ok": True, "data": {"devices": status_list}}
    except Exception as e:
        return {"ok": False, "error": "Device status error: {0}".format(e)}


def _cmd_test_online(params):
    import scriptengine as se

    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return {"ok": False, "error": "projects not captured"}
    tb = []
    try:
        tb.append("se imported OK")
        prj = projects.primary
        tb.append("project: " + str(prj)[:80])
        app = prj.active_application
        tb.append("app: " + str(app)[:80])
        if app is None:
            return {"ok": True, "data": {"state": "no app", "log": tb}}
        oa = se.online.create_online_application(app)
        tb.append("oa: " + str(oa)[:80])
        if oa is not None:
            state = str(oa.application_state)
            tb.append("state: " + state)
        return {"ok": True, "data": {"state": str(oa) if oa else "None", "log": tb}}
    except Exception as e:
        _log("test_online EXCEPTION: " + str(e))
        tb.append("ERROR: " + str(e))
        tb.append(traceback.format_exc())
        return {"ok": False, "error": str(e), "log": tb}


def _cmd_explore_api():
    """Explore available APIs for log/event/diagnostic access."""
    import scriptengine as se

    result = {}
    try:
        prj = sys._codesys_daemon_loop.get("projects")
        if prj is None:
            return {"ok": False, "error": "projects not captured"}
        prj = prj.primary
        app = prj.active_application
        oa = se.online.create_online_application(app)

        # 1. OnlineApplication methods
        result["oa_methods"] = [m for m in dir(oa) if not m.startswith("_")]

        # 2. se.online module
        result["se_online_methods"] = [
            m for m in dir(se.online) if not m.startswith("_")
        ]

        # 3. Device objects with log/event/message/diagnostic methods
        log_keywords = [
            "log",
            "event",
            "message",
            "diagnos",
            "error",
            "status",
            "trace",
            "info",
        ]
        devices = []
        for child in prj.get_children(True):
            name = ""
            try:
                name = str(child.get_name())
            except Exception:
                pass
            methods = [
                m for m in dir(child) if any(k in m.lower() for k in log_keywords)
            ]
            if methods:
                devices.append({"name": name, "log_methods": methods})
        result["devices_with_log_api"] = devices[:20]

        # 4. System log methods
        try:
            import __main__

            system = getattr(__main__, "system", None)
            if system:
                sys_methods = [
                    m for m in dir(system) if any(k in m.lower() for k in log_keywords)
                ]
                if sys_methods:
                    result["system_log_methods"] = sys_methods
        except Exception:
            pass

        # 5. se.online module deeper
        online_attrs = {}
        for attr in dir(se.online):
            if not attr.startswith("_"):
                try:
                    val = getattr(se.online, attr)
                    online_attrs[attr] = str(type(val).__name__)
                except Exception:
                    pass
        result["se_online_attrs"] = online_attrs

        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Explore error: {0}".format(e)}


def _cmd_help():
    """List all available commands."""
    help_text = {
        "ping": "Check daemon liveness and cached PLC state",
        "status": "Get daemon, project, sync-folder, and cached PLC state",
        "stop": "Stop the daemon",
        "application_state": "Get PLC application state (run/stop)",
        "project_info": "Get project information",
        "project_tree": "Get project object tree [--depth N]",
        "read_object": "Read one project object [--path PATH | --name NAME | --guid GUID]",
        "connect_to_device": "Connect to PLC [--ip IP] [--gatewayName NAME] — best practice: connect in CODESYS UI before starting daemon. If not, user must approve the connection dialog in CODESYS within ~2 minutes or the command times out.",
        "disconnect_from_device": "Disconnect from PLC",
        "download": "Force a FULL download of the active app to the PLC (login with force-download; needed after adding new GVL/DUT/POU). [--start 0|1, default 1]",
        "read_variable": "Read a PLC variable --name VAR",
        "write_variable": "Write a PLC variable --name VAR --value VAL",
        "device_status": "Get device status",
        "export": "Export project snapshot [--output PATH]",
        "build": "Build the active application [--output PATH]",
        "test_online": "Test online connection helpers",
        "explore": "Explore available APIs",
        "help": "Show this help",
        "read_log": "Read system/PLC log messages [--last N] [--clear]",
        "start_plc": "Start the PLC application",
        "stop_plc": "Stop the PLC application",
        "reset_plc": "Reset PLC [--kind warm|cold|origin]",
        "create_boot_app": "Create boot application on PLC",
        "source_download": "Download source from PLC [--output DIR]",
        "update_pou": "Edge case: update ONE object's text from .st [--name NAME] [--app APP] --st_path PATH. Prefer sync_import_text for the normal disk->IDE flow",
        "delete_pou": "Delete POU/Function/FunctionBlock [--name NAME] [--app APP]",
        "probe": "Probe OnlineApplication for variable/symbol APIs",
        "read_variables": 'Batch-read expressions {"names": [...]} -> per-item value/read_ok/read_error',
        "write_variables": 'Batch-write {"items": [{name,value}]} -> per-item written/write_error',
        "application_tree": "Walk the application OBJECT tree [--depth N] [--values] [--pattern FILTER] [--flat] [--output PATH]",
        "plc_files": "List files on PLC [--path /]",
        "plc_download": "Download file from PLC --src PATH [--dest PATH]",
        "plc_upload": "Upload file to PLC --src PATH --dest PLC_PATH [--overwrite 0|1]",
        "export_csv": "Export PLC variable tree as CSV [--output PATH] [--values]",
        "export_st": "Export project POU source code as .st files [--output DIR]",
        "app_crc": "Get Application CRC and metadata from PLC",
        "app_history": "Log CRC to .dump/app_history.json [--read to just view history]",
        "sync": "Show sync folder info and .dump state",
        "sync_export": "Export Native XML snapshot to .dump/ [--output PATH]",
        "sync_import": "Low-level: import a raw .dump/ XML snapshot back into project [--input PATH]. For text edits use sync_import_text instead",
        "sync_compare": "Compare project tree against .dump/ snapshot [--against PATH]",
        "sync_export_text": "IDE->disk: export Native XML and OVERWRITE project-view/ .st files with the IDE state",
        "sync_import_text": "disk->IDE (preferred): build IMPORT.xml from project-view/ and apply to project. Disk wins on conflicts; requires offline (disconnect first)",
        "sync_compare_text": "Compare project against project-view/ (diff report)",
        "cicd": "Run CI/CD test plan --file path [--timeout N]",
        "permissions": "Show daemon security config (read-only)",
        "plc_log": "Read PLC log [--file codesyscontrol.log] [--tail N] [--output DIR]",
        "app_info": "Get detailed info about application on PLC",
        "compare": "Compare IDE project CRC with PLC Application.crc",
    }
    return {"ok": True, "data": help_text}


def _cmd_probe_oa(params):
    """Probe OnlineApplication for variable/symbol-related APIs."""
    import scriptengine as se
    import System
    import System.Reflection

    oa = sys._codesys_daemon_loop.get("online_app")
    if oa is None:
        return {"ok": False, "error": "Not connected. Call connect_to_device first."}

    result = {}

    # 1. All public methods of oa
    all_methods = []
    for m in dir(oa):
        if not m.startswith("_"):
            try:
                thing = getattr(oa, m)
                kind = "method" if callable(thing) else "property"
                all_methods.append({"name": m, "type": kind, "str": str(thing)[:120]})
            except Exception as e:
                all_methods.append({"name": m, "error": str(e)[:80]})
    result["all_methods"] = all_methods

    # 2. .NET reflection: get methods by signature
    try:
        net_methods = []
        for m in oa.GetType().GetMethods(
            System.Reflection.BindingFlags.Instance
            | System.Reflection.BindingFlags.Public
        ):
            try:
                p = [str(p.ParameterType.Name) for p in m.GetParameters()]
                net_methods.append(
                    {
                        "name": m.Name,
                        "params": p,
                        "return": str(m.ReturnType.Name),
                    }
                )
            except Exception:
                pass
        result["net_methods"] = net_methods
    except Exception as e:
        result["net_reflection_error"] = str(e)

    # 3. Explore get_online_device() return value
    online_dev = None
    if hasattr(oa, "get_online_device"):
        try:
            online_dev = oa.get_online_device()
            if online_dev is not None:
                dev_methods = []
                for m in dir(online_dev):
                    if not m.startswith("_"):
                        try:
                            thing = getattr(online_dev, m)
                            kind = "method" if callable(thing) else "property"
                            dev_methods.append(
                                {"name": m, "type": kind, "str": str(thing)[:120]}
                            )
                        except Exception:
                            pass
                result["online_device_methods"] = dev_methods
                # Try to get its type info
                try:
                    dev_net_methods = []
                    for m in online_dev.GetType().GetMethods(
                        System.Reflection.BindingFlags.Instance
                        | System.Reflection.BindingFlags.Public
                    ):
                        try:
                            p = [str(p.ParameterType.Name) for p in m.GetParameters()]
                            dev_net_methods.append(
                                {
                                    "name": m.Name,
                                    "params": p,
                                    "return": str(m.ReturnType.Name),
                                }
                            )
                        except Exception:
                            pass
                    result["online_device_net_methods"] = dev_net_methods
                except Exception as e:
                    result["online_device_net_error"] = str(e)
        except Exception as e:
            result["get_online_device_error"] = str(e)

    # 4. Explore oa.application (the Application object inside CODESYS)
    app_obj = None
    if hasattr(oa, "application"):
        try:
            app_obj = oa.application
            if app_obj is not None:
                app_methods = []
                for m in dir(app_obj):
                    if not m.startswith("_"):
                        try:
                            thing = getattr(app_obj, m)
                            kind = "method" if callable(thing) else "property"
                            app_methods.append(
                                {"name": m, "type": kind, "str": str(thing)[:180]}
                            )
                        except Exception:
                            pass
                result["oa_application_methods"] = app_methods
                # Try get_children on the application
                try:
                    children = list(app_obj.get_children(True))
                    result["oa_app_children_count"] = len(children)
                    child_names = []
                    for c in children[:30]:
                        try:
                            child_names.append(c.get_name())
                        except Exception:
                            pass
                    result["oa_app_children_names"] = child_names
                except Exception as e:
                    result["oa_app_children_error"] = str(e)[:200]
        except Exception as e:
            result["oa_application_error"] = str(e)[:200]

    # 5. Try to call candidate methods for symbol enumeration
    candidates = [
        "all_variables",
        "variables",
        "symbols",
        "symbol",
        "plc_variables",
        "tags",
        "signals",
        "list_variables",
        "get_all_variables",
        "value_names",
        "variable_names",
        "symbol_names",
    ]
    for name in candidates:
        if hasattr(oa, name):
            try:
                thing = getattr(oa, name)
                if callable(thing):
                    val = thing()
                else:
                    val = thing
                result["try_oa_" + name] = str(val)[:300]
            except Exception as e:
                result["try_oa_" + name + "_error"] = str(e)[:200]

    # Also try on online_device and application
    if online_dev is not None:
        for name in candidates:
            if hasattr(online_dev, name):
                try:
                    thing = getattr(online_dev, name)
                    if callable(thing):
                        val = thing()
                    else:
                        val = thing
                    result["try_dev_" + name] = str(val)[:300]
                except Exception as e:
                    result["try_dev_" + name + "_error"] = str(e)[:200]

    if app_obj is not None:
        for name in candidates:
            if hasattr(app_obj, name):
                try:
                    thing = getattr(app_obj, name)
                    if callable(thing):
                        val = thing()
                    else:
                        val = thing
                    result["try_app_" + name] = str(val)[:300]
                except Exception as e:
                    result["try_app_" + name + "_error"] = str(e)[:200]

    return {"ok": True, "data": result}


# ── Project lifecycle / devices / diagnostics (cts project ...) ────────────────
# Handlers for the `project` subcommand and `discover` that previously had no
# entry in _DISPATCH (returned "Unknown method"). See tests/unit/
# test_cli_daemon_protocol.py for the CLI<->daemon parity contract.


def _sync_folder_for_project(project):
    """Read the project's cds-sync-folder property, or "" if unavailable."""
    try:
        proj_info = _get_project_info_object(project)
        if proj_info is not None:
            props = _project_info_properties(proj_info)
            sf = props.get("cds-sync-folder", "")
            if sf:
                return str(sf)
    except Exception:
        pass
    return ""


def _codesys_version():
    """Best-effort CODESYS/runtime version from the captured system object."""
    system = sys._codesys_daemon_loop.get("system")
    if system is None:
        return ""
    for attr in ("version", "Version", "build_version", "BuildVersion"):
        try:
            val = getattr(system, attr)
            if val:
                return str(val)
        except Exception:
            pass
    return ""


def _project_path(prj):
    """Best-effort filesystem path of a project object, or ""."""
    return _project_file_path(prj)


def _project_display_name(prj):
    """Project name, falling back to the path basename.

    CODESYS project wrappers often expose no usable get_name(), so derive a
    readable name from the file path when the name is empty.
    """
    name = _obj_name(prj)
    if not name:
        path = _project_path(prj)
        if path:
            name = os.path.splitext(os.path.basename(path))[0]
    return name


def _open_projects(projects):
    """Best-effort list of currently open project objects.

    ScriptProjects exposes the open set differently across CODESYS versions;
    probe a couple of accessors, then fall back to the primary alone.
    """
    for attr in ("all", "get_all_projects"):
        try:
            val = getattr(projects, attr)
            if callable(val):
                val = val()
            if val:
                return list(val)
        except Exception:
            pass
    try:
        primary = projects.primary
    except Exception:
        primary = None
    return [primary] if primary is not None else []


def _cmd_project_open(params):
    path = (params or {}).get("path", "")
    if not path:
        return {"ok": False, "error": "project open requires a 'path'"}
    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return {"ok": False, "error": "projects not captured"}
    try:
        # Guard: reopening an already-open project can pop a modal reload dialog
        # in CODESYS, which blocks the single-threaded daemon loop. Skip it.
        norm = os.path.normcase(os.path.normpath(path))
        for prj in _open_projects(projects):
            if os.path.normcase(os.path.normpath(_project_path(prj))) == norm:
                return {
                    "ok": True,
                    "data": {
                        "opened": path,
                        "already_open": True,
                        "name": _project_display_name(prj),
                    },
                }
        project = projects.open(path)
        name = _project_display_name(project) if project is not None else ""
        return {"ok": True, "data": {"opened": path, "name": name}}
    except Exception as e:
        return {"ok": False, "error": "Project open error: {0}".format(e)}


def _cmd_project_close():
    project, err = _get_active_project()
    if err:
        return err
    try:
        name = _project_display_name(project)
        if hasattr(project, "close"):
            project.close()
        else:
            projects = sys._codesys_daemon_loop.get("projects")
            if projects is None:
                return {"ok": False, "error": "projects not captured"}
            projects.close(project)
        return {"ok": True, "data": {"closed": name}}
    except Exception as e:
        return {"ok": False, "error": "Project close error: {0}".format(e)}


def _cmd_project_list():
    projects = sys._codesys_daemon_loop.get("projects")
    if projects is None:
        return {"ok": False, "error": "projects not captured"}
    try:
        try:
            primary = projects.primary
        except Exception:
            primary = None
        primary_path = ""
        if primary is not None:
            primary_path = os.path.normcase(os.path.normpath(_project_path(primary)))
        found = []
        for prj in _open_projects(projects):
            path = _project_path(prj)
            is_primary = bool(primary_path) and (
                os.path.normcase(os.path.normpath(path)) == primary_path
            )
            found.append(
                {
                    "name": _project_display_name(prj),
                    "path": path,
                    "primary": is_primary,
                }
            )
        return {"ok": True, "data": {"projects": found, "count": len(found)}}
    except Exception as e:
        return {"ok": False, "error": "Project list error: {0}".format(e)}


def _cmd_list_devices():
    project, err = _get_active_project()
    if err:
        return err
    try:
        devices = []
        seen = set()
        for child in project.get_children(True):
            is_device_like = False
            try:
                if hasattr(child, "set_simulation_mode") or hasattr(
                    child, "set_gateway_and_address"
                ):
                    is_device_like = True
                else:
                    cls = str(type(child).__name__)
                    if "Device" in cls or "Controller" in cls:
                        is_device_like = True
            except Exception:
                pass
            if not is_device_like:
                continue
            key = str(getattr(child, "guid", id(child)))
            if key in seen:
                continue
            seen.add(key)
            devices.append(
                {
                    "name": _obj_name(child),
                    "path": _build_path(child),
                    "type_guid": str(getattr(child, "type", "")),
                    "class": str(type(child).__name__),
                }
            )
        return {"ok": True, "data": {"devices": devices, "count": len(devices)}}
    except Exception as e:
        return {"ok": False, "error": "List devices error: {0}".format(e)}


def _cmd_set_simulation_mode(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        enable_raw = (params or {}).get("enable", "on")
        enable = _bool_or_none(enable_raw)
        if enable is None:
            enable = str(enable_raw).strip().lower() in ("on", "true", "1", "yes")
        result = _helpers.set_simulation_mode_impl(project, enable)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Set simulation mode error: {0}".format(e)}


def _cmd_set_credentials(params):
    params = params or {}
    username = params.get("username", "")
    password = params.get("password", "")
    if not username:
        return {"ok": False, "error": "set-credentials requires a 'username'"}
    try:
        result = _helpers.set_credentials_impl(username, password)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": "Set credentials error: {0}".format(e)}


def _cmd_diagnose_online():
    project, err = _get_active_project()
    if err:
        return err
    try:
        diag = {}
        try:
            diag["application"] = _helpers.get_application_state_impl(project)
        except Exception as e:
            diag["application_error"] = str(e)
        try:
            _ensure_online_app(project)  # prime the online-app cache
            diag["plc"] = _get_plc_status_snapshot()
        except Exception as e:
            diag["plc_error"] = str(e)
        return {"ok": True, "data": diag}
    except Exception as e:
        return {"ok": False, "error": "Diagnose online error: {0}".format(e)}


def _cmd_discover(params):
    project, err = _get_active_project()
    if err:
        return err
    try:
        base_dir = (params or {}).get("path", "")
        if not base_dir:
            base_dir = _sync_folder_for_project(project)
        if not base_dir:
            return {
                "ok": False,
                "error": "No sync folder set (cds-sync-folder); pass --path",
            }
        from discover_report import build_discovery_report

        report = build_discovery_report(project, base_dir, _codesys_version())
        if report.get("status") != "success":
            return {"ok": False, "error": report.get("error", "discover failed")}
        return {"ok": True, "data": report}
    except Exception as e:
        return {"ok": False, "error": "Discover error: {0}".format(e)}
