# -*- coding: utf-8 -*-
"""
ide_reverse_pipe_loop.py — CODESYS-side reverse pipe daemon.

This module runs inside CODESYS as a polling loop.
It connects to a CLI-created named pipe server, reads one command,
executes it in the main script context, and writes back the result.

Architecture (reverse pipe):
  1. CLI creates \named pipecds-cli-<user> as server, writes command, waits
  2. CODESYS loop (every 200ms) tries to connect as client
  3. If pipe exists: read command, execute CODESYS API, write response, close
  4. If pipe does not exist: sleep and continue

This avoids calling CODESYS APIs from a background thread.
"""

from __future__ import print_function

import io
import json
import os
import sys
import tempfile
import time
import traceback

import clr

# Add ide_bridge dir to path
_LOOP_DIR = os.path.dirname(os.path.abspath(__file__))
if _LOOP_DIR not in sys.path:
    sys.path.insert(0, _LOOP_DIR)

import ide_online_helpers as _helpers
import ide_runtime_common as _common

clr.AddReference("System.IO.Pipes")
clr.AddReference("System.IO")

from System.IO.Pipes import NamedPipeClientStream, PipeDirection

# ── Shared state / helpers (imported from ide_daemon_state) ───────────────

from ide_daemon_state import (
    PIPE_NAME,
    VERSION,
    POLL_INTERVAL,
    CONNECT_TIMEOUT_MS,
    LOG_FILE,
    MAX_MESSAGE_SIZE,
    _DEFAULT_CONFIG,
    _now,
    _log,
    _read_text_utf8,
    _read_json_from_pipe,
    _write_json_to_pipe,
    _require_param,
    _get_active_project,
    _obj_name,
    _json_safe,
    _build_path,
    _clear_path_cache,
    _load_daemon_config,
    _save_daemon_config,
    _check_permission,
    _get_status_info,
    _read_online_attr,
    _bool_or_none,
    _get_plc_status_snapshot,
)

from ide_daemon_helpers import (
    _get_project_info_object,
    _project_info_summary,
    _project_info_properties,
    _get_device_objects,
    _invalidate_device_cache,
    _find_object_in_project,
    _active_application_name,
    _read_text_member,
    _find_object_by_selector,
    _ensure_online_app,
    _build_tree,
    _get_sync_folder,
    _active_app_online_state,
)

from ide_handlers_plc import (
    _cmd_start_plc,
    _cmd_stop_plc,
    _cmd_reset_plc,
    _cmd_create_boot_app,
    _cmd_source_download,
    _cmd_plc_files,
    _cmd_plc_download,
    _cmd_plc_upload,
    _cmd_plc_log,
    _cmd_read_log,
)

from ide_handlers_build import (
    _cmd_export,
    _cmd_build,
    _cmd_export_csv,
    _cmd_export_st,
    _cmd_application_tree,
)

from ide_handlers_project import (
    _cmd_project_info,
    _cmd_project_tree,
    _cmd_application_state,
    _cmd_connect_to_device,
    _cmd_disconnect_from_device,
    _cmd_download,
    _cmd_read_variable,
    _cmd_write_variable,
    _cmd_read_variables,
    _cmd_write_variables,
    _cmd_read_object,
    _cmd_device_status,
    _cmd_test_online,
    _cmd_explore_api,
    _cmd_help,
    _cmd_probe_oa,
)

from ide_handlers_crc import (
    _cmd_app_crc,
    _cmd_app_info,
    _cmd_app_history,
    _cmd_compare_crc,
    _cmd_permissions,
)

from ide_handlers_sync import (
    _cmd_sync_info,
    _cmd_sync_export,
    _cmd_sync_import,
    _cmd_sync_compare,
    _cmd_sync_export_text,
    _cmd_sync_import_text,
    _cmd_sync_compare_text,
    _cmd_update_pou,
    _cmd_delete_pou,
)

# ── UI Dashboard (WinForms) ────────────────────────────────────────────────

