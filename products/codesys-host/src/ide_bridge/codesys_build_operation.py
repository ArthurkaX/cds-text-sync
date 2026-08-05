# -*- coding: utf-8 -*-
"""
codesys_build_operation.py - Build active CODESYS application and export diagnostics.
"""
from __future__ import print_function
import codecs
import json
import os
import re
import time

from codesys_runtime import resolve_runtime
from codesys_utils import (
    ensure_engine_path,
    init_logging,
    load_base_dir,
    resolve_projects,
    safe_str,
)


BUILD_CATEGORY_GUID = "97F48D64-A2A3-4856-B640-75C046E37EA9"


def _dump_root(base_dir):
    path = os.path.join(base_dir, ".dump")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _clean_filename(value):
    text = safe_str(value) or "Application"
    return "".join([c if c.isalnum() or c in ("-", "_") else "_" for c in text])


def _write_text(path, lines):
    with codecs.open(path, "w", "utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _write_json(path, data):
    with codecs.open(path, "w", "utf-8") as handle:
        handle.write(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")


def _project_name(project):
    name = "Unknown Project"
    try:
        if hasattr(project, "name"):
            name = safe_str(project.name)
        elif hasattr(project, "get_name"):
            name = safe_str(project.get_name())
        elif hasattr(project, "path"):
            name = os.path.basename(safe_str(project.path))
    except Exception:
        pass
    if "\\" in name or "/" in name:
        name = os.path.basename(name).replace(".project", "")
    match = re.search(r"stPath=([^,\)]+)", name)
    if match:
        name = os.path.basename(match.group(1)).replace(".project", "")
    return name


def _load_profile(base_dir):
    ensure_engine_path()
    try:
        from _project_profiles import kind_for_type_guid, load_profile
        from _project_settings import load_project_settings
        settings = load_project_settings(base_dir)
        profile = load_profile(settings.get("profile"))
        return settings, profile, kind_for_type_guid
    except Exception:
        return {"profile": "default"}, {}, None


def _kind_for_obj(obj, profile, kind_for_type_guid):
    if kind_for_type_guid is None:
        return None
    try:
        return kind_for_type_guid(profile, safe_str(obj.type))
    except Exception:
        return None


def _find_applications(project, profile, kind_for_type_guid):
    apps = []
    try:
        for obj in project.get_children(recursive=True):
            if _kind_for_obj(obj, profile, kind_for_type_guid) == "application":
                apps.append(obj)
    except Exception:
        pass
    return apps


def _choose_application(runtime, project, base_dir):
    settings, profile, kind_for_type_guid = _load_profile(base_dir)
    apps = _find_applications(project, profile, kind_for_type_guid)

    if len(apps) > 1:
        try:
            options = [safe_str(app.get_name()) for app in apps]
            choice = runtime.ui.choose("Multiple applications detected. Select application to build:", options)
            try:
                choice_idx = choice[0]
            except Exception:
                choice_idx = choice
            if choice_idx is not None and choice_idx >= 0 and choice_idx < len(apps):
                return apps[choice_idx]
            return None
        except Exception as error:
            print("Application selection error: " + safe_str(error))

    if len(apps) == 1:
        return apps[0]

    try:
        if project.active_application:
            return project.active_application
    except Exception:
        pass

    return None


def _message_id(msg):
    prefix = safe_str(getattr(msg, "prefix", ""))
    try:
        number = int(getattr(msg, "number", 0))
    except Exception:
        number = 0
    if number > 0:
        return "%s%04d" % (prefix, number)
    return prefix


def _text_sections(obj_ref):
    declaration = ""
    implementation = ""
    try:
        text_obj = getattr(obj_ref, "textual_declaration", None)
        if text_obj:
            declaration = safe_str(text_obj.text)
    except Exception:
        pass
    try:
        text_obj = getattr(obj_ref, "textual_implementation", None)
        if text_obj:
            implementation = safe_str(text_obj.text)
    except Exception:
        pass
    return declaration, implementation


def _line_col_from_position(msg, obj_ref):
    pos_index = getattr(msg, "position", -1)
    try:
        pos_index = int(pos_index)
    except Exception:
        pos_index = -1
    if pos_index < 0 or obj_ref is None:
        return 0, 0, ""

    declaration, implementation = _text_sections(obj_ref)
    section = "(Decl)"
    rel_index = pos_index
    target = declaration
    if pos_index >= len(declaration):
        section = "(Impl)"
        rel_index = pos_index - len(declaration)
        target = implementation
    if rel_index < 0:
        rel_index = 0
    if rel_index > len(target):
        rel_index = len(target)
    before = target[:rel_index]
    lines = before.split("\n")
    return len(lines), len(lines[-1]) + 1, section


def _fallback_line_col(msg_text):
    line = 0
    col = 0
    line_match = re.search(r"[Ll]ine[:\s]+(\d+)", msg_text)
    if line_match:
        line = int(line_match.group(1))
    col_match = re.search(r"[Cc]olumn[:\s]+(\d+)", msg_text)
    if col_match:
        col = int(col_match.group(1))
    return line, col


def _collect_messages(runtime, category_guid):
    try:
        return runtime.system.get_message_objects(category_guid)
    except Exception:
        return []


def _severity(msg):
    return safe_str(getattr(msg, "severity", ""))


def _object_name(msg, app_name):
    obj_ref = None
    obj_name = "N/A"
    try:
        obj_ref = getattr(msg, "object", None)
        if obj_ref:
            obj_name = safe_str(obj_ref.get_name())
    except Exception:
        obj_name = safe_str(getattr(msg, "object", "N/A"))
    if obj_name and obj_name != "N/A":
        return obj_name + " [" + app_name + "]", obj_ref
    return obj_name, obj_ref


def _format_messages(messages, app_name):
    rows = []
    error_count = 0
    warning_count = 0

    for msg in messages:
        msg_text = safe_str(getattr(msg, "text", ""))
        if "Build started" in msg_text or "Compile complete" in msg_text:
            continue

        severity = _severity(msg)
        if "Error" not in severity and "Warning" not in severity:
            continue

        if "Error" in severity:
            error_count += 1
        if "Warning" in severity:
            warning_count += 1

        obj_text, obj_ref = _object_name(msg, app_name)
        line, col, section = _line_col_from_position(msg, obj_ref)
        if line <= 0:
            line, col = _fallback_line_col(msg_text)
        pos_text = ""
        if line > 0:
            pos_text = "Line {0}, Col {1} {2}".format(line, col, section).strip()

        msg_id = _message_id(msg)
        description = (msg_id + ": " + msg_text).strip(": ")
        description = description.replace("\r", "").replace("\n", " ")

        rows.append({
            "severity": severity,
            "code": msg_id,
            "text": msg_text,
            "description": description,
            "object": obj_text,
            "line": line,
            "column": col,
            "section": section.strip("()"),
            "position": pos_text,
        })

    return rows, error_count, warning_count


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}
    init_logging(base_dir)

    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    project = projects_obj.primary
    app = _choose_application(runtime, project, base_dir)
    if app is None:
        message = "Error: No active application found to build."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    app_name = safe_str(app.get_name())
    print("=== Starting Project Build ===")
    print("Application: " + app_name)

    try:
        from System import Guid
        category_guid = Guid(BUILD_CATEGORY_GUID)
    except Exception:
        category_guid = BUILD_CATEGORY_GUID

    try:
        runtime.system.clear_messages(category_guid)
    except Exception:
        pass

    start = time.time()
    try:
        app.build()
    except Exception as error:
        runtime.ui.error("Build process failed: " + safe_str(error))
        return {"status": "error", "error": safe_str(error)}
    elapsed = time.time() - start

    messages = _collect_messages(runtime, category_guid)
    rows, error_count, warning_count = _format_messages(messages, app_name)

    header = "{:<90} | {:<40} | {}".format("Description", "Object", "Position")
    separator = "-" * 160
    lines = [
        "------ Build started: Application: {0} ------".format(app_name),
        header,
        separator,
    ]
    for row in rows:
        desc = row["description"]
        if len(desc) > 90:
            desc = desc[:87] + "..."
        lines.append("{:<90} | {:<40} | {}".format(desc, row["object"], row["position"]))
    footer = "Compile complete -- {0} errors, {1} warnings".format(error_count, warning_count)
    lines.append(separator)
    lines.append(footer + " (Time: {0:.2f}s)".format(elapsed))

    dump_dir = _dump_root(base_dir)
    clean_app_name = _clean_filename(app_name)
    log_path = os.path.join(dump_dir, "build_{0}.log".format(clean_app_name))
    report_path = os.path.join(dump_dir, "build_report.json")
    summary = {
        "project_name": _project_name(project),
        "application_name": app_name,
        "errors": error_count,
        "warnings": warning_count,
        "elapsed_seconds": round(elapsed, 3),
        "log_path": log_path,
        "report_path": report_path,
    }
    report = {
        "status": "success" if error_count == 0 else "failed",
        "summary": summary,
        "messages": rows,
    }
    try:
        _write_text(log_path, lines)
        _write_json(report_path, report)
        print("Build log saved to: " + log_path)
        print("Build report saved to: " + report_path)
    except Exception as error:
        print("Error saving build diagnostics: " + safe_str(error))

    print(footer + " (Time: {0:.2f}s)".format(elapsed))
    message = "{0}\nErrors: {1}\nWarnings: {2}\nTime: {3:.2f}s".format(
        app_name, error_count, warning_count, elapsed
    )
    if error_count == 0:
        runtime.ui.info(message)
    else:
        runtime.ui.error(message)
    return {"status": report["status"], "summary": summary, "report": report_path}
