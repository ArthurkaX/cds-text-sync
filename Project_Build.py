# -*- coding: utf-8 -*-
"""
Project_Build.py - Trigger build in CODESYS IDE

Compiles the active application and reports errors/warnings.
"""
import time
import sys
from codesys_utils import safe_str, init_logging, load_base_dir

def build_project(projects_obj=None, silent=False):
    """Build the active application in CODESYS and generate build.log"""
    from System import Guid

    # Resolve projects object
    if projects_obj is None:
        projects_obj = globals().get("projects")
        
    if projects_obj is None:
        try:
            import __main__
            projects_obj = getattr(__main__, "projects", None)
        except:
            pass
            
    if projects_obj is None:
        msg = "Error: 'projects' object not found."
        if not silent:
            system.ui.error(msg)
        else:
            print(msg)
        return

    if not projects_obj.primary:
        msg = "Error: No project open!"
        if not silent:
            system.ui.error(msg)
        else:
            print(msg)
        return

    # Find active application
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
        if not silent:
            system.ui.error(msg)
        else:
            print(msg)
        return

    # CODESYS Build GUID Category
    BUILD_CATEGORY = Guid("97F48D64-A2A3-4856-B640-75C046E37EA9")
    
    print("=== Starting Project Build ===")
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
        
        project_name = safe_str(projects_obj.primary.get_name())
        app_name = safe_str(app.get_name())

        for msg in messages:
            sev = str(msg.severity)
            if "Error" in sev: error_count += 1
            if "Warning" in sev: warning_count += 1
            
            # Format: [ID]: [Text] | [Project] | [Object] | [Position]
            # Example ID: C0018
            msg_id = safe_str(msg.prefix) + "{:04d}".format(msg.number) if msg.number > 0 else safe_str(msg.prefix)
            desc = "{}: {}".format(msg_id, safe_str(msg.text))
            
            obj_str = "N/A"
            if msg.object:
                try:
                    obj_str = "{} [{}]".format(safe_str(msg.object.get_name()), app_name)
                except: pass
                
            pos_str = ""
            if msg.line > 0:
                pos_str = "Line {}, Column {}".format(msg.line, msg.column)
            
            # Recreate table-like row for log
            log_lines.append("{:<80} | {:<15} | {:<40} | {}".format(desc, project_name, obj_str, pos_str))

        # Footer
        footer = "Compile complete -- {} errors, {} warnings".format(error_count, warning_count)
        log_lines.append(footer)
        
        # Write to build.log in base directory
        base_dir, _ = load_base_dir()
        if base_dir and os.path.exists(base_dir):
            log_path = os.path.join(base_dir, "build.log")
            try:
                import codecs
                with codecs.open(log_path, "w", "utf-8") as f:
                    f.write("\n".join(log_lines))
                print("Build log saved to: " + log_path)
            except Exception as e:
                print("Error saving build.log: " + str(e))

        status = "Success" if error_count == 0 else "Failed"
        msg_title = "Build " + status
        msg_body = "{}\nErrors: {}\nWarnings: {}\nTime: {:.2f}s".format(
            app_name, error_count, warning_count, elapsed
        )
        
        print(footer + " (Time: {:.2f}s)".format(elapsed))
        
        # Feedback
        try:
            from codesys_ui import show_toast
            show_toast(msg_title, msg_body)
        except:
            if not silent:
                if error_count == 0:
                    system.ui.info(msg_body)
                else:
                    system.ui.error(msg_body)
                    
    except Exception as e:
        print("Build Error: " + str(e))
        if not silent:
            system.ui.error("Build process failed: " + str(e))

def main():
    base_dir, error = load_base_dir()
    if error:
        # Build doesn't strictly need base_dir, but we check for consistency
        pass
    
    # Check if we are being run in silent mode (e.g. from Daemon)
    is_silent = globals().get("SILENT", False)
    
    build_project(silent=is_silent)

if __name__ == "__main__":
    main()
