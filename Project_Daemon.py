# -*- coding: utf-8 -*-
"""
Project_daemon.py - Background Hotkey Listener & Quick Actions for CODESYS Sync

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

def _get_captured_projects():
    """Resolve projects object using shared logic."""
    from codesys_utils import resolve_projects
    # Always try to find a fresh projects object from the environment first
    proj = resolve_projects(None, globals())
    if not proj:
        # Fallback to previously captured object
        proj = sys._codesys_daemon.get("projects")
        
    if proj:
        sys._codesys_daemon["projects"] = proj
    return proj

def _run_script_in_namespace(script_name, silent=True):
    """Execute scripts in current namespace to preserve CODESYS globals.
    
    IMPORTANT: We must use globals().copy() to inherit the full CODESYS IDE
    namespace. Scripts and their imported modules (codesys_utils, etc.) rely
    on implicit globals like 'projects', 'system', and internal engine
    references that CODESYS injects into the scripting environment.
    A clean/minimal namespace breaks these references.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, script_name)
    
    if not os.path.exists(script_path):
        print("Error: Script not found: " + script_path)
        return
        
    try:
        # Resolve projects object (may have changed since daemon started)
        projects_obj = _get_captured_projects()
        system_obj = globals().get("system")
        
        # Read the script
        with open(script_path, "r") as f:
            script_code = f.read()
        
        # Copy the full CODESYS namespace to preserve all implicit globals
        script_globals = globals().copy()
        script_globals["__name__"] = "__main__"
        script_globals["__file__"] = script_path
        script_globals["SILENT"] = silent
        
        # Explicitly inject resolved CODESYS objects
        if projects_obj:
            script_globals["projects"] = projects_obj
        if system_obj:
            script_globals["system"] = system_obj
            
        exec(script_code, script_globals)
    except Exception as e:
        print("Execution error in " + script_name + ": " + str(e))
        try:
            from codesys_ui import show_toast
            show_toast(script_name + " Failed", str(e))
        except: pass

# --- Quick Action Dashboard Form ---
class QuickActionForm(Form):
    def __init__(self):
        self.Text = "CODESYS Quick Actions"
        self.FormBorderStyle = getattr(FormBorderStyle, "None")
        self.StartPosition = FormStartPosition.CenterScreen
        self.Size = Size(350, 280)
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
                    "  [B]  Build Project (Compile)\n" \
                    "  [C]  Compare IDE vs Disk\n" \
                    "  [P]  Backup Project (.project)\n" \
                    "\n" \
                    "  [D]  Deactivate Daemon\n" \
                    "  [Esc] Cancel"
        
        lbl_help = Label()
        lbl_help.Text = help_text
        lbl_help.Location = Point(30, 50)
        lbl_help.AutoSize = True
        lbl_help.Font = Font("Consolas", 10, FontStyle.Regular)
        self.Controls.Add(lbl_help)

        # Footnote
        lbl_foot = Label()
        lbl_foot.Text = "Waiting for input..."
        lbl_foot.Location = Point(20, 250)
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
            
        # D -> Deactivate Daemon (Stop Script)
        if key == Keys.D:
            self.Close()
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
        elif key == Keys.B:
            action = "BUILD_PROJ"
        elif key == Keys.C:
            action = "COMPARE_PROJ"

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
        projects_obj = _get_captured_projects()
        system_obj = globals().get("system")
        
        if action == "EXPORT_SRC":
            # Force Source Only - Temp disable XML and Binary Backup
            from codesys_utils import set_project_prop, get_project_prop
            old_xml = get_project_prop("cds-sync-export-xml", False)
            old_backup = get_project_prop("cds-sync-backup-binary", False)
            
            set_project_prop("cds-sync-export-xml", False)
            set_project_prop("cds-sync-backup-binary", False)
            
            try:
                _run_script_in_namespace("Project_export.py", silent=True)
            finally:
                # Restore original settings
                set_project_prop("cds-sync-export-xml", old_xml)
                set_project_prop("cds-sync-backup-binary", old_backup)
            
        elif action == "IMPORT_SRC":
            _run_script_in_namespace("Project_import.py", silent=True)
            
        elif action == "EXPORT_ALL":
            # Force XML ON for this run
            from codesys_utils import set_project_prop, get_project_prop
            old_xml = get_project_prop("cds-sync-export-xml", False)
            set_project_prop("cds-sync-export-xml", True)
            try:
                _run_script_in_namespace("Project_export.py", silent=True)
            finally:
                set_project_prop("cds-sync-export-xml", old_xml)

        elif action == "BACKUP_PROJ":
             from codesys_utils import backup_project_binary
             print("Backing up .project file...")
             
             projects_obj = _get_captured_projects()
             if not projects_obj:
                 print("Error: 'projects' not available")
                 return
                 
             backup_project_binary(base_dir, projects_obj)
             try:
                 from codesys_ui import show_toast
                 show_toast("Backup Complete", "Project binary saved to /project folder")
             except: pass

        elif action == "BUILD_PROJ":
            _run_script_in_namespace("Project_build.py", silent=False)

        elif action == "COMPARE_PROJ":
            _run_script_in_namespace("Project_compare.py", silent=False)


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

            [DllImport("user32.dll")]
            public static extern bool BringWindowToTop(IntPtr hWnd);

            [DllImport("user32.dll")]
            public static extern IntPtr GetForegroundWindow();
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
                # Use reflection to call static methods
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
                # Capture previous window to restore focus later
                prev_hwnd = None
                try:
                    win32_helper = sys._codesys_daemon.get("win32_helper")
                    if win32_helper:
                        prev_hwnd = win32_helper.GetMethod("GetForegroundWindow").Invoke(None, None)
                except: pass

                # Show Dashboard
                form = QuickActionForm()
                
                # Setup focus trick on SHOWN (Load is too early)
                def on_form_shown(s, e):
                    try:
                        form.Activate()
                        win32_helper = sys._codesys_daemon.get("win32_helper")
                        if win32_helper:
                            hwnd = form.Handle
                            # Call Win32 APIs for aggressive focus
                            win32_helper.GetMethod("BringWindowToTop").Invoke(None, [hwnd])
                            win32_helper.GetMethod("SetForegroundWindow").Invoke(None, [hwnd])
                    except Exception as ex:
                        print("Focus error: " + str(ex))
                
                form.Shown += on_form_shown
                
                # ShowDialog blocks until closed
                form.ShowDialog()
                
                # Restore focus to previous window
                if prev_hwnd and win32_helper:
                    try:
                        # Small delay to let Windows process the closing animation?
                        # time.sleep(0.1) 
                        win32_helper.GetMethod("SetForegroundWindow").Invoke(None, [prev_hwnd])
                    except: pass
                    
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
