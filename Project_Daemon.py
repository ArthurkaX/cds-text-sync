# -*- coding: utf-8 -*-
"""
Project_Daemon.py - Background Hotkey Listener & Quick Actions for CODESYS Sync

- Runs in background (via hidden form polling).
- Listens for global ALT+Q keypress.
- Shows a non-blocking Quick Action Dashboard.
- Silent execution of Export/Import tasks.

Usage: Run once to Start. Run again to Stop.
"""
import sys
import os
import clr
import time

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Windows.Forms import (
    Application, Form, Label, FormBorderStyle, FormStartPosition, 
    Keys, Timer, Screen
)
from System.Drawing import Size, Point, Color, Font, FontStyle, SystemIcons

# --- Global State Management ---
if not hasattr(sys, "_codesys_daemon"):
    sys._codesys_daemon = {
        "timer": None,
        "running": False,
        "projects": None  # Will be set by Start_Daemon.py wrapper
    }

# Try to capture CODESYS global objects at runtime
# This function is called lazily when actions are executed
def try_capture_projects():
    """Attempt to capture the projects object using multiple strategies"""
    
    # Strategy 1: Check if already captured by wrapper
    if sys._codesys_daemon.get("projects"):
        return sys._codesys_daemon["projects"]
    
    # Strategy 2: Check __main__ module's globals
    try:
        import __main__
        if hasattr(__main__, 'projects'):
            return __main__.projects
    except:
        pass
    
    # Strategy 3: Search sys.modules for a module with 'projects'
    try:
        for module_name, module in sys.modules.items():
            if hasattr(module, 'projects'):
                proj = getattr(module, 'projects')
                # Verify it's the right type (has .primary attribute)
                if hasattr(proj, 'primary'):
                    return proj
    except:
        pass
    
    return None