_DASHBOARD = None
_ui = None
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    import ide_daemon_ui as _ui

    _DASHBOARD = "winforms"
except Exception:
    _ui = None

# ── Global state ──────────────────────────────────────────────────────────

if not hasattr(sys, "_codesys_daemon_loop"):
    sys._codesys_daemon_loop = {
        "running": False,
        "started": False,
        "projects": None,
        "system": None,
        "started_at": None,
        "command_count": 0,
        "last_command": None,
        "online_app": None,
        "online_target_app": None,
    }


# ── Capture globals ───────────────────────────────────────────────────────


def capture_codesys_globals():
    g = globals()
    projects_obj = g.get("projects")
    system_obj = g.get("system")

    if projects_obj is not None and hasattr(projects_obj, "primary"):
        sys._codesys_daemon_loop["projects"] = projects_obj
    else:
        try:
            import __main__

            if hasattr(__main__, "projects"):
                proj = __main__.projects
                if hasattr(proj, "primary"):
                    sys._codesys_daemon_loop["projects"] = proj
            if hasattr(__main__, "system"):
                sys._codesys_daemon_loop["system"] = __main__.system
        except Exception:
            pass

    if system_obj is not None:
        sys._codesys_daemon_loop["system"] = system_obj

    if sys._codesys_daemon_loop["projects"] is None:
        _log("WARNING: projects not captured!")
    if sys._codesys_daemon_loop["system"] is None:
        _log("WARNING: system not captured!")


# ── Command handler ────────────────────────────────────────────────────────


def handle_command(method, params):
    """Dispatch a command. All CODESYS API calls happen here, in the main loop."""
    _log("Command: {0}".format(method))

    # Command aliases (shorter CLI names -> full daemon method names)
    _ALIASES = {
        "connect": "connect_to_device",
        "disconnect": "disconnect_from_device",
        "app": "application_state",
        "proj": "project_info",
        "tree": "project_tree",
    }
    _original_method = method
    method = _ALIASES.get(method, method)

    # Commands that never require permission check (system/read-only)
    if method not in (
        "ping",
        "status",
        "help",
        "stop",
        "permissions",
        "sync",
        "project_info",
        "project_tree",
        "read_object",
        "explore",
    ):
        allowed, reason = _check_permission(method)
        if not allowed:
            return {"ok": False, "error": reason}

    try:
        if method == "stop":
            sys._codesys_daemon_loop["running"] = False
            return {"ok": True, "data": {"message": "Daemon stopping..."}}

        elif method == "ping":
            return {
                "ok": True,
                "data": {
                    "status": "pong",
                    "mode": "reverse_pipe",
                    "pid": os.getpid(),
                    "plc": _get_plc_status_snapshot(),
                },
            }

        elif method == "status":
            result = _get_status_info()
            result["running"] = sys._codesys_daemon_loop.get("running", False)
            result["mode"] = "reverse_pipe"
            result["plc"] = _get_plc_status_snapshot()
            return {"ok": True, "data": result}

        elif method == "project_info":
            return _cmd_project_info()

        elif method == "project_tree":
            return _cmd_project_tree(params)

        elif method == "read_object":
            return _cmd_read_object(params)

        elif method == "application_state":
            return _cmd_application_state()

        elif method == "connect_to_device":
            return _cmd_connect_to_device(params)

        elif method == "disconnect_from_device":
            return _cmd_disconnect_from_device()

        elif method == "download":
            return _cmd_download(params)

        elif method == "read_variable":
            return _cmd_read_variable(params)

        elif method == "write_variable":
            return _cmd_write_variable(params)

        elif method == "read_variables":
            return _cmd_read_variables(params)

        elif method == "write_variables":
            return _cmd_write_variables(params)

        elif method == "export":
            return _cmd_export(params)

        elif method == "build":
            return _cmd_build(params)

        elif method == "device_status":
            return _cmd_device_status(params)

        elif method == "test_online":
            return _cmd_test_online(params)

        elif method == "explore":
            return _cmd_explore_api()

        elif method == "sync":
            return _cmd_sync_info()

        elif method == "sync_export":
            return _cmd_sync_export(params)

        elif method == "sync_import":
            return _cmd_sync_import(params)

        elif method == "sync_compare":
            return _cmd_sync_compare(params)

        elif method == "sync_export_text":
            return _cmd_sync_export_text(params)

        elif method == "sync_import_text":
            return _cmd_sync_import_text(params)
        elif method == "update_pou":
            return _cmd_update_pou(params)

        elif method == "delete_pou":
            return _cmd_delete_pou(params)

        elif method == "cicd":
            return _cmd_cicd(params)
        elif method == "sync_compare_text":
            return _cmd_sync_compare_text(params)

        elif method == "help":
            return _cmd_help()

        elif method == "read_log":
            return _cmd_read_log(params)

        elif method == "start_plc":
            return _cmd_start_plc()

        elif method == "stop_plc":
            return _cmd_stop_plc()

        elif method == "reset_plc":
            return _cmd_reset_plc(params)

        elif method == "create_boot_app":
            return _cmd_create_boot_app()

        elif method == "source_download":
            return _cmd_source_download(params)

        elif method == "probe":
            return _cmd_probe_oa(params)

        elif method == "application_tree":
            return _cmd_application_tree(params)

        elif method == "plc_files":
            return _cmd_plc_files(params)

        elif method == "plc_log":
            return _cmd_plc_log(params)

        elif method == "plc_download":
            return _cmd_plc_download(params)

        elif method == "plc_upload":
            return _cmd_plc_upload(params)

        elif method == "export_csv":
            return _cmd_export_csv(params)

        elif method == "export_st":
            return _cmd_export_st(params)

        elif method == "app_crc":
            return _cmd_app_crc(params)

        elif method == "app_info":
            return _cmd_app_info()

        elif method == "app_history":
            return _cmd_app_history(params)

        elif method == "permissions":
            return _cmd_permissions()

        elif method == "compare":
            return _cmd_compare_crc(params)

        else:
            return {"ok": False, "error": "Unknown method: {0}".format(method)}

    except Exception as e:
        _log("Command error: {0}\n{1}".format(e, traceback.format_exc()))
        return {"ok": False, "error": "{0}: {1}".format(type(e).__name__, e)}



