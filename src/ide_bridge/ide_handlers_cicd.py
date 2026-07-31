# -*- coding: utf-8 -*-
"""
ide_handlers_cicd.py — CI/CD command handler for the CODESYS daemon.

Implements the 'cicd' command: test-plan execution, cold-reset cycle,
and related helpers.
"""
from __future__ import print_function

import json
import os
import sys
import time

import ide_online_helpers as _helpers

from ide_daemon_state import (
    _log,
    _get_active_project,
    _read_text_utf8,
)

from ide_daemon_helpers import (
    _get_sync_folder,
    _invalidate_device_cache,
)

from ide_handlers_plc import _cmd_reset_plc, _cmd_start_plc
from ide_handlers_build import _cmd_build


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
                    "Format documentation: cds_text_sync/TEST_FORMAT.md"
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
    """Execute a single test plan dict and return results."""
    import time as _time

    import ide_online_helpers as _helpers

    plan_name = plan.get("name", "unnamed")
    plan_timeout = float(plan.get("timeout", 60))
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