# --- Quick Action Dashboard Form ---
class QuickActionForm(Form):
    def __init__(self):
        self.Text = "CODESYS Quick Actions"
        self.FormBorderStyle = FormBorderStyle.None
        self.StartPosition = FormStartPosition.CenterScreen
        self.Size = Size(350, 220)
        self.BackColor = Color.FromArgb(30, 30, 30) # Dark Theme
        self.ForeColor = Color.White
        self.TopMost = True
        self.KeyPreview = True
        self.Opacity = 0.95
        
        # Title
        lbl = Label()
        lbl.Text = "CODESYS Sync Actions"
        lbl.Location = Point(20, 15)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 12, FontStyle.Bold)
        lbl.ForeColor = Color.FromArgb(0, 122, 204) # Blue accent
        self.Controls.Add(lbl)

        # Instructions
        help_text = "Press key to execute:\n\n" \
                    "  [E]  Export Source (Silent)\n" \
                    "  [I]  Import Source (Silent)\n" \
                    "  [X]  Export All (with XML)\n" \
                    "  [P]  Backup Project (.project)\n" \
                    "\n" \
                    "  [Q]  Cancel / Quit"
        
        lbl_help = Label()
        lbl_help.Text = help_text
        lbl_help.Location = Point(30, 50)
        lbl_help.AutoSize = True
        lbl_help.Font = Font("Consolas", 10, FontStyle.Regular)
        self.Controls.Add(lbl_help)

        # Footnote
        lbl_foot = Label()
        lbl_foot.Text = "Waiting for input..."
        lbl_foot.Location = Point(20, 190)
        lbl_foot.AutoSize = True
        lbl_foot.ForeColor = Color.Gray
        self.Controls.Add(lbl_foot)

        # Event Handlers
        self.KeyDown += self.on_key_down
        self.Deactivate += self.on_deactivate

    def on_deactivate(self, sender, args):
        self.Close()

    def on_key_down(self, sender, args):
        key = args.KeyCode
        
        # ESC -> Close Menu (Cancel)
        if key == Keys.Escape:
            self.Close()
            return
            
        # Q -> Stop Daemon entirely (Quit App)
        if key == Keys.Q:
            self.Close()
            # Stop the daemon properly
            stop_daemon()
            return
        
        action = None
        if key == Keys.E:
            action = "EXPORT_SRC"
        elif key == Keys.I:
            action = "IMPORT_SRC"
        elif key == Keys.X:
            action = "EXPORT_ALL"
        elif key == Keys.P:
            action = "BACKUP_PROJ"

        if action:
            self.Hide() # Hide immediately to show we are working
            # Force UI update so hide happens
            Application.DoEvents() 
            
            try:
                self.execute_action(action)
            except Exception as e:
                # Show error if script failed
                print("Error executing action: " + str(e))
                # Re-show form if error? Or just toast?
                try:
                    from codesys_ui import show_toast
                    show_toast("Error", "Script failed: " + str(e))
                except:
                    pass
            finally:
                self.Close()

    def execute_action(self, action):
        from codesys_utils import load_base_dir
        base_dir, error = load_base_dir()
        if error:
            print("Base dir error: " + error)
            return
        
        print("Executing " + action + "...")
        
        # Get script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Try to resolve projects/system objects for the script namespace
        projects_obj = sys._codesys_daemon.get("projects")
        if not projects_obj:
            projects_obj = try_capture_projects()
            if projects_obj:
                sys._codesys_daemon["projects"] = projects_obj
        
        system_obj = globals().get("system")
        
        if action == "EXPORT_SRC":
            # Force Source Only - Temp disable XML and Binary Backup
            from codesys_utils import set_project_prop, get_project_prop
            old_xml = get_project_prop("cds-sync-export-xml", False)
            old_backup = get_project_prop("cds-sync-backup-binary", False)
            
            set_project_prop("cds-sync-export-xml", False)
            set_project_prop("cds-sync-backup-binary", False)
            
            # Execute Project_export.py in current namespace to preserve CODESYS globals
            export_script = os.path.join(script_dir, "Project_export.py")
            try:
                # Read the script
                with open(export_script, "r") as f:
                    script_code = f.read()
                
                # Create a namespace with the necessary globals
                script_globals = globals().copy()
                script_globals["__name__"] = "__main__"
                script_globals["__file__"] = export_script
                script_globals["SILENT"] = True # Force silent mode
                
                # Explicitly inject CODESYS objects if we found them
                if projects_obj:
                    script_globals["projects"] = projects_obj
                if system_obj:
                    script_globals["system"] = system_obj
                
                # Execute in that namespace
                exec(script_code, script_globals)
                
            except Exception as e:
                print("Export error: " + str(e))
                try:
                    from codesys_ui import show_toast
                    show_toast("Export Failed", str(e))
                except:
                    pass
            finally:
                # Restore original settings
                set_project_prop("cds-sync-export-xml", old_xml)
                set_project_prop("cds-sync-backup-binary", old_backup)
            
        elif action == "IMPORT_SRC":
            # Execute Project_import.py in current namespace
            import_script = os.path.join(script_dir, "Project_import.py")
            try:
                with open(import_script, "r") as f:
                    script_code = f.read()
                
                script_globals = globals().copy()
                script_globals["__name__"] = "__main__"
                script_globals["__file__"] = import_script
                script_globals["SILENT"] = True # Force silent mode
                
                # Explicitly inject CODESYS objects if we found them
                if projects_obj:
                    script_globals["projects"] = projects_obj
                if system_obj:
                    script_globals["system"] = system_obj
                
                exec(script_code, script_globals)
                
            except Exception as e:
                print("Import error: " + str(e))
                try:
                    from codesys_ui import show_toast
                    show_toast("Import Failed", str(e))
                except:
                    pass
            
        elif action == "EXPORT_ALL":
            # Force XML ON for this run
            from codesys_utils import set_project_prop, get_project_prop
            
            old_xml = get_project_prop("cds-sync-export-xml", False)
            set_project_prop("cds-sync-export-xml", True)
            
            try:
                export_script = os.path.join(script_dir, "Project_export.py")
                with open(export_script, "r") as f:
                    script_code = f.read()
                
                script_globals = globals().copy()
                script_globals["__name__"] = "__main__"
                script_globals["__file__"] = export_script
                script_globals["SILENT"] = True # Force silent mode
                
                # Explicitly inject CODESYS objects if we found them
                if projects_obj:
                    script_globals["projects"] = projects_obj
                if system_obj:
                    script_globals["system"] = system_obj
                
                exec(script_code, script_globals)
            finally:
                set_project_prop("cds-sync-export-xml", old_xml)

        elif action == "BACKUP_PROJ":
             from codesys_utils import backup_project_binary
             print("Backing up .project file...")
             
             # Get projects from globals (should be available in Daemon's namespace)
             projects_obj = globals().get("projects")
             if not projects_obj:
                 print("Error: 'projects' not available")
                 return
                 
             backup_project_binary(base_dir, projects_obj)
             try:
                 from codesys_ui import show_toast
                 show_toast("Backup Complete", "Project binary saved to /project folder")
             except: pass


# --- Hotkey Polling Logic ---
# Since we cannot easily specificy P/Invoke in pure IronPython script without compiling C# class,
# We rely on System.Windows.Forms.Control.ModifierKeys check in a Timer loop.
# This works ONLY if the script or CODESYS has focus? No, ModifierKeys is static but often Application bound.
# BUT: GetAsyncKeyState IS available via ctypes if python standard lib is present.
# IronPython often does NOT have ctypes standard lib.
#
# Alternative: Use a hidden form that uses RegisterHotKey via C# snippet compilation.
# This is the most robust way.