def _parse_codesys_value(raw):
    """Parse CODESYS value string like 'REAL#13.0', 'INT#5', 'BOOL#TRUE' into Python type."""
    if not raw:
        return raw
    s = str(raw).strip()
    if "#" in s:
        prefix, val = s.split("#", 1)
        prefix = prefix.upper()
        if prefix in (
            "REAL",
            "LREAL",
            "INT",
            "DINT",
            "UINT",
            "UDINT",
            "SINT",
            "USINT",
            "BYTE",
            "WORD",
            "DWORD",
        ):
            try:
                return float(val) if "." in val else int(val)
            except ValueError:
                return val
        if prefix == "BOOL":
            return val.upper() == "TRUE"
        if prefix == "STRING":
            return val
    # Try numeric
    try:
        return (
            int(s)
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit())
            else float(s)
        )
    except ValueError:
        pass
    return s


def _cicd_cold_reset(project, ip_address="", gateway_name="Gateway-1"):
    """Perform full cold reset cycle for CI/CD: stop PLC → cold reset → reconnect → build → start."""
    import time as _time

    _log("CICD: Cold reset sequence started")

    # 1. Stop PLC
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is not None and hasattr(oa, "stop"):
            _log("CICD: Stopping PLC")
            oa.stop()
            _time.sleep(0.3)
    except Exception as e:
        _log("CICD: Stop PLC (non-fatal): {0}".format(e))

    # 2. Cold reset via existing command
    _log("CICD: Performing cold reset")
    reset_result = _cmd_reset_plc({"kind": "cold"})
    if not reset_result.get("ok"):
        raise RuntimeError(
            "CICD cold reset failed: {0}".format(reset_result.get("error", ""))
        )

    _time.sleep(0.5)

    # 3. Clear cached online_app
    sys._codesys_daemon_loop["online_app"] = None
    sys._codesys_daemon_loop["online_target_app"] = None
    _invalidate_device_cache()

    # 4. Re-connect (creates fresh online_app, logs in)
    _log("CICD: Reconnecting after cold reset")
    from ide_online_helpers import connect_to_device_impl

    connect_to_device_impl(project, ip_address, gateway_name)

    _time.sleep(0.3)

    # 5. Build → online change (re-download application to PLC)
    _log("CICD: Building after cold reset")
    build_result = _cmd_build({})
    if not build_result.get("ok"):
        _log("CICD: Build warning: {0}".format(build_result.get("error", "")))

    # 6. Start PLC
    _log("CICD: Starting PLC after cold reset")
    try:
        oa = sys._codesys_daemon_loop.get("online_app")
        if oa is not None and hasattr(oa, "start"):
            oa.start()
    except Exception as e:
        _log("CICD: Start PLC (non-fatal): {0}".format(e))

    _log("CICD: Cold reset complete")


