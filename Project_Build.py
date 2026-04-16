# -*- coding: utf-8 -*-
"""
Project_Build.py - Trigger build in CODESYS IDE

Compiles the active application and reports errors/warnings.
"""
import os
import time
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

# --- Hidden Module Loader ---
def _load_hidden_module(name):
    """Load a .pyw module from the script directory and register it in sys.modules."""
    if name not in sys.modules:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, name + ".pyw")
        if os.path.exists(path):
            if _HAS_IMPORTLIB_UTIL:
                spec = importlib.util.spec_from_file_location(name, path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[name] = mod
                    spec.loader.exec_module(mod)
            elif _HAS_IMP:
                sys.modules[name] = imp.load_source(name, path)

# Load shared core logic
_load_hidden_module("codesys_constants")
_load_hidden_module("codesys_utils")
_load_hidden_module("codesys_ui")

from codesys_utils import safe_str, init_logging, load_base_dir, resolve_projects, update_application_count_flag

def build_project(projects_obj=None):
    """Build the active application in CODESYS and generate build.log"""
    from System import Guid

    # Resolve projects object
    projects_obj = resolve_projects(projects_obj, globals())
    
    if projects_obj is None or not projects_obj.primary:
        msg = "Error: 'projects' object not found or no project open."
        system.ui.error(msg)
        return

    if not projects_obj.primary:
        msg = "Error: No project open!"
        system.ui.error(msg)
        return

    # Find application to build
    from codesys_utils import get_project_prop
    has_multiple_apps = get_project_prop("cds-text-sync-multipleApps", False)
    
    app = None
    if has_multiple_apps:
        # Check if we should prompt for application
        try:
            APP_GUID = "639b491f-5557-464c-af91-1471bac9f549"
            apps = []
            for obj in projects_obj.primary.get_children(recursive=True):
                if hasattr(obj, 'type') and str(obj.type).lower() == APP_GUID:
                    apps.append(obj)
            
            if len(apps) > 1:
                options = [safe_str(a.get_name()) for a in apps]
                # Add "Active Application" as first option? No, better just list them.
                res = system.ui.choose("Multiple applications detected. Select application to build:", options)
                # res is usually index but in some environments/versions it's a tuple (index, label)
                try:
                    choice_idx = res[0]
                except:
                    choice_idx = res
                
                if choice_idx is not None and choice_idx >= 0:
                    app = apps[choice_idx]
                else:
                    print("Build cancelled by user.")
                    return
        except Exception as e:
            print("Selection error: " + safe_str(e))
            
    if not app:
        # Fallback to active application
        app = projects_obj.primary.active_application
        
    if not app:
        # Fallback: find first application in project
        def find_app(obj):
            for child in obj.get_children():
                if str(child.type).lower() == "6394ad93-46a4-4927-8819-c1ca8654c6ad": # Application GUID
                    return child
                res = find_app(child)
                if res: return res
            return None
        
        app = find_app(projects_obj.primary)
        
    if not app:
        msg = "Error: No active application found to build."
        system.ui.error(msg)
        return

    # CODESYS Build GUID Category
    BUILD_CATEGORY = Guid("97F48D64-A2A3-4856-B640-75C046E37EA9")
    
    print("=== Starting Project Build ===")
    update_application_count_flag()
    print("Application: " + safe_str(app.get_name()))
    
    # Clear previous build messages
    try:
        system.clear_messages(BUILD_CATEGORY)
    except:
        pass

    start_time = time.time()
    
    # Log Header for build.log
    log_lines = []
    log_lines.append("------ Build started: Application: {} ------".format(safe_str(app.get_name())))
    log_lines.append("Typify code...") # Aesthetic phase marker
    
    try:
        # Trigger Build
        app.build()
        elapsed = time.time() - start_time
        
        # Retrieve messages
        messages = system.get_message_objects(BUILD_CATEGORY)
        
        error_count = 0
        warning_count = 0
        
        # Try to get project name safely
        project_name = "Unknown Project"
        try:
            # projects.primary on some versions returns a project object whose string 
            # representation is complex. Let's try to get a clean name.
            p = projects_obj.primary
            if hasattr(p, "name"):
                project_name = safe_str(p.name)
            elif hasattr(p, "get_name"):
                project_name = safe_str(p.get_name())
            
            # If it's still a long path or object string, take the filename
            if "\\" in project_name or "/" in project_name:
                project_name = os.path.basename(project_name).replace(".project", "")
            if "Project(" in project_name:
                 # Fallback: try to find the path in the string
                 import re
                 match = re.search(r"stPath=([^,\)]+)", project_name)
                 if match:
                     project_name = os.path.basename(match.group(1)).replace(".project", "")
        except:
            pass

        app_name = safe_str(app.get_name())

        for msg in messages:
            msg_text = safe_str(msg.text)
            
            # Skip messages that are just headers/footers (avoid double logging)
            if "Build started" in msg_text or "Compile complete" in msg_text:
                continue
                
            sev = str(msg.severity)
            if "Error" in sev: error_count += 1
            if "Warning" in sev: warning_count += 1
            
            # Format ID using old-school % for maximum compatibility with IronPython
            # prefix is usually 'C', number is the code like 18
            prefix = safe_str(msg.prefix) if msg.prefix else ""
            if msg.number and msg.number > 0:
                msg_id = "%s%04d" % (prefix, msg.number)
            else:
                msg_id = prefix
                
            desc = "{}: {}".format(msg_id, msg_text)
            
            # Object information
            obj_str = "N/A"
            obj_ref = None
            if hasattr(msg, "object") and msg.object:
                try:
                    obj_ref = msg.object
                    obj_str = "{} [{}]".format(safe_str(obj_ref.get_name()), app_name)
                except:
                     obj_str = str(msg.object) if msg.object else "N/A"
                
            # Position information
            pos_str = ""
            msg_line = 0
            msg_col = 0
            section = ""
            
            # --- Attempt 1: Default calculation from 'position' index ---
            # Try to get position index
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
                    
                    # Check if index is within Declaration
                    if pos_index < len(decl_text):
                        target_text = decl_text
                        section = "(Decl)"
                    else:
                        # Assume it is in Implementation
                        rel_index = pos_index - len(decl_text)
                        target_text = impl_text
                        section = "(Impl)"
                    
                    if target_text is not None and rel_index >= 0:
                        if rel_index > len(target_text): rel_index = len(target_text)
                        part = target_text[:rel_index]
                        lines = part.split('\n')
                        msg_line = len(lines)
                        msg_col = len(lines[-1]) + 1
                except:
                    pass
            
            # --- Attempt 2: Heuristic Text Search (Override if found) ---
            # If the default calculation seems suspect or purely to improve accuracy,
            # we search for the offending code in the text.
            try:
                import re
                candidates = []
                # 1. Quoted text inside message
                candidates.extend(re.findall(r"'([^']+)'", msg_text))
                # 2. "instead of <Identifier>" pattern (common in syntax errors)
                m_instead = re.search(r"instead of\s+([a-zA-Z0-9_]+)", msg_text)
                if m_instead:
                    candidates.append(m_instead.group(1))
                    
                # Keywords that are valid standalone in Declaration (no colon needed)
                decl_keywords = {'VAR', 'END_VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'VAR_IN_OUT', 
                                 'VAR_TEMP', 'VAR_GLOBAL', 'VAR_CONFIG', 'VAR_EXTERNAL', 'VAR_STAT',
                                 'PROGRAM', 'FUNCTION_BLOCK', 'FUNCTION', 'TYPE', 'END_TYPE', 
                                 'STRUCT', 'END_STRUCT', 'PROTECTED', 'INTERNAL'}
                
                best_match = None   # (line, col, section)
                high_priority_found = False
                min_dist = 999999999
                
                for item in candidates:
                    # Allow length 1 items only if they were explicitly captured (e.g. "j" from "instead of j")
                    # But filter out extremely common delimiters if they slipped in (like , or ;) unless quoted
                    if len(item) < 1: continue
                    
                    # Regex for whole word search to avoid partial matches
                    pattern = r"\b" + re.escape(item) + r"\b"
                    
                    # --- Search Declaration ---
                    for m in re.finditer(pattern, decl_text):
                        idx = m.start()
                        
                        # Calculate Line/Col
                        part = decl_text[:idx]
                        lines = part.split('\n')
                        match_line = len(lines)
                        match_col = len(lines[-1]) + 1
                        
                        # Analyze content for High Priority (Code in Decl)
                        lines_all = decl_text.split('\n')
                        if match_line <= len(lines_all):
                            line_content = lines_all[match_line-1].strip()
                            # Check if line has colon (valid decl) or is a keyword (valid block marker)
                            has_colon = ":" in line_content
                            # Check if it starts with a keyword
                            is_keyword = any(line_content.startswith(k) for k in decl_keywords) or line_content in decl_keywords
                            
                            if not has_colon and not is_keyword:
                                # High Priority: This looks like executable code in declaration!
                                msg_line = match_line
                                msg_col = match_col
                                section = "(Decl)"
                                high_priority_found = True
                                break
                        
                        # Calculate distance to reported position (if valid)
                        # Decl index is absolute 0..len
                        dist = abs(idx - pos_index)
                        if dist < min_dist:
                            min_dist = dist
                            best_match = (match_line, match_col, "(Decl)")
                            
                    if high_priority_found: break

                    # --- Search Implementation ---
                    # Only search impl if we haven't found a High Priority Decl error
                    offset = len(decl_text)
                    for m in re.finditer(pattern, impl_text):
                        idx = m.start()
                        
                        # Calculate Line/Col
                        part = impl_text[:idx]
                        lines = part.split('\n')
                        match_line = len(lines)
                        match_col = len(lines[-1]) + 1
                        
                        # Calculate distance (Impl matches start after Decl)
                        abs_pos = offset + idx
                        dist = abs(abs_pos - pos_index)
                        
                        if dist < min_dist:
                            min_dist = dist
                            best_match = (match_line, match_col, "(Impl)")

                    if high_priority_found: break
                
                # Apply best match if no high priority one was set directly
                if not high_priority_found and best_match:
                    msg_line = best_match[0]
                    msg_col = best_match[1]
                    section = best_match[2]
                    
            except:
                pass
            
            # --- Attempt 3: Regex Parse from Message Text (Fallback) ---
            if msg_line == 0:
                import re
                line_match = re.search(r'[Ll]ine[:\s]+(\d+)', msg_text)
                if line_match:
                    msg_line = int(line_match.group(1))
                    col_match = re.search(r'[Cc]olumn[:\s]+(\d+)', msg_text)
                    if col_match:
                        msg_col = int(col_match.group(1))
            
            if msg_line > 0:
                pos_str = "Line {}, Col {} {}".format(msg_line, msg_col, section)
            
            # Sanitize description for table formatting
            # 1. Remove newlines that break the row structure
            clean_desc = desc.replace('\r', '').replace('\n', ' ')
            # 2. Truncate if too long to maintain column width (optional, but good for cleanliness)
            # if len(clean_desc) > 90: clean_desc = clean_desc[:87] + "..."
            # Actually, standard format specifier {:<90} will not truncate, it just pads. 
            # If string is longer, it overflows. Table alignment breaks.
            # So truncation is recommended for strict table.
            if len(clean_desc) > 90:
                clean_desc = clean_desc[:87] + "..."

            # Recreate table-like row for log (Removed Project Column)
            log_lines.append("{:<90} | {:<40} | {}".format(clean_desc, obj_str, pos_str))

        # --- Formatting for File Output ---
        # Add Header Table
        header = "{:<90} | {:<40} | {}".format("Description", "Object", "Position")
        separator = "-" * 160
        
        # Insert Header at the top
        log_lines.insert(0, separator)
        log_lines.insert(0, header)
        
        # Add Footer with separator
        footer = "Compile complete -- {} errors, {} warnings".format(error_count, warning_count)
        log_lines.append(separator)
        log_lines.append(footer)
        
        # Write to build_[AppName].log in base directory
        base_dir, _ = load_base_dir()
        if base_dir and os.path.exists(base_dir):
            # Sanitize app name for filename
            clean_app_name = "".join([c if c.isalnum() or c in ("-", "_") else "_" for c in app_name])
            log_filename = "build_{}.log".format(clean_app_name)
            log_path = os.path.join(base_dir, log_filename)
            try:
                import codecs
                with codecs.open(log_path, "w", "utf-8") as f:
                    f.write("\n".join(log_lines))
                print("Build log saved to: " + log_path)
            except Exception as e:
                print("Error saving build log: " + str(e))

        status = "Success" if error_count == 0 else "Failed"
        msg_title = "Build " + status
        msg_body = "{}\nErrors: {}\nWarnings: {}\nTime: {:.2f}s".format(
            app_name, error_count, warning_count, elapsed
        )
        
        print(footer + " (Time: {:.2f}s)".format(elapsed))
        
        # Feedback
        if error_count == 0:
            system.ui.info(msg_body)
        else:
            system.ui.error(msg_body)
                    
    except Exception as e:
        print("Build Error: " + str(e))
        system.ui.error("Build process failed: " + str(e))

def main(params=None):
    base_dir, error = load_base_dir()
    if error:
        pass
    
    build_project()

if __name__ == "__main__":
    main()
