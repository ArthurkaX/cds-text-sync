# -*- coding: utf-8 -*-
"""
codesys_build_operation.py - Shared build workflow for CODESYS compilation.
"""
from __future__ import print_function
import os
import time
import re
import sys

try:
    import importlib.util
    _HAS_IMPORTLIB_UTIL = True
except ImportError:
    _HAS_IMPORTLIB_UTIL = False

try:
    import imp
    _HAS_IMP = True
except ImportError:
    _HAS_IMP = False


def _load_sibling_module(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".pyw")
    if _HAS_IMPORTLIB_UTIL:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    if _HAS_IMP:
        module = imp.load_source(name, path)
        sys.modules[name] = module
        return module
    raise ImportError(name + ".pyw not found.")

from codesys_runtime import resolve_runtime
from codesys_utils import safe_str, load_base_dir, resolve_projects, update_application_count_flag
try:
    from codesys_type_profiles import PROJECT_PROPERTY_KEY
except ImportError:
    PROJECT_PROPERTY_KEY = _load_sibling_module("codesys_type_profiles").PROJECT_PROPERTY_KEY
try:
    from codesys_type_system import is_guid_kind
except ImportError:
    is_guid_kind = _load_sibling_module("codesys_type_system").is_guid_kind


def build_project(runtime=None, params=None):
    from System import Guid

    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)

    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    if not projects_obj.primary:
        message = "Error: No project open!"
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    from codesys_utils import get_project_prop
    has_multiple_apps = get_project_prop("cds-text-sync-multipleApps", False)
    profile_name = get_project_prop(PROJECT_PROPERTY_KEY)

    app = None
    if has_multiple_apps:
        try:
            apps = []
            for obj in projects_obj.primary.get_children(recursive=True):
                if hasattr(obj, "type") and is_guid_kind(str(obj.type).lower(), "application", profile_name):
                    apps.append(obj)

            if len(apps) > 1:
                options = [safe_str(a.get_name()) for a in apps]
                result = runtime.ui.choose("Multiple applications detected. Select application to build:", options)
                try:
                    choice_idx = result[0]
                except Exception:
                    choice_idx = result

                if choice_idx is not None and choice_idx >= 0:
                    app = apps[choice_idx]
                else:
                    print("Build cancelled by user.")
                    return {"status": "cancelled", "reason": "user_cancelled"}
        except Exception as error:
            print("Selection error: " + safe_str(error))

    if not app:
        app = projects_obj.primary.active_application

    if not app:
        def find_app(obj):
            for child in obj.get_children():
                if is_guid_kind(str(child.type).lower(), "application", profile_name):
                    return child
                result = find_app(child)
                if result:
                    return result
            return None

        app = find_app(projects_obj.primary)

    if not app:
        message = "Error: No active application found to build."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    build_category = Guid("97F48D64-A2A3-4856-B640-75C046E37EA9")

    print("=== Starting Project Build ===")
    update_application_count_flag()
    print("Application: " + safe_str(app.get_name()))

    try:
        runtime.system.clear_messages(build_category)
    except Exception:
        pass

    start_time = time.time()

    log_lines = []
    log_lines.append("------ Build started: Application: {} ------".format(safe_str(app.get_name())))
    log_lines.append("Typify code...")

    try:
        app.build()
        elapsed = time.time() - start_time
        messages = runtime.system.get_message_objects(build_category)

        error_count = 0
        warning_count = 0

        project_name = "Unknown Project"
        try:
            project = projects_obj.primary
            if hasattr(project, "name"):
                project_name = safe_str(project.name)
            elif hasattr(project, "get_name"):
                project_name = safe_str(project.get_name())

            if "\\" in project_name or "/" in project_name:
                project_name = os.path.basename(project_name).replace(".project", "")
            if "Project(" in project_name:
                match = re.search(r"stPath=([^,\)]+)", project_name)
                if match:
                    project_name = os.path.basename(match.group(1)).replace(".project", "")
        except Exception:
            pass

        app_name = safe_str(app.get_name())

        for msg in messages:
            msg_text = safe_str(msg.text)
            if "Build started" in msg_text or "Compile complete" in msg_text:
                continue

            severity = str(msg.severity)
            if "Error" in severity:
                error_count += 1
            if "Warning" in severity:
                warning_count += 1

            prefix = safe_str(msg.prefix) if msg.prefix else ""
            if msg.number and msg.number > 0:
                msg_id = "%s%04d" % (prefix, msg.number)
            else:
                msg_id = prefix

            description = "{}: {}".format(msg_id, msg_text)
            obj_str = "N/A"
            obj_ref = None
            if hasattr(msg, "object") and msg.object:
                try:
                    obj_ref = msg.object
                    obj_str = "{} [{}]".format(safe_str(obj_ref.get_name()), app_name)
                except Exception:
                    obj_str = str(msg.object) if msg.object else "N/A"

            pos_str = ""
            msg_line = 0
            msg_col = 0
            section = ""

            pos_index = getattr(msg, "position", -1)
            decl_text = ""
            impl_text = ""

            if obj_ref:
                if hasattr(obj_ref, "textual_declaration") and obj_ref.textual_declaration:
                    decl_text = safe_str(obj_ref.textual_declaration.text)
                if hasattr(obj_ref, "textual_implementation") and obj_ref.textual_implementation:
                    impl_text = safe_str(obj_ref.textual_implementation.text)

            if pos_index >= 0 and obj_ref:
                try:
                    target_text = None
                    rel_index = pos_index
                    if pos_index < len(decl_text):
                        target_text = decl_text
                        section = "(Decl)"
                    else:
                        rel_index = pos_index - len(decl_text)
                        target_text = impl_text
                        section = "(Impl)"

                    if target_text is not None and rel_index >= 0:
                        if rel_index > len(target_text):
                            rel_index = len(target_text)
                        part = target_text[:rel_index]
                        lines = part.split("\n")
                        msg_line = len(lines)
                        msg_col = len(lines[-1]) + 1
                except Exception:
                    pass

            try:
                candidates = []
                candidates.extend(re.findall(r"'([^']+)'", msg_text))
                instead_match = re.search(r"instead of\s+([a-zA-Z0-9_]+)", msg_text)
                if instead_match:
                    candidates.append(instead_match.group(1))

                decl_keywords = set([
                    "VAR", "END_VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
                    "VAR_TEMP", "VAR_GLOBAL", "VAR_CONFIG", "VAR_EXTERNAL", "VAR_STAT",
                    "PROGRAM", "FUNCTION_BLOCK", "FUNCTION", "TYPE", "END_TYPE",
                    "STRUCT", "END_STRUCT", "PROTECTED", "INTERNAL"
                ])

                best_match = None
                high_priority_found = False
                min_dist = 999999999

                for item in candidates:
                    if len(item) < 1:
                        continue

                    pattern = r"\b" + re.escape(item) + r"\b"

                    for match in re.finditer(pattern, decl_text):
                        idx = match.start()
                        part = decl_text[:idx]
                        lines = part.split("\n")
                        match_line = len(lines)
                        match_col = len(lines[-1]) + 1

                        lines_all = decl_text.split("\n")
                        if match_line <= len(lines_all):
                            line_content = lines_all[match_line - 1].strip()
                            has_colon = ":" in line_content
                            is_keyword = any(line_content.startswith(key) for key in decl_keywords) or line_content in decl_keywords

                            if not has_colon and not is_keyword:
                                msg_line = match_line
                                msg_col = match_col
                                section = "(Decl)"
                                high_priority_found = True
                                break

                        dist = abs(idx - pos_index)
                        if dist < min_dist:
                            min_dist = dist
                            best_match = (match_line, match_col, "(Decl)")

                    if high_priority_found:
                        break

                    offset = len(decl_text)
                    for match in re.finditer(pattern, impl_text):
                        idx = match.start()
                        part = impl_text[:idx]
                        lines = part.split("\n")
                        match_line = len(lines)
                        match_col = len(lines[-1]) + 1
                        abs_pos = offset + idx
                        dist = abs(abs_pos - pos_index)

                        if dist < min_dist:
                            min_dist = dist
                            best_match = (match_line, match_col, "(Impl)")

                    if high_priority_found:
                        break

                if not high_priority_found and best_match:
                    msg_line = best_match[0]
                    msg_col = best_match[1]
                    section = best_match[2]
            except Exception:
                pass

            if msg_line == 0:
                line_match = re.search(r"[Ll]ine[:\s]+(\d+)", msg_text)
                if line_match:
                    msg_line = int(line_match.group(1))
                    col_match = re.search(r"[Cc]olumn[:\s]+(\d+)", msg_text)
                    if col_match:
                        msg_col = int(col_match.group(1))

            if msg_line > 0:
                pos_str = "Line {}, Col {} {}".format(msg_line, msg_col, section)

            clean_desc = description.replace("\r", "").replace("\n", " ")
            if len(clean_desc) > 90:
                clean_desc = clean_desc[:87] + "..."

            log_lines.append("{:<90} | {:<40} | {}".format(clean_desc, obj_str, pos_str))

        header = "{:<90} | {:<40} | {}".format("Description", "Object", "Position")
        separator = "-" * 160

        log_lines.insert(0, separator)
        log_lines.insert(0, header)

        footer = "Compile complete -- {} errors, {} warnings".format(error_count, warning_count)
        log_lines.append(separator)
        log_lines.append(footer)

        base_dir, _ = load_base_dir()
        if base_dir and os.path.exists(base_dir):
            clean_app_name = "".join([c if c.isalnum() or c in ("-", "_") else "_" for c in app_name])
            log_filename = "build_{}.log".format(clean_app_name)
            log_path = os.path.join(base_dir, log_filename)
            try:
                import codecs
                with codecs.open(log_path, "w", "utf-8") as file_obj:
                    file_obj.write("\n".join(log_lines))
                print("Build log saved to: " + log_path)
            except Exception as error:
                print("Error saving build log: " + str(error))

        status_text = "Success" if error_count == 0 else "Failed"
        message = "{}\nErrors: {}\nWarnings: {}\nTime: {:.2f}s".format(
            app_name, error_count, warning_count, elapsed
        )

        print(footer + " (Time: {:.2f}s)".format(elapsed))

        if error_count == 0:
            runtime.ui.info(message)
        else:
            runtime.ui.error(message)

        return {
            "status": "success" if error_count == 0 else "failed",
            "summary": {
                "project_name": project_name,
                "application_name": app_name,
                "errors": error_count,
                "warnings": warning_count,
                "elapsed_seconds": round(elapsed, 3)
            }
        }

    except Exception as error:
        print("Build Error: " + str(error))
        runtime.ui.error("Build process failed: " + str(error))
        return {"status": "error", "error": safe_str(error)}


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    return build_project(runtime=runtime, params=params)