def _cmd_cicd(params):
    """Execute CI/CD test plan.

    Args:
        file: path to test JSON file (relative to sync_folder/.test/ or absolute)
    """
    import time as _time

    import ide_online_helpers as _helpers

    project, err = _get_active_project()
    if err:
        return err

    # Resolve file path
    file_path = params.get("file", "")
    sf, sf_err = _get_sync_folder()
    if sf_err:
        return {"ok": False, "error": sf_err}

    if not file_path:
        # No file specified: run all tests from .test/ by default.
        test_dir = os.path.join(sf, ".test")
        if not os.path.isdir(test_dir):
            legacy_test_dir = os.path.join(sf, "test")
            if os.path.isdir(legacy_test_dir):
                test_dir = legacy_test_dir
        if not os.path.isdir(test_dir):
            return {
                "ok": False,
                "error": (
                    "No .test/ directory found at {0}. "
                    "Create JSON test plans in <sync-folder>/.test/ "
                    "and run 'cts test --file plan.json'. "
                    "Format documentation: cli/TEST_FORMAT.md"
                ).format(test_dir),
            }
        json_files = sorted([f for f in os.listdir(test_dir) if f.endswith(".json")])
        if not json_files:
            return {"ok": False, "error": "No JSON files found in {0}".format(test_dir)}
        # Cold reset once before running all tests — handled by first plan via _prepare_cicd_plan
        sys._codesys_daemon_loop["cicd_reset_done"] = False

        results = []
        for jf in json_files:
            fp = os.path.join(test_dir, jf)
            plan = {}
            try:
                plan = json.loads(_read_text_utf8(fp))
            except Exception as e:
                results.append({"file": jf, "status": "FAIL", "error": str(e)})
                continue
            result = _run_test_plan(project, plan)
            result["file"] = jf
            results.append(result)
        return {"ok": True, "data": _summarize_cicd_results(results)}

    if not os.path.isabs(file_path):
        test_dir = os.path.join(sf, ".test")
        candidate = os.path.join(test_dir, file_path)
        if not os.path.exists(candidate):
            legacy_candidate = os.path.join(sf, "test", file_path)
            if os.path.exists(legacy_candidate):
                candidate = legacy_candidate
        file_path = candidate

    if not os.path.exists(file_path):
        return {"ok": False, "error": "Test file not found: {0}".format(file_path)}

    # Read and execute
    try:
        plan = json.loads(_read_text_utf8(file_path))
    except Exception as e:
        return {"ok": False, "error": "Failed to parse test file: {0}".format(e)}

    result = _run_test_plan(project, plan)
    result["file"] = os.path.basename(file_path)
    return {"ok": True, "data": _summarize_cicd_results([result])}


def _get_application_name(app):
    """Return a readable CODESYS application name."""
    if app is None:
        return ""
    for attr in ("get_name", "Name", "name"):
        try:
            value = getattr(app, attr)
            if callable(value):
                value = value()
            if value:
                return str(value)
        except Exception:
            pass
    return ""