def create_hotkey_listener():
    # Implementation of a polling listener using C# snippet for GetAsyncKeyState
    # This avoids ctypes dependency issues
    import clr
    try:
        clr.AddReference("System.Runtime.InteropServices")
        pass
    except:
        pass

    # We can try to compile a small class to call user32
    # If that fails, we are stuck.
    # Let's assume we can use the Timer + Control.ModifierKeys trick MIGHT work 
    # but usually only when app is focused.
    # 
    # Actually, the user asked for "background even if changed desktop".
    # P/Invoke is required.
    
    # Simple Polling with ctypes (if available)
    try:
        import ctypes
        GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
        
        def check_hotkey():
            # Check ALT (VK_MENU=0x12) and Q (0x51)
            # GetAsyncKeyState returns short. MSB set if down.
            
            # 0x8000 is the mask for "Currently Down"
            alt_down = (GetAsyncKeyState(0x12) & 0x8000) != 0
            q_down = (GetAsyncKeyState(0x51) & 0x8000) != 0
            
            return alt_down and q_down
            
    except:
        # Fallback: We might not be able to listen globally easily.
        # Let's try to load a C# class that does P/Invoke.
        # This works in CODESYS usually.
        src = """
        using System;
        using System.Runtime.InteropServices;
        public class Win32 {
            [DllImport("user32.dll")]
            public static extern short GetAsyncKeyState(int vKey);
            
            [DllImport("user32.dll")]
            public static extern bool SetForegroundWindow(IntPtr hWnd);
        }
        """
        import clr
        try:
            # CodeDom provider usage
            from Microsoft.CSharp import CSharpCodeProvider
            from System.CodeDom.Compiler import CompilerParameters
            
            params = CompilerParameters()
            params.GenerateInMemory = True
            
            provider = CSharpCodeProvider()
            res = provider.CompileAssemblyFromSource(params, [src])
            
            if res.Errors.Count > 0:
                print("C# Compile Error: " + str(res.Errors[0]))
                return None
            
            assembly = res.CompiledAssembly
            win32_type = assembly.GetType("Win32")
            
            # Store win32 helper globally in the daemon state
            sys._codesys_daemon["win32_helper"] = win32_type
            
            def check_hotkey():
                # VK_MENU=0x12, Q=0x51
                state_alt = win32_type.GetMethod("GetAsyncKeyState").Invoke(None, [0x12])
                state_q = win32_type.GetMethod("GetAsyncKeyState").Invoke(None, [0x51])
                
                alt_down = (int(state_alt) & 0x8000) != 0
                q_down = (int(state_q) & 0x8000) != 0
                return alt_down and q_down
                
        except Exception as e:
            print("Failed to compile Win32 helper: " + str(e))
            return None

    return check_hotkey

# --- Main Logic ---

def on_tick(sender, args):
    # Check hotkey
    try:
        # Safety check: if daemon was stopped, timer might be None
        timer = sys._codesys_daemon.get("timer")
        if not timer:
            return
            
        check_func = sys._codesys_daemon.get("check_func")
        if check_func and check_func():
            # Hotkey detected!
            timer.Stop()
            
            try:
                # Show Dashboard
                form = QuickActionForm()
                
                # Setup focus trick on Load
                def on_form_load(s, e):
                    try:
                        win32_helper = sys._codesys_daemon.get("win32_helper")
                        if win32_helper:
                            win32_helper.GetMethod("SetForegroundWindow").Invoke(None, [form.Handle])
                    except: pass
                
                form.Load += on_form_load
                
                # ShowDialog blocks until closed
                form.ShowDialog()
            except Exception as e:
                print("Dashboard Error: " + str(e))
            
            # Wait for keys to be released to prevent immediate re-trigger
            time.sleep(0.5)
            
            # ALWAYS attempt to resume if we haven't been stopped globally
            if sys._codesys_daemon.get("timer") and sys._codesys_daemon.get("running"):
                sys._codesys_daemon["timer"].Start()
    except Exception as e:
        print("Daemon Tick Error: " + str(e))
        # Don't stop the timer here unless it's a fatal error
        # Instead, just try to make sure it's running for the next tick
        try:
            t = sys._codesys_daemon.get("timer")
            if t and sys._codesys_daemon.get("running"):
                t.Start()
        except: pass

def start_daemon():
    print("Starting Daemon...")
    check_func = create_hotkey_listener()
    
    if not check_func:
        system.ui.error("Could not initialize global key listener.\n(C# Compiler or P/Invoke failed).")
        return

    timer = Timer()
    timer.Interval = 100 # 10Hz check
    timer.Tick += on_tick
    timer.Start()
    
    sys._codesys_daemon["timer"] = timer
    sys._codesys_daemon["check_func"] = check_func
    sys._codesys_daemon["running"] = True
    
    print("Daemon Started. Press ALT+Q to open dashboard.")
    
    # Notify user
    try:
        from codesys_ui import show_toast
        show_toast("Daemon Started", "Listening for ALT+Q...")
    except:
        pass

def stop_daemon():
    if sys._codesys_daemon["timer"]:
        sys._codesys_daemon["timer"].Stop()
        sys._codesys_daemon["timer"].Dispose()
        sys._codesys_daemon["timer"] = None
    
    sys._codesys_daemon["running"] = False
    print("Daemon Stopped.")
    
    try:
        from codesys_ui import show_toast
        show_toast("Daemon Stopped", "Background listener deactivated.")
    except:
        pass

def main():
    if sys._codesys_daemon["running"]:
        stop_daemon()
    else:
        start_daemon()

if __name__ == "__main__":
    main()