def _find_application_by_name(project, name):
    """Find an application object by exact name in the active project."""
    if not name:
        return None
    try:
        app = project.active_application
        if app is not None and _get_application_name(app) == name:
            return app
    except Exception:
        pass
    try:
        for child in project.get_children(True):
            try:
                if hasattr(child, "is_application") and child.is_application:
                    if _get_application_name(child) == name:
                        return child
            except Exception:
                pass
    except Exception:
        pass
    return None


def _prepare_cicd_plan(project, plan):
    """Validate the plan target and prepare the online application."""
    application = str(plan.get("application", "") or "").strip()
    if not application:
        raise RuntimeError(
            'Test plan must specify the target application: {"application": "Application"}'
        )

    target_app = _find_application_by_name(project, application)
    if target_app is None:
        raise RuntimeError(
            "Application '{0}' not found in the active project".format(application)
        )

    active_name = ""
    try:
        active_name = _get_application_name(project.active_application)
    except Exception:
        pass
    if active_name and active_name != application:
        try:
            project.active_application = target_app
            sys._codesys_daemon_loop["online_app"] = None
            sys._codesys_daemon_loop["online_target_app"] = None
            active_name = application
        except Exception as e:
            raise RuntimeError(
                "Test plan targets application '{0}', but active application is '{1}'. "
                "Automatic switch failed: {2}".format(application, active_name, e)
            )

    ip_address = str(plan.get("ip", "") or plan.get("device_ip", "") or "").strip()
    gateway_name = str(
        plan.get("gateway", "") or plan.get("gateway_name", "Gateway-1") or "Gateway-1"
    ).strip()
    connect_result = _helpers.connect_to_device_impl(project, ip_address, gateway_name)

    # Cold reset if requested by plan (and not already done by bulk runner)
    if plan.get("reset") == "cold" and not sys._codesys_daemon_loop.get(
        "cicd_reset_done"
    ):
        _cicd_cold_reset(project, ip_address, gateway_name)
        sys._codesys_daemon_loop["cicd_reset_done"] = True

    if plan.get("start", True):
        start_result = _cmd_start_plc()
        if not start_result.get("ok"):
            start_error = start_result.get("error", "Failed to start PLC application")
            if (
                "state is run" not in str(start_error).lower()
                and "already" not in str(start_error).lower()
            ):
                raise RuntimeError(start_error)

    return {
        "application": application,
        "device": connect_result.get("device", ""),
        "state": connect_result.get("state", ""),
    }


def _summarize_cicd_results(results):
    """Return detailed results plus a compact machine/human summary."""
    passed = 0
    failed = 0
    total_tests = 0
    files = []
    for result in results:
        status = result.get("status", "FAIL")
        tests = result.get("tests", [])
        ok_tests = sum(1 for t in tests if t.get("status") == "PASS")
        bad_tests = sum(1 for t in tests if t.get("status") == "FAIL")
        if tests:
            passed += ok_tests
            failed += bad_tests
            total_tests += len(tests)
        else:
            total_tests += 1
            if status == "PASS":
                passed += 1
            else:
                failed += 1
        files.append(
            {
                "file": result.get("file", ""),
                "plan": result.get("plan", ""),
                "status": "SUCCESS" if status == "PASS" else "FAIL",
                "ok": status == "PASS",
                "tests_ok": ok_tests,
                "tests_failed": bad_tests,
                "error": result.get("error", ""),
                "total_ms": result.get("total_ms", 0),
            }
        )
    return {
        "status": "SUCCESS" if failed == 0 else "FAIL",
        "ok": failed == 0,
        "summary": {
            "ok": passed,
            "not_ok": failed,
            "total": total_tests,
            "files": len(results),
        },
        "files": files,
        "results": results,
    }


def _run_test_plan(project, plan):
    """Execute a single test plan and return results."""
    import time as _time

    import ide_online_helpers as _helpers

    plan_name = plan.get("name", "unnamed")
    plan_timeout = plan.get("timeout", 30000) / 1000.0  # convert to seconds
    plan_continue_on_fail = plan.get("continue_on_fail", False)
    tests = plan.get("tests", [])
    prepare_info = None

    start_all = _time.time()
    results = {
        "plan": plan_name,
        "application": str(plan.get("application", "") or ""),
        "status": "PASS",
        "total_ms": 0,
        "tests": [],
    }

    if not tests:
        results["status"] = "FAIL"
        results["error"] = "Test plan contains no tests"
        results["total_ms"] = int((_time.time() - start_all) * 1000)
        return results

    try:
        prepare_info = _prepare_cicd_plan(project, plan)
        results["prepare"] = prepare_info
    except Exception as e:
        results["status"] = "FAIL"
        results["error"] = str(e)
        results["total_ms"] = int((_time.time() - start_all) * 1000)
        return results

    for test in tests:
        test_name = test.get("name", "unnamed")
        test_timeout = test.get("timeout", plan_timeout * 1000) / 1000.0
        steps = test.get("steps", [])
        continue_on_fail = test.get("continue_on_fail", False)

        test_start = _time.time()
        test_result = {
            "name": test_name,
            "status": "PASS",
            "ms": 0,
            "steps": [],
        }

        test_failed = False
        for i, step in enumerate(steps):
            action = step.get("action", "")
            step_start = _time.time()

            # Check overall timeout
            if _time.time() - start_all > plan_timeout:
                step_result = {
                    "action": action,
                    "status": "FAIL",
                    "ms": 0,
                    "error": "Plan timeout exceeded",
                }
                test_result["steps"].append(step_result)
                test_failed = True
                break

            step_result = {"action": action}

            try:
                if action == "write":
                    var_name = step.get("variable", "")
                    value = step.get("value")
                    if not var_name:
                        raise Exception("write: variable name is required")
                    # Convert value to string (CODESYS online API expects str)
                    if isinstance(value, bool):
                        value_str = "TRUE" if value else "FALSE"
                    elif isinstance(value, float):
                        value_str = str(value)
                    elif isinstance(value, int):
                        value_str = str(value)
                    else:
                        value_str = str(value)
                    _helpers.write_variable_impl(project, var_name, value_str)
                    _log("cicd write {0} = {1}".format(var_name, value_str))

                elif action == "wait":
                    ms = int(step.get("ms", 100))
                    _time.sleep(ms / 1000.0)

                elif action == "read":
                    var_name = step.get("variable", "")
                    if not var_name:
                        raise Exception("read: variable name is required")
                    result = _helpers.read_variable_impl(project, var_name)
                    step_result["value"] = result
                    _log("cicd read {0} = {1}".format(var_name, result))

                    # Extract actual value from read result
                    raw_value = (
                        result.get("value", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    # Parse CODESYS format: "REAL#13.0", "INT#5", "BOOL#TRUE"
                    parsed = _parse_codesys_value(raw_value)
                    step_result["parsed"] = parsed

                    # Check expected value
                    expected = step.get("expected")
                    tolerance = float(step.get("tolerance", 0))
                    expected_min = step.get("expected_min")
                    expected_max = step.get("expected_max")

                    if expected is not None:
                        if isinstance(parsed, (int, float)) and isinstance(
                            expected, (int, float)
                        ):
                            if abs(float(parsed) - float(expected)) > tolerance:
                                raise Exception(
                                    "read {0}: expected {1}±{2}, got {3} (raw={4})".format(
                                        var_name, expected, tolerance, parsed, raw_value
                                    )
                                )
                        elif isinstance(parsed, bool) and isinstance(expected, bool):
                            if parsed != expected:
                                raise Exception(
                                    "read {0}: expected {1}, got {2}".format(
                                        var_name, expected, parsed
                                    )
                                )
                        elif str(parsed).lower() != str(expected).lower():
                            raise Exception(
                                "read {0}: expected {1}, got {2}".format(
                                    var_name, expected, parsed
                                )
                            )

                    if expected_min is not None and float(parsed) < float(expected_min):
                        raise Exception(
                            "read {0}: min {1}, got {2}".format(
                                var_name, expected_min, parsed
                            )
                        )
                    if expected_max is not None and float(parsed) > float(expected_max):
                        raise Exception(
                            "read {0}: max {1}, got {2}".format(
                                var_name, expected_max, parsed
                            )
                        )

                elif action == "assert":
                    var_name = step.get("variable", "")
                    if not var_name:
                        raise Exception("assert: variable name is required")
                    result = _helpers.read_variable_impl(project, var_name)
                    raw_value = (
                        result.get("value", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    parsed = _parse_codesys_value(raw_value)
                    expected = step.get("expected")
                    if expected is not None:
                        # Compare as native types
                        if isinstance(expected, bool) and isinstance(parsed, bool):
                            if parsed != expected:
                                raise Exception(
                                    "assert {0}: expected {1}, got {2}".format(
                                        var_name, expected, parsed
                                    )
                                )
                        elif str(parsed).lower() != str(expected).lower():
                            raise Exception(
                                "assert {0}: expected {1}, got {2}".format(
                                    var_name, expected, parsed
                                )
                            )

                else:
                    raise Exception("Unknown action: {0}".format(action))

                step_result["status"] = "PASS"

            except Exception as e:
                step_result["status"] = "FAIL"
                step_result["error"] = str(e)
                test_failed = True
                if not continue_on_fail:
                    test_result["steps"].append(step_result)
                    test_result["ms"] = int((_time.time() - test_start) * 1000)
                    test_result["status"] = "FAIL"
                    test_result["error"] = str(e)
                    break

            step_result["ms"] = int((_time.time() - step_start) * 1000)
            test_result["steps"].append(step_result)

        test_result["ms"] = int((_time.time() - test_start) * 1000)
        if test_failed and "error" not in test_result:
            test_result["status"] = "FAIL"
        results["tests"].append(test_result)

        if test_failed and not continue_on_fail and not plan_continue_on_fail:
            break

    overall_fail = any(t["status"] == "FAIL" for t in results["tests"])
    results["status"] = "FAIL" if overall_fail else "PASS"
    results["total_ms"] = int((_time.time() - start_all) * 1000)
    return results


# ── Main polling loop ─────────────────────────────────────────────────────


def _get_poll_interval():
    """Get current poll interval from config, default 0.2s."""
    config = sys._codesys_daemon_loop.get("config", {})
    if not config:
        config = _load_daemon_config()
        sys._codesys_daemon_loop["config"] = config
    return config.get("poll_ms", 200) / 1000.0


def _dashboard_command_label(method, params):
    """Return a readable dashboard label for an incoming command."""
    if method == "cicd":
        test_file = str((params or {}).get("file", "") or "").strip()
        if test_file:
            return "Run test: {0}".format(os.path.basename(test_file))
        return "Run tests: all"
    return method


def _dashboard_log_response(dash, method, response):
    """Append concise result lines to the dashboard after command execution."""
    if dash is None or method != "cicd":
        return
    try:
        if not response.get("ok"):
            dash.log_command(
                "FAIL tests: {0}".format(response.get("error", "unknown error"))
            )
            return
        data = response.get("data", {})
        summary = data.get("summary", {})
        total = int(summary.get("total", 0))
        passed = int(summary.get("ok", 0))
        failed = int(summary.get("not_ok", 0))
        for item in data.get("files", []):
            label = item.get("file") or item.get("plan") or "test"
            status = "PASS" if item.get("ok") else "FAIL"
            item_total = int(item.get("tests_ok", 0)) + int(item.get("tests_failed", 0))
            item_passed = int(item.get("tests_ok", 0))
            if item_total > 0:
                dash.log_command(
                    "{0} {1} ({2}/{3})".format(status, label, item_passed, item_total)
                )
            else:
                dash.log_command("{0} {1}".format(status, label))
        if failed:
            dash.log_command("Test suite FAIL ({0}/{1} passed)".format(passed, total))
        else:
            dash.log_command("Test suite PASS ({0}/{1})".format(passed, total))
    except Exception:
        pass


def run_loop():
    """Main polling loop. Runs inside CODESYS script context."""
    capture_codesys_globals()
    sys._codesys_daemon_loop["running"] = True
    sys._codesys_daemon_loop["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sys._codesys_daemon_loop["started"] = True

    _log(
        "cds-text-sync v{0} started  pipe={1}  pid={2}".format(
            VERSION, PIPE_NAME, os.getpid()
        )
    )
    _log("Waiting for CLI commands...  cds-text-sync --help")

    # Warn if sync folder not configured
    sf, sf_err = _get_sync_folder()
    if sf is None:
        _log(
            '[WARN] Sync folder not configured. Set "cds-sync-folder" project property via Project_directory.py'
        )
    else:
        _log("Sync folder: {0}".format(sf))

    # Show UI dashboard (WinForms window)
    _dash = None
    if _ui is not None:
        try:
            _dash = _ui.show_daemon_ui()
            # Push startup messages to dashboard
            if _dash is not None:
                _dash.log_command("Daemon v{0} started".format(VERSION))
                _dash.log_command("Waiting for CLI...")
                if sf is None:
                    _dash.log_command("[WARN] Sync folder not set")
                else:
                    _dash.log_command("Sync folder: {0}".format(os.path.basename(sf)))
        except Exception as e:
            _dash = None

    while sys._codesys_daemon_loop.get("running", False):
        pipe = None
        try:
            # Keep UI responsive
            if _dash is not None:
                _ui.pump_events(_dash)

            # Early exit if stop was requested via UI button
            if not sys._codesys_daemon_loop.get("running", False):
                break

            # Try to connect to the CLI's pipe server
            pipe = NamedPipeClientStream(".", PIPE_NAME, PipeDirection.InOut)
            pipe.Connect(CONNECT_TIMEOUT_MS)

            # Connected! Read the command
            cmd = _read_json_from_pipe(pipe)
            if cmd is None:
                try:
                    pipe.Close()
                except Exception:
                    pass
                time.sleep(_get_poll_interval())
                continue

            method = cmd.get("method", "")
            params = cmd.get("params", {})

            sys._codesys_daemon_loop["command_count"] = (
                sys._codesys_daemon_loop.get("command_count", 0) + 1
            )
            sys._codesys_daemon_loop["last_command"] = method

            # Log to UI
            if _dash is not None:
                try:
                    _dash.log_command(_dashboard_command_label(method, params))
                    _dash.set_command_count(sys._codesys_daemon_loop["command_count"])
                except Exception:
                    pass

            # Execute command in main script context
            response = handle_command(method, params)

            if _dash is not None:
                _dashboard_log_response(_dash, method, response)

            # Write response back
            ok = _write_json_to_pipe(pipe, response)
            if not ok:
                _log("Failed to write response for {0}".format(method))

            try:
                pipe.Close()
            except Exception:
                pass

            # If stop was requested, break out of the loop
            if method == "stop":
                break

        except Exception as e:
            # Expected: pipe not found (no CLI waiting)
            err_str = str(e)
            if (
                "timed out" in err_str.lower()
                or "Could not connect" in err_str
                or "not found" in err_str.lower()
            ):
                # Normal - no CLI pipe available
                pass
            else:
                _log("Pipe poll error: {0}".format(e))
            if pipe is not None:
                try:
                    pipe.Close()
                except Exception:
                    pass

        time.sleep(_get_poll_interval())

    _log("Reverse Pipe Daemon loop ended.")
    sys._codesys_daemon_loop["running"] = False

    # Close UI dashboard
    if _dash is not None and _ui is not None:
        try:
            _dash.close_window()
        except Exception:
            pass
    _dash = None


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__" or __name__ == "__builtin__":
    run_loop()
else:
    # Called from Project_daemon.py via exec()
    # Check if globals suggest we're inside CODESYS
    if globals().get("projects") is not None or globals().get("system") is not None:
        run_loop()
