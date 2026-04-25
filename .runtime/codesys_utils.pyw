# -*- coding: utf-8 -*-
"""
codesys_utils.py - Shared utility functions for CODESYS scripts

Contains common utility functions used across export, import, and sync scripts.
"""
import os
import codecs
import json
import zlib
import csv
import sys
import traceback
import time
import tempfile
import threading
import shutil

try:
    import clr
    clr.AddReference("System")
    from System import Environment
    from System.Diagnostics import Process, FileVersionInfo
except:
    Environment = None
    Process = None
    FileVersionInfo = None

# --- Global Thread Lock ---
_metadata_thread_lock = threading.Lock()
from codesys_constants import IMPL_MARKER, FORBIDDEN_CHARS, PROPERTY_GET_MARKER, PROPERTY_SET_MARKER

FOLDER_GUID = "738bea1e-99bb-4f04-90bb-a7a567e74e3a"

# Cache version — bump when format changes to force full rebuild
CACHE_VERSION = "3.1"  # 3.1: hashes now include build_properties (exclude_from_build, etc.)


# --- Logging System ---
# --- Logging System ---
class Logger:
    def __init__(self):
        self.log_file = None
        self.is_final = False
        self.logging_enabled = None  # None = not yet checked, True/False = override
        self.info_enabled = True
        self.console_silent = False
        
    def _initialize(self, base_dir=None):
        if not self.logging_enabled:
            return

        # If explicitly providing base_dir, override everything
        if base_dir:
            self.log_file = os.path.join(base_dir, "sync_debug.log")
            self.is_final = True
            return

        # If we already have a final path, don't change it unless forced
        if self.is_final:
            return

        # Try to find current project base_dir from properties
        # This can "upgrade" a non-final path to a final one
        try:
            # In CODESYS, 'projects' is a global object provided by the environment
            if projects.primary:
                info = projects.primary.get_project_info()
                props = info.values if hasattr(info, "values") else info
                if "cds-sync-folder" in props:
                    folder = props["cds-sync-folder"]
                    if folder and os.path.exists(folder):
                        self.log_file = os.path.join(folder, "sync_debug.log")
                        self.is_final = True # We found the real path
                        return
        except:
            pass

        # Fallback to local dir if we still don't have a path
        if not self.log_file:
            try:
                # Use temp directory to avoid cluttering ScriptDir
                self.log_file = os.path.join(tempfile.gettempdir(), "cds_sync_debug.log")
            except:
                pass
            # allow overwriting later since this is a fallback
            self.is_final = False

    def log(self, level, message, include_traceback=False):
        if level == "INFO" and (not self.info_enabled or self.console_silent):
            return

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = "[%s] [%s] %s\n" % (timestamp, level, message)
        
        if include_traceback:
            log_entry += traceback.format_exc() + "\n"
            
        print("[%s] %s" % (level, message))
        
        if not self.logging_enabled:
            return

        self._initialize()
        if not self.log_file:
            return

        try:
            with codecs.open(self.log_file, "a", "utf-8") as f:
                f.write(log_entry)
        except:
            pass

_logger = Logger()

def log_info(message):
    _logger.log("INFO", message)

def log_warning(message):
    _logger.log("WARNING", message)

def set_info_logging(enabled):
    """Enable or suppress INFO-level console/log output."""
    _logger.info_enabled = bool(enabled)


def set_console_silence(enabled):
    """Force console INFO output off/on without touching file logging."""
    _logger.console_silent = bool(enabled)

def init_logging(base_dir):
    """Explicitly set the logging directory and check if logging is enabled"""
    enabled = get_project_prop("cds-sync-enable-logging", False)
    _logger.logging_enabled = enabled
    if enabled and base_dir and os.path.exists(base_dir):
        _logger._initialize(base_dir)

def is_logging_enabled():
    """Check if file logging is enabled via project settings"""
    if _logger.logging_enabled is None:
        _logger.logging_enabled = get_project_prop("cds-sync-enable-logging", False)
    return _logger.logging_enabled

def log_error(message, critical=False):
    _logger.log("ERROR", message, include_traceback=True)
    if critical:
        try:
            import system
            if _logger.logging_enabled:
                system.ui.error("CRITICAL ERROR: " + message + "\n\nSee sync_debug.log for details.")
            else:
                system.ui.error("CRITICAL ERROR: " + message)
        except:
            pass

# --- Utility Functions ---

def is_valid_projects(obj):
    """Check if the projects object is valid and functional."""
    if obj is None:
        return False
    try:
        # Accessing .primary is the ultimate test. 
        # If it's a stale/dead object from a previous run, this throws.
        _ = obj.primary
        return True
    except:
        return False


def resolve_projects(projects_obj=None, caller_globals=None):
    """
    Ensure we have a reference to the CODESYS projects engine.
    
    Tries multiple strategies:
    1. Use the explicitly passed object (if valid)
    2. Check caller's globals
    3. Check __main__ module
    4. Search sys.modules for an object with .primary attribute
    
    Returns the projects object or None.
    """
    if is_valid_projects(projects_obj):
        return projects_obj
    
    # Strategy 1: caller globals
    if caller_globals and "projects" in caller_globals:
        candidate = caller_globals["projects"]
        if is_valid_projects(candidate):
            return candidate
    
    # Strategy 2: __main__
    try:
        import __main__
        obj = getattr(__main__, "projects", None)
        if is_valid_projects(obj):
            return obj
    except:
        pass
    
    # Strategy 3: sys.modules scan
    try:
        # sys is already imported at top level
        # Sort modules to prioritize those that might be "more" main
        for module in sys.modules.values():
            if hasattr(module, "projects"):
                candidate = getattr(module, "projects")
                if is_valid_projects(candidate):
                    return candidate
    except:
        pass
    
    return None


def is_valid_system(obj):
    """Check if the system object is valid and functional."""
    if obj is None:
        return False
    try:
        # Accessing .ui is a good test for the CODESYS system object
        _ = obj.ui
        return True
    except:
        return False


def resolve_system(caller_globals=None):
    """Resolve the CODESYS 'system' global object."""
    # Strategy 1: caller globals
    if caller_globals and "system" in caller_globals:
        candidate = caller_globals["system"]
        if is_valid_system(candidate):
            return candidate
            
    # Strategy 2: __main__
    try:
        import __main__
        obj = getattr(__main__, "system", None)
        if is_valid_system(obj):
            return obj
    except:
        pass
        
    # Strategy 3: sys.modules scan
    try:
        if "system" in sys.modules:
            return sys.modules["system"]
        for module in sys.modules.values():
            if hasattr(module, "system"):
                candidate = getattr(module, "system")
                if is_valid_system(candidate):
                    return candidate
    except:
        pass
        
    return None


def get_quick_ide_hash(obj, is_xml):
    """
    Quickly calculate identification hash from IDE object without full export.
    Includes build_properties (sync attributes) so attribute-only changes
    invalidate the cache.
    Returns None if full export is mandatory (e.g. XML types).
    """
    if is_xml:
        return None  # XML requires full export for stable comparison
        
    try:
        try:
            from codesys_type_profiles import PROJECT_PROPERTY_KEY
            from codesys_type_system import resolve_runtime_object
            obj_kind = resolve_runtime_object(obj, get_project_prop(PROJECT_PROPERTY_KEY)).get("semantic_kind")
        except:
            obj_kind = None
        
        # Extract decl and impl
        decl = obj.textual_declaration.text if hasattr(obj, 'has_textual_declaration') and obj.has_textual_declaration else None
            
        if obj_kind == "property":
            # Special Case: Properties combine Get and Set children
            get_impl = None
            set_impl = None
            try:
                for child in obj.get_children():
                    c_name = child.get_name().lower()
                    if c_name == "get":
                        c_decl = child.textual_declaration.text if child.has_textual_declaration else ""
                        c_impl = child.textual_implementation.text if child.has_textual_implementation else ""
                        get_impl = format_st_content(c_decl, c_impl)
                    elif c_name == "set":
                        c_decl = child.textual_declaration.text if child.has_textual_declaration else ""
                        c_impl = child.textual_implementation.text if child.has_textual_implementation else ""
                        set_impl = format_st_content(c_decl, c_impl)
            except: pass
            
            content = format_property_content(decl, get_impl, set_impl)
        else:
            # Standard POU/GVL/DUT
            impl = obj.textual_implementation.text if hasattr(obj, 'has_textual_implementation') and obj.has_textual_implementation else None
            if decl is not None or impl is not None:
                from codesys_type_system import can_have_implementation_kind
                can_have_impl = can_have_implementation_kind(obj_kind)
                content = format_st_content(decl, impl, can_have_impl)
            else:
                return None

        # Include build attributes in the hash so attribute-only changes
        # (like toggling Exclude from build) invalidate the cache
        attrs = read_ide_attrs(obj)
        return build_state_hash(content, attrs)
    except Exception as e:
        log_warning("Quick hash failed: " + str(e))
        
    return None


def calculate_hash(content):
    """Calculate CRC32 checksum of string content (faster than SHA256)"""
    if content is None:
        return ""
    if isinstance(content, str):
        content = content.encode('utf-8')
    # CRC32 returns signed int, convert to unsigned and format as hex
    crc = zlib.crc32(content) & 0xFFFFFFFF
    return "%08X" % crc


def safe_str(value):
    """Safely convert value to string, handling Unicode in Python 2.7"""
    if value is None:
        return ""
    try:
        if sys.version_info[0] < 3:
            if isinstance(value, unicode):
                return value
            return unicode(value)
        return str(value)
    except:
        return "N/A"


def get_process_version_info():
    result = {
        "process_name": None,
        "exe_path": None,
        "product_name": None,
        "product_version": None,
        "file_version": None,
        "company_name": None,
        "main_window_title": None,
        "is_64bit_process": None
    }

    if not Process:
        return result

    try:
        proc = Process.GetCurrentProcess()
        result["process_name"] = safe_str(getattr(proc, "ProcessName", None)) or None
        result["main_window_title"] = safe_str(getattr(proc, "MainWindowTitle", None)) or None
        result["is_64bit_process"] = bool(Environment.Is64BitProcess) if Environment else None

        exe_path = None
        try:
            exe_path = safe_str(proc.MainModule.FileName) or None
        except:
            exe_path = None
        result["exe_path"] = exe_path

        if exe_path and FileVersionInfo:
            try:
                info = FileVersionInfo.GetVersionInfo(exe_path)
                result["product_name"] = safe_str(getattr(info, "ProductName", None)) or None
                result["product_version"] = safe_str(getattr(info, "ProductVersion", None)) or None
                result["file_version"] = safe_str(getattr(info, "FileVersion", None)) or None
                result["company_name"] = safe_str(getattr(info, "CompanyName", None)) or None
            except:
                pass
    except:
        pass

    return result


def get_detected_codesys_version(system_obj=None):
    candidates = []

    if not system_obj:
        system_obj = resolve_system()

    if system_obj:
        for attr_name in ("version", "Version", "product_version", "ProductVersion"):
            try:
                value = safe_str(getattr(system_obj, attr_name, None)).strip()
            except:
                value = ""
            if value and value not in ("N/A", "None"):
                candidates.append(value)

    process_info = get_process_version_info()
    for key in ("product_version", "file_version"):
        value = safe_str(process_info.get(key)).strip()
        if value and value not in ("N/A", "None"):
            candidates.append(value)

    return candidates[0] if candidates else "N/A"


def _get_semantic_kind(obj, profile_name=None):
    """Resolve an object's semantic kind using the active profile."""
    try:
        from codesys_type_profiles import PROJECT_PROPERTY_KEY
        from codesys_type_system import resolve_runtime_object
        if profile_name is None:
            profile_name = get_project_prop(PROJECT_PROPERTY_KEY)
        return resolve_runtime_object(obj, profile_name).get("semantic_kind")
    except:
        try:
            return safe_str(getattr(obj, "type", None))
        except:
            return ""


def determine_object_type(content):
    """Determine CODESYS object type from ST content.

    Returns the semantic kind instead of a raw GUID so callers can route
    through the profile-aware type system.
    """
    from codesys_type_system import determine_semantic_kind
    return determine_semantic_kind(content)


def clean_filename(name):
    """Clean filename from invalid characters"""
    clean_name = name
    for char in FORBIDDEN_CHARS:
        clean_name = clean_name.replace(char, "_")
    return clean_name


def get_project_prop(key, default=None):
    """Safely get a project property using the appropriate API for this CODESYS version."""
    try:
        projects_obj = resolve_projects()
        if not projects_obj or not projects_obj.primary:
            return default
            
        proj = projects_obj.primary
        
        info = proj.get_project_info() if hasattr(proj, "get_project_info") else getattr(proj, "project_info", None)
        if not info: return default
        
        props = info.values if hasattr(info, "values") else info
        try:
            val = props[key]
            if val is None: return default
            # Auto-convert types if they look like numbers or booleans
            s_val = str(val)
            if s_val.lower() == "true": return True
            if s_val.lower() == "false": return False
            if s_val.isdigit(): return int(s_val)
            return s_val
        except:
            return default
    except:
        return default

def set_project_prop(key, value):
    """Safely set a project property."""
    try:
        projects_obj = resolve_projects()
        if not projects_obj or not projects_obj.primary:
            return False
            
        proj = projects_obj.primary
        
        info = proj.get_project_info() if hasattr(proj, "get_project_info") else getattr(proj, "project_info", None)
        if not info: return False
        
        props = info.values if hasattr(info, "values") else info
        props[key] = str(value)
        return True
    except:
        return False

def update_application_count_flag():
    """Count internal 'Application' objects and set 'boolean' property to True if > 1."""
    from codesys_type_profiles import PROJECT_PROPERTY_KEY
    from codesys_type_system import resolve_runtime_object

    try:
        proj = None
        try:
            import __main__
            if hasattr(__main__, 'projects'): proj = __main__.projects.primary
        except: pass
        if not proj:
            try: proj = projects.primary
            except: pass
        
        if not proj: return False
        
        profile_name = get_project_prop(PROJECT_PROPERTY_KEY)

        # Count all application objects using the selected type profile.
        all_objs = proj.get_children(recursive=True)
        app_count = 0

        for obj in all_objs:
            try:
                if resolve_runtime_object(obj, profile_name).get("semantic_kind") == "application":
                    app_count += 1
            except:
                pass
        
        has_multiple_apps = (app_count > 1)
        log_info("Application count summary: Found %d applications. Setting 'cds-text-sync-multipleApps' flag to %s" % (app_count, str(has_multiple_apps)))
        
        # Cleanup old 'boolean' flag if it exists (prevents clutter)
        try:
            info = proj.get_project_info() if hasattr(proj, "get_project_info") else getattr(proj, "project_info", None)
            props = info.values if hasattr(info, "values") else info
            if "boolean" in props:
                del props["boolean"]
        except:
            pass
            
        return set_project_prop("cds-text-sync-multipleApps", has_multiple_apps)
    except Exception as e:
        log_error("Failed to update application count flag: " + safe_str(e))
        return False

def load_base_dir():
    """Load base directory from the project property 'cds-sync-folder'.
    
    Supports both absolute and relative paths:
    - Absolute paths: Used as-is (e.g., C:\\MySync\\)
    - Relative paths: Resolved relative to project file location (e.g., ./ or ./folderName/)
    
    If the directory doesn't exist, it will be created automatically.
    """
    base_dir = get_project_prop("cds-sync-folder")
    if not base_dir:
        return None, "Project sync directory not set!\nPlease run 'Project_directory.py' or add 'cds-sync-folder' property in Project Information > Properties."
    
    # Check if path is relative
    is_relative = base_dir.startswith('.' + os.sep) or base_dir.startswith('./') or base_dir.startswith('.\\') or base_dir == '.'
    
    # Resolve relative paths against project file location
    if is_relative:
        try:
            projects_obj = resolve_projects()
            proj = projects_obj.primary if projects_obj else None
            
            if not proj or not hasattr(proj, 'path'):
                return None, "Cannot resolve relative path: project path not available.\n\nRelative path: " + base_dir
            
            # Get directory containing the project file
            project_file_path = safe_str(proj.path)
            project_dir = os.path.dirname(project_file_path)
            
            # Resolve relative path
            # Normalize the base_dir first (convert / to os.sep)
            normalized_base = base_dir.replace('/', os.sep).replace('\\', os.sep)
            
            # Join and normalize
            base_dir = os.path.normpath(os.path.join(project_dir, normalized_base))
            
            log_info("Resolved relative path '%s' to '%s' (project dir: '%s')" % (normalized_base, base_dir, project_dir))
        except Exception as e:
            log_error("Error resolving relative path: " + safe_str(e))
            return None, "Failed to resolve relative path: " + base_dir + "\n\nError: " + safe_str(e)
    
    # Check for PC mismatch only for ABSOLUTE paths
    # For relative paths, we skip this check to facilitate teamwork and portability
    if not is_relative:
        sync_pc = get_project_prop("cds-sync-pc")
        try:
            import socket
            current_pc = socket.gethostname()
            log_info("PC Check: Current PC='%s', Sync PC='%s'" % (safe_str(current_pc), safe_str(sync_pc)))
            
            if sync_pc and current_pc and safe_str(sync_pc) != safe_str(current_pc):
                message = "Computer Mismatch Detected!\n\n"
                message += "This project was last synced on: " + safe_str(sync_pc) + "\n"
                message += "Current computer: " + safe_str(current_pc) + "\n\n"
                message += "The saved sync path may be invalid for this machine:\n"
                message += safe_str(base_dir) + "\n\n"
                message += "Would you like to re-configure the sync folder for this PC?"
                
                # Try to find 'system' object for UI
                sys_ui = None
                try:
                    if "system" in globals(): sys_ui = globals()["system"].ui
                    else: 
                        import __main__
                        if hasattr(__main__, "system"): sys_ui = __main__.system.ui
                except: pass
                
                if sys_ui:
                    from codesys_ui import ask_yes_no_cancel
                    ans = ask_yes_no_cancel("Computer Mismatch Detected", message)
                    
                    if ans == "yes":
                        try:
                            import Project_directory
                            Project_directory.set_base_directory()
                            base_dir = get_project_prop("cds-sync-folder")
                            # Re-resolve if it's still relative after reconfiguration
                            if base_dir and (base_dir.startswith('.' + os.sep) or base_dir.startswith('./') or base_dir.startswith('.\\') or base_dir == '.'):
                                try:
                                    projects_obj = resolve_projects()
                                    proj = projects_obj.primary if projects_obj else None
                                    if proj and hasattr(proj, 'path'):
                                        project_dir = os.path.dirname(safe_str(proj.path))
                                        normalized_base = base_dir.replace('/', os.sep).replace('\\', os.sep)
                                        base_dir = os.path.normpath(os.path.join(project_dir, normalized_base))
                                except:
                                    pass
                        except Exception as e:
                            log_warning("Could not launch Project_directory: " + safe_str(e))
                            return None, "Please run 'Project_directory.py' manually to re-configure sync."
                    elif ans == "cancel":
                        return None, "Operation cancelled by user."
                else:
                    log_warning("Computer mismatch detected ('%s' vs '%s') but UI (system.ui) is not available." % (safe_str(sync_pc), safe_str(current_pc)))
        except Exception as e:
            log_warning("Error during PC mismatch check: " + safe_str(e))

    # Create directory if it doesn't exist
    if base_dir:
        if not os.path.exists(base_dir):
            try:
                os.makedirs(base_dir)
                log_info("Created sync directory: " + base_dir)
                print("Created sync directory: " + base_dir)
            except Exception as e:
                log_error("Failed to create sync directory: " + safe_str(e))
                return None, "Could not create sync directory: " + base_dir + "\n\nError: " + safe_str(e)
        
        return base_dir, None
    
    return None, "Project sync directory not found: " + str(base_dir) + "\nPlease run 'Project_directory.py' to update it."


def ensure_git_configs(export_dir):
    """Create .gitignore and .gitattributes if they don't exist in the export directory."""
    gitignore_path = os.path.join(export_dir, ".gitignore")
    gitattributes_path = os.path.join(export_dir, ".gitattributes")
    
    # 1. Gitignore handling
    if not os.path.exists(gitignore_path):
        content = [
            "# CODESYS Sync local files",
            "*.json",
            "*.log",
            "*.tmp",
            "*.bak",
            "/.diff/",
            "/.diff/*",
            "",
            "# CODESYS temporary and build files",
            "*.~u",
            "*.precompilecache",
            "*.opt",
            "*.bootinfo",
            "*.bootinfo_guids",
            "*.compileinfo",
            "*.simulation.bootinfo",
            "*.simulation.bootinfo_guids",
            "*.simulation.compileinfo",
            ""
        ]
        try:
            with codecs.open(gitignore_path, "w", "utf-8") as f:
                f.write("\n".join(content))
            log_info("Created: .gitignore")
        except Exception as e:
            log_error("Failed to create .gitignore: " + safe_str(e))
    else:
        # File exists, check if essential patterns are present
        try:
            with codecs.open(gitignore_path, "r", "utf-8") as f:
                lines = f.readlines()
            
            # Ensure *.log is ignored
            if not any("*.log" in line for line in lines):
                with codecs.open(gitignore_path, "a", "utf-8") as f:
                    f.write("\n*.log\n")
                log_info("Updated .gitignore with *.log")
        except: pass

    # 2. Gitattributes handling
    if not os.path.exists(gitattributes_path):
        content = [
            "# Git LFS configuration for CODESYS project binary",
            "*.project filter=lfs diff=lfs merge=lfs -text",
            "",
            "# Prevent line ending conversion for CODESYS Structured Text files",
            "*.st -text",
            "",
            "# GitHub linguist language detection",
            "*.st linguist-language=Pascal",
            ""
        ]
        try:
            with codecs.open(gitattributes_path, "w", "utf-8") as f:
                f.write("\n".join(content))
            log_info("Created: .gitattributes")
        except Exception as e:
            log_error("Failed to create .gitattributes: " + safe_str(e))


# Removed MetadataLock and load_metadata (metadata files no longer used)


def format_st_content(declaration, implementation, can_have_impl=False):
    """
    Format ST file content with clean structure.
    Uses markers for import script to parse sections.
    Ensures consistent whitespace for reliable hashing.
    
    Args:
        declaration: The declaration text
        implementation: The implementation text (may be None or empty)
        can_have_impl: True if object type can have implementation even if empty
    """
    content = []
    
    decl = (declaration or "").strip()
    if decl:
        content.append(decl)
    
    impl = (implementation or "").strip()
    if impl or can_have_impl:
        if content and impl:
            content.append("")  # Empty line separator
        content.append(IMPL_MARKER)
        if impl:
            content.append(impl)
    
    return "\n".join(content).replace('\r\n', '\n').replace('\r', '\n')


def format_property_content(declaration, get_impl, set_impl):
    """
    Format property file content with GET and SET accessors combined.
    """
    content = []
    
    decl = (declaration or "").strip()
    if decl:
        content.append(decl)
    
    # Add GET section if present
    get = (get_impl or "").strip()
    if get:
        if content:
            content.append("")  # Empty line separator
        content.append(IMPL_MARKER)
        content.append(PROPERTY_GET_MARKER)
        content.append(get)
    
    # Add SET section if present
    set_content = (set_impl or "").strip()
    if set_content:
        if not get:
            # If no GET but we have SET, still need IMPL_MARKER
            if content:
                content.append("")
            content.append(IMPL_MARKER)
        content.append("")  # Empty line before SET
        content.append(PROPERTY_SET_MARKER)
        content.append(set_content)
    
    return "\n".join(content).replace('\r\n', '\n').replace('\r', '\n')

def merge_native_xmls(file_paths, output_path):
    """
    Merge multiple CODESYS .xml (Native Export) files into one.
    This allows importing them in a single batch, showing only one dialog.
    """
    if not file_paths: return False
    
    header = None
    footer = None
    payloads = []
    
    for path in file_paths:
        try:
            if not os.path.exists(path): continue
            with codecs.open(path, 'r', 'utf-8') as f:
                content = f.read()
            
            # Find the EntryList container
            start_marker = '<List2 Name="EntryList">'
            end_marker = '</List2>'
            
            s_idx = content.find(start_marker)
            e_idx = content.rfind(end_marker)
            
            if s_idx == -1 or e_idx == -1:
                log_warning("Could not find EntryList in " + path + ". Skipping merge.")
                continue
                
            if header is None:
                # Take the file structure from the first file
                header = content[:s_idx + len(start_marker)]
                footer = content[e_idx:]
            
            # Extract the actual object(s) inside the EntryList
            payload = content[s_idx + len(start_marker) : e_idx]
            payloads.append(payload)
        except Exception as e:
            log_error("Failed to read XML for merge: " + str(e))
            
    if not payloads: return False
    
    # Reassemble: Header + all payloads + Footer
    merged = header + "\n".join(payloads) + footer
    try:
        with codecs.open(output_path, 'w', 'utf-8') as f:
            f.write(merged)
        return True
    except Exception as e:
        log_error("Failed to write merged XML: " + str(e))
        return False


def parse_property_content(content):
    """
    Parse property file content to extract declaration, GET, and SET sections.
    
    Args:
        content: Full property file content string
    
    Returns:
        Tuple (declaration, get_impl, set_impl)
    """
    declaration = None
    get_impl = None
    set_impl = None
    
    if not content:
        return declaration, get_impl, set_impl
    
    # Split by IMPL_MARKER first
    if IMPL_MARKER in content:
        parts = content.split(IMPL_MARKER, 1)
        declaration = parts[0].strip()
        impl_section = parts[1].strip() if len(parts) > 1 else ""
        
        # Now split implementation by GET and SET markers
        if PROPERTY_GET_MARKER in impl_section:
            # Has GET section
            get_parts = impl_section.split(PROPERTY_GET_MARKER, 1)
            get_content = get_parts[1] if len(get_parts) > 1 else ""
            
            # Check if SET follows GET
            if PROPERTY_SET_MARKER in get_content:
                set_parts = get_content.split(PROPERTY_SET_MARKER, 1)
                get_impl = set_parts[0].strip()
                set_impl = set_parts[1].strip() if len(set_parts) > 1 else None
            else:
                get_impl = get_content.strip()
        elif PROPERTY_SET_MARKER in impl_section:
            # Has only SET section (no GET)
            set_parts = impl_section.split(PROPERTY_SET_MARKER, 1)
            set_impl = set_parts[1].strip() if len(set_parts) > 1 else None
        else:
            # No property markers, treat entire impl as GET (backward compatibility)
            get_impl = impl_section
    else:
        # No implementation marker - entire content is declaration
        declaration = content.strip()
    
    return declaration, get_impl, set_impl


# Removed save_metadata (metadata files no longer used)


# --- Sync Pragma API ---

def parse_sync_pragmas(content):
    """Parse leading cds-text-sync pragma lines from file content.

    Returns:
        (attrs, clean_st)
        - attrs: dict {"exclude_from_build": True, ...} (only True keys)
        - clean_st: content with pragma block removed
    """
    from codesys_constants import SYNC_PRAGMA_PREFIX
    lines = content.split("\n")
    attrs = {}
    first_non_pragma = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(SYNC_PRAGMA_PREFIX):
            kv = stripped[len(SYNC_PRAGMA_PREFIX):]
            if "=" in kv:
                key, val = kv.split("=", 1)
                key = key.strip()
                val = val.strip().lower()
                if val == "true":
                    attrs[key] = True
            first_non_pragma = i + 1
        elif stripped == "":
            if not attrs:
                break
            first_non_pragma = i + 1
        else:
            break

    clean_st = "\n".join(lines[first_non_pragma:])
    clean_st = clean_st.lstrip("\n")
    return attrs, clean_st


def render_sync_pragmas(attrs, clean_st):
    """Render sync pragmas + clean ST content to final file content.

    Args:
        attrs: dict {"exclude_from_build": True, ...}
        clean_st: ST content without pragmas
    Returns:
        Final file content string
    """
    from codesys_constants import ATTR_ORDER, SYNC_PRAGMA_PREFIX
    pragma_lines = []
    for key in ATTR_ORDER:
        if attrs.get(key):
            pragma_lines.append("%s%s=true" % (SYNC_PRAGMA_PREFIX, key))

    if pragma_lines:
        return "\n".join(pragma_lines) + "\n\n" + clean_st
    return clean_st


def normalize_sync_attrs(attrs):
    """Normalize attrs dict to a stable, hashable tuple.

    Only includes keys from ATTR_ORDER that are True.
    Returns a tuple of sorted (key, True) pairs for deterministic hashing.
    """
    from codesys_constants import ATTR_ORDER
    return tuple((k, True) for k in ATTR_ORDER if attrs.get(k))


def build_state_hash(code_content, attrs):
    """Build combined state hash from code content and attributes.

    Args:
        code_content: ST code string (already clean, no pragmas)
        attrs: dict {"exclude_from_build": True, ...}
    Returns:
        str: hex hash representing full object state
    """
    code_hash = calculate_hash(code_content)
    attrs_hash = calculate_hash(str(normalize_sync_attrs(attrs)))
    return calculate_hash(code_hash + "|" + attrs_hash)


def read_ide_attrs(obj):
    """Read supported IDE attributes from live CODESYS object.

    Uses obj.build_properties (ScriptBuildProperties) to access build flags.
    Uses ATTR_REGISTRY to determine which attributes apply to this object's semantic kind.
    Returns dict of {attr_key: True} for non-default attributes.
    """
    from codesys_constants import ATTR_REGISTRY
    from codesys_type_system import resolve_runtime_object, semantic_kind_from_guid
    from codesys_type_profiles import PROJECT_PROPERTY_KEY

    obj_type_guid = safe_str(obj.type)
    obj_name = safe_str(obj.get_name()) if hasattr(obj, "get_name") else "<unknown>"

    # Resolve semantic kind from runtime type
    semantic_kind = None
    try:
        profile_name = get_project_prop(PROJECT_PROPERTY_KEY)
        resolution = resolve_runtime_object(obj, profile_name)
        semantic_kind = resolution.get("semantic_kind")
    except:
        pass
    if not semantic_kind:
        semantic_kind = semantic_kind_from_guid(obj_type_guid)

    attrs = {}
    unsupported_props = getattr(read_ide_attrs, "_unsupported_props", set())
    read_ide_attrs._unsupported_props = unsupported_props

    applicable = [key for key, spec in ATTR_REGISTRY.items() if semantic_kind and semantic_kind in spec.get("kinds", set())]
    if not applicable:
        return attrs

    # Access the build_properties sub-object (ScriptBuildProperties)
    build_props = None
    try:
        build_props = getattr(obj, "build_properties", None)
    except Exception as e:
        log_info("read_ide_attrs: %s has no build_properties: %s" % (obj_name, safe_str(e)))

    if build_props is None:
        log_info("read_ide_attrs: %s -> build_properties is None (object may not support build flags)" % obj_name)
        return attrs

    # One-time diagnostic: dump all build_properties attributes for the first applicable object
    _dumped = getattr(read_ide_attrs, '_bp_dumped', False)
    if not _dumped:
        read_ide_attrs._bp_dumped = True
        try:
            bp_attrs = [a for a in dir(build_props) if not a.startswith("_")]
            log_info("BUILD_PROPERTIES DISCOVERY for %s (%s): %s" % (obj_name, semantic_kind, bp_attrs))
            for a in bp_attrs:
                try:
                    val = getattr(build_props, a)
                    if not hasattr(val, "__call__"):
                        log_info("  build_properties.%s = %s" % (a, repr(val)))
                except Exception as e2:
                    log_info("  build_properties.%s -> ERROR: %s" % (a, safe_str(e2)))
        except Exception as e:
            log_info("BUILD_PROPERTIES DISCOVERY failed: %s" % safe_str(e))

    for key, spec in ATTR_REGISTRY.items():
        if semantic_kind and semantic_kind not in spec.get("kinds", set()):
            continue
        prop_name = spec["api_prop"]
        try:
            # Check if this property is valid for this object type
            valid_check = prop_name + "_is_valid"
            if hasattr(build_props, valid_check):
                if not getattr(build_props, valid_check):
                    continue

            if hasattr(build_props, prop_name):
                val = getattr(build_props, prop_name)
                if val:
                    attrs[key] = True
                    log_info("  %s.build_properties.%s = %s" % (obj_name, prop_name, repr(val)))
            else:
                unsupported_props.add(prop_name)
        except Exception as e:
            if "has no attribute" in safe_str(e).lower():
                unsupported_props.add(prop_name)
                continue
            log_warning("Cannot read attr '%s' from %s: %s" % (key, obj_name, safe_str(e)))

    if attrs:
        log_info("read_ide_attrs: %s -> %s" % (obj_name, list(attrs.keys())))
    return attrs


def write_ide_attrs(obj, attrs):
    """Apply parsed attributes to a CODESYS IDE object via build_properties.

    Only sets attributes that are supported for this object's semantic kind per ATTR_REGISTRY.
    Skips silently if attribute is not in attrs (preserves current IDE state).
    """
    from codesys_constants import ATTR_REGISTRY
    from codesys_type_system import resolve_runtime_object, semantic_kind_from_guid
    from codesys_type_profiles import PROJECT_PROPERTY_KEY

    obj_type_guid = safe_str(obj.type)
    obj_name = safe_str(obj.get_name()) if hasattr(obj, "get_name") else "<unknown>"

    # Resolve semantic kind from runtime type
    semantic_kind = None
    try:
        profile_name = get_project_prop(PROJECT_PROPERTY_KEY)
        resolution = resolve_runtime_object(obj, profile_name)
        semantic_kind = resolution.get("semantic_kind")
    except:
        pass
    if not semantic_kind:
        semantic_kind = semantic_kind_from_guid(obj_type_guid)

    # Access the build_properties sub-object
    build_props = None
    unsupported_props = getattr(write_ide_attrs, "_unsupported_props", set())
    write_ide_attrs._unsupported_props = unsupported_props
    try:
        build_props = getattr(obj, "build_properties", None)
    except Exception as e:
        log_warning("write_ide_attrs: %s has no build_properties: %s" % (obj_name, safe_str(e)))
        return

    if build_props is None:
        log_warning("write_ide_attrs: %s -> build_properties is None, cannot apply attrs" % obj_name)
        return

    for key, spec in ATTR_REGISTRY.items():
        if semantic_kind and semantic_kind not in spec.get("kinds", set()):
            continue
            
        prop_name = spec["api_prop"]
        # Treat missing pragmas as False (unset)
        target_val = attrs.get(key, False)

        if prop_name in unsupported_props:
            continue
        
        try:
            # Check if this property is valid for this object type
            valid_check = prop_name + "_is_valid"
            if hasattr(build_props, valid_check):
                if not getattr(build_props, valid_check):
                    log_info("write_ide_attrs: %s.%s is not valid, skipping" % (obj_name, prop_name))
                    continue

            if not hasattr(build_props, prop_name):
                unsupported_props.add(prop_name)
                continue

            # Only set it if it actually differs from target (to avoid dirtifying IDE unnecessarily)
            current_val = getattr(build_props, prop_name)
            if bool(current_val) != bool(target_val):
                setattr(build_props, prop_name, target_val)
                log_info("write_ide_attrs: updated %s.build_properties.%s = %s" % (obj_name, prop_name, target_val))
        except Exception as e:
            if "has no attribute" in safe_str(e).lower():
                unsupported_props.add(prop_name)
                continue
            log_warning("Cannot write attr '%s' on %s: %s" % (key, obj_name, safe_str(e)))


def parse_st_file(file_path):
    """Parse an ST file: strip sync pragmas, then extract declaration and implementation.

    Returns tuple (declaration, implementation, attrs).
    attrs is a dict of sync pragma attributes (may be empty).
    For backward compatibility, callers that unpack only 2 values will get (decl, impl)
    and attrs is the 3rd element.
    """
    try:
        with codecs.open(file_path, "r", "utf-8") as f:
            content = f.read()
    except Exception as e:
        print("Error reading file " + file_path + ": " + safe_str(e))
        return None, None, {}
    
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    # Strip sync pragmas first
    attrs, clean_content = parse_sync_pragmas(content)

    declaration = None
    implementation = None
    
    if IMPL_MARKER in clean_content:
        parts = clean_content.split(IMPL_MARKER)
        declaration = parts[0].strip()
        implementation = parts[1].strip() if len(parts) > 1 else None
    else:
        declaration = clean_content.strip()
    
    return declaration, implementation, attrs


def build_object_cache(project=None):
    """
    Build lookup caches for project objects.
    Returns tuple (guid_map, name_map).
    
    Args:
        project: CODESYS project object. If None, will try to use global 'projects.primary'
    """
    guid_map = {}
    name_map = {}
    
    # Try to get project from parameter or global
    if project is None:
        try:
            project = projects.primary
        except NameError:
            # Not in CODESYS environment
            return guid_map, name_map
    
    if not project:
        return guid_map, name_map
    
    try:
        all_objects = project.get_children(recursive=True)
    except:
        return guid_map, name_map
    
    for obj in all_objects:
        try:
            # GUID Cache
            g = safe_str(obj.guid)
            if g != "N/A":
                guid_map[g] = obj
            
            # Name Cache
            n = safe_str(obj.get_name())
            if n not in name_map:
                name_map[n] = []
            name_map[n].append(obj)
        except:
            continue
    
    return guid_map, name_map


def find_application_recursive(obj, depth=0):
    """Recursively search for Application or PLC Logic container"""
    if depth > 5:  # Limit recursion depth
        return None
        
    try:
        children = obj.get_children()
        for child in children:
            try:
                child_kind = _get_semantic_kind(child)
                if child_kind == "application":
                    return child
                if child_kind in ("device", "plc_logic"):
                    result = find_application_recursive(child, depth + 1)
                    if result:
                        return result
            except:
                continue
    except:
        pass
    return None


def is_container_device(obj):
    """
    Check if a device is a 'container' (like a PLC root) that contains logic/applications.
    Such devices should NOT be monolithic XMLs because they are too large and
    their children (Applications, etc.) are already handled separately.
    """
    try:
        obj_kind = _get_semantic_kind(obj)
        if obj_kind != "device":
            return False
            
        # Check if it has an Application or Plc Logic child
        # We only check direct children to avoid heavy recursion
        children = obj.get_children(recursive=False)
        for child in children:
            child_kind = _get_semantic_kind(child)
            if child_kind in ["application", "plc_logic"]:
                return True
        return False
    except:
        return False


def _find_child_transparent(parent_obj, name):
    """
    Find a child object by name, transparently looking through 'Plc Logic' nodes.
    
    The export skips 'Plc Logic' in paths (e.g. PLC/ST_Application instead of
    PLC/Plc Logic/ST_Application). This helper first checks direct children, then
    looks through any plc_logic children for the target name.
    
    Returns the found object or None.
    """
    if not parent_obj or not name:
        return None
    
    name_lower = name.lower()
    
    try:
        children = parent_obj.get_children()
    except:
        return None
    
    # First pass: direct child match
    for child in children:
        try:
            if child.get_name().lower() == name_lower:
                return child
        except:
            continue
    
    # Second pass: look through 'plc_logic' children transparently
    # (the export skips this level in the path)
    for child in children:
        try:
            c_type = _get_semantic_kind(child)
            if c_type == "plc_logic":
                for grandchild in child.get_children():
                    try:
                        if grandchild.get_name().lower() == name_lower:
                            return grandchild
                    except:
                        continue
        except:
            continue
    
    return None


def ensure_folder_path(path_str, project):
    """
    Ensure folder structure exists in CODESYS project.
    path_str: relative path string e.g. "PLC/Application/MainFolder"
    Returns the parent object (folder/application/device) or None if failed.
    
    Note: The export skips 'Plc Logic' nodes in paths (e.g. PLC/ST_Application
    instead of PLC/Plc Logic/ST_Application), so this function transparently
    looks through plc_logic children when a direct match isn't found.
    """
    if not path_str or path_str == "." or path_str == "src":
        return project
        
    # Legacy 'src/' prefix check (handled by Project_export migration now, but for robustness)
    if path_str.startswith("src/"): path_str = path_str[4:]
    elif path_str.startswith("src\\"): path_str = path_str[4:]
    
    parts = path_str.replace("\\", "/").split("/")
    current_obj = project # Start at project root
    
    log_info("ensure_folder_path: resolving '" + path_str + "' (" + str(len(parts)) + " parts)")
    log_info("  Starting at: " + safe_str(current_obj) + " (type: " + safe_str(current_obj.type if hasattr(current_obj, 'type') else 'N/A') + ")")
    
    for i, part in enumerate(parts):
        if not part: continue
        
        found = _find_child_transparent(current_obj, part)
        
        if found:
            log_info("  [" + str(i) + "] Found '" + part + "' -> " + safe_str(found) + " (type: " + safe_str(found.type if hasattr(found, 'type') else 'N/A') + ")")
        else:
            log_info("  [" + str(i) + "] NOT found '" + part + "' under " + safe_str(current_obj) + " — will try to create folder")
            # List available children for debugging
            try:
                children = current_obj.get_children()
                child_names = []
                for c in children:
                    try:
                        child_names.append(safe_str(c.get_name()) + " (" + safe_str(c.type) + ")")
                    except:
                        child_names.append("???")
                log_info("    Available children: " + str(child_names))
            except Exception as e:
                log_info("    Could not list children: " + safe_str(e))
            
        if not found:
            # We can only create folders, not Devices/Applications
            try:
                if hasattr(current_obj, "create_folder"):
                    found = current_obj.create_folder(part)
                    log_info("    create_folder('" + part + "') returned: " + safe_str(found))
                elif hasattr(current_obj, "create_child"):
                    # Use folder GUID from constants
                    found = current_obj.create_child(part, FOLDER_GUID)
                    log_info("    create_child('" + part + "') returned: " + safe_str(found))
                else:
                    # If we reached a level where we can't create (e.g. Device level), log it
                    log_error("Cannot create component '" + part + "' at " + safe_str(current_obj))
                    return None
                
                # CODESYS quirk: create_folder/create_child may create the folder
                # but return a falsy wrapper. Re-scan children to find it.
                if not found:
                    log_info("    Return value was falsy, re-scanning children...")
                    found = _find_child_transparent(current_obj, part)
                    if found:
                        log_info("    Re-scan found: " + safe_str(found))
                    else:
                        log_error("    Re-scan also failed for '" + part + "'")
                        
            except Exception as e:
                log_error("Failed to create folder '" + part + "': " + safe_str(e))
                # Even if exception, the folder might have been created
                found = _find_child_transparent(current_obj, part)
                if found:
                    log_info("    Despite exception, found folder '" + part + "' via re-scan")
                else:
                    return None
        
        if found:
            current_obj = found
        else:
            return None
            
    return current_obj


def find_object_by_guid(guid, guid_map):
    """Find a CODESYS object by its GUID using cache"""
    return guid_map.get(guid)


def find_object_by_name(name, name_map, parent_name=None):
    """
    Find a CODESYS object by name using cache.
    Returns first match or None.
    """
    found = name_map.get(name)
    if not found:
        return None
    
    if len(found) == 1:
        return found[0]
    
    # Multiple matches - filter by parent if provided
    if parent_name:
        for obj in found:
            try:
                if hasattr(obj, "parent") and obj.parent:
                    if obj.parent.get_name() == parent_name:
                        return obj
            except:
                continue
        # Strict matching: if parent_name was provided but not found, return None
        return None
    
    # Return first match ONLY if no parent filter was requested
    return found[0]


def find_object_by_path(rel_path, project):
    """
    Find a CODESYS object using its hierarchical path.
    Example rel_path: "PLC/ST_Application/02_Object_GVL/_02_TaskLocalGVL.xml"
    
    Note: The export skips 'Plc Logic' nodes in paths, so this function
    transparently looks through plc_logic children when a direct match
    isn't found.
    """
    if not rel_path: return None
    
    # Clean up path
    path_str = rel_path.replace("\\", "/")
    if path_str.startswith("src/"): path_str = path_str[4:]
    
    # Strip extension for lookup
    root, ext = os.path.splitext(path_str)
    parts = root.split("/")
    
    # Handle New Format: Name.Type.xml
    if ext.lower() == ".xml" and parts:
        last_part = parts[-1]
        if "." in last_part:
            name_part, doc_type = last_part.rsplit(".", 1)
            # Verify if doc_type is a known CODESYS type name
            from codesys_type_system import SEMANTIC_TYPE_NAMES
            if doc_type in SEMANTIC_TYPE_NAMES or doc_type == "pou_xml":
                parts[-1] = name_part

    current_obj = project
    for part in parts:
        if not part: continue
        found = _find_child_transparent(current_obj, part)
        
        if found:
            current_obj = found
        else:
            return None
            
    return current_obj


def cleanup_old_backups(project_folder, retention_count, verbose=True):
    """
    Clean up old timestamped backups in .project/ folder.
    Only deletes files matching pattern: YYYYMMDD_HHMMSS_*.bak
    Preserves non-timestamped backup files (Git LFS backups).
    
    Args:
        project_folder: Path to the .project folder
        retention_count: Number of timestamped backups to keep
    """
    if retention_count <= 0:
        return
    
    if not os.path.exists(project_folder):
        return
    
    import re
    
    timestamped_backups = []
    try:
        for filename in os.listdir(project_folder):
            if not filename.endswith(".bak"):
                continue
            
            # Pattern: YYYYMMDD_HHMMSS_*.bak
            # Example: 20260325_143022_MyProject.project.bak
            if re.match(r'^\d{8}_\d{6}_.*\.bak$', filename):
                full_path = os.path.join(project_folder, filename)
                if os.path.isfile(full_path):
                    timestamped_backups.append(full_path)
        
        if len(timestamped_backups) <= retention_count:
            return
        
        # Sort by filename (timestamp is encoded in name)
        timestamped_backups.sort(reverse=True)
        
        # Delete files beyond retention count
        files_to_delete = timestamped_backups[retention_count:]
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                filename = os.path.basename(file_path)
                log_info("Deleted old backup: .project/" + filename)
                if verbose:
                    print("Deleted old backup: .project/" + filename)
            except Exception as e:
                log_warning("Failed to delete old backup " + file_path + ": " + safe_str(e))
                if verbose:
                    print("Warning: Failed to delete old backup: " + file_path)
    except Exception as e:
        log_warning("Error during backup cleanup: " + safe_str(e))
        if verbose:
            print("Warning: Error during backup cleanup: " + safe_str(e))


def backup_project_binary(export_dir, projects_obj=None, timestamped=False, retention_count=None, verbose=True):
    """
    Copy the current project binary to /project folder.
    Forces a project save before copying to ensure the backup is current.
    If timestamped=True, creates a backup with date and time.
    
    Args:
        export_dir: Directory where .project folder will be created
        projects_obj: CODESYS projects object
        timestamped: If True, create timestamped backup with date and time
        retention_count: Optional. If provided, clean up old timestamped backups
                         keeping only this many (only applies to timestamped backups)
    
    Returns:
        Backup filename if created successfully, None otherwise
    """
    try:
        if not projects_obj:
            try:
                import projects
                projects_obj = projects
            except:
                pass
        
        if not projects_obj or not hasattr(projects_obj, "primary") or not projects_obj.primary:
            log_warning("Cannot identify project for backup.")
            if verbose:
                print("Debug: Cannot identify project for backup (projects_obj missing or invalid).")
            return None

        # Force save to ensure we backup the latest state
        try:
            projects_obj.primary.save()
            log_info("Project saved for backup.")
        except Exception as e:
            msg = "Could not save project before backup: " + safe_str(e)
            log_warning(msg)
            if verbose:
                print("Debug: " + msg)

        if not hasattr(projects_obj.primary, "path") or not projects_obj.primary.path:
            log_warning("Project not saved to disk yet. Skipping binary backup.")
            if verbose:
                print("Debug: Project has no path on disk.")
            return None

        project_path = projects_obj.primary.path
        project_folder = os.path.join(export_dir, ".project")
        
        if not os.path.exists(project_folder):
            os.makedirs(project_folder)
            
        # Determine target filename
        if timestamped:
            import time
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            base_name = os.path.basename(project_path)
            # Format: YYYYMMDD_HHMMSS_ProjectName.project.bak
            file_name = "{}_{}.bak".format(timestamp, base_name)
        else:
            custom_name = get_project_prop("cds-sync-backup-name", "")
            if custom_name:
                # Ensure it ends with .project
                if not custom_name.lower().endswith(".project"):
                    file_name = custom_name + ".project"
                else:
                    file_name = custom_name
            else:
                file_name = os.path.basename(project_path)
            
        target_path = os.path.join(project_folder, file_name)
        
        shutil.copy2(project_path, target_path)
        log_info("Binary backup created: .project/" + file_name)
        if verbose:
            print("Binary backup created: .project/" + file_name)
        
        # Clean up old timestamped backups if retention is specified
        if timestamped and retention_count is not None:
            cleanup_old_backups(project_folder, retention_count, verbose=verbose)
        
        return file_name
        
    except Exception as e:
        log_error("Warning: Could not create binary backup: " + str(e))
        if verbose:
            print("Warning: Could not create binary backup: " + str(e))
        return None


def normalize_path(path):
    """Normalize path separators to forward slashes for cross-platform consistency in cache keys."""
    if path is None: return ""
    return path.replace("\\", "/").strip("/")


def build_folder_hashes(object_hashes):
    """
    Build direct-parent folder hashes from a dictionary of object hashes.
    
    Args:
        object_hashes: dict of {norm_path: content_hash}
    
    Returns:
        dict: {folder_path: folder_hash}
    """
    from collections import defaultdict
    folder_children = defaultdict(list)
    
    for path, o_hash in object_hashes.items():
        if not o_hash:
            continue

        parts = path.split("/")
        if len(parts) < 2:
            continue

        # Folder hashes are intentionally local to immediate file children.
        # A change in PLC/ST_Application/... must not invalidate untouched
        # device XML files that merely share the top-level PLC folder.
        folder_path = "/".join(parts[:-1])
        folder_children[folder_path].append(o_hash)
            
    result = {}
    for folder_path, child_hashes in folder_children.items():
        # Folder hash is the hash of sorted child hashes
        sorted_hashes = "|".join(sorted(child_hashes))
        result[folder_path] = calculate_hash(sorted_hashes)
        
    return result


def load_sync_cache(base_dir):
    """Load the synchronization cache from sync_cache.json in the base directory."""
    cache_path = os.path.join(base_dir, "sync_cache.json")
    if os.path.exists(cache_path):
        try:
            with codecs.open(cache_path, "r", "utf-8") as f:
                data = json.load(f)
                cache_version = data.get("version", "1.0")
                if cache_version != CACHE_VERSION:
                    log_info("Cache version mismatch (%s vs %s), triggering full rebuild." % (cache_version, CACHE_VERSION))
                    return {"objects": {}, "folders": {}, "types": {}, "version": CACHE_VERSION}
                return {
                    "objects": data.get("objects", {}),
                    "folders": data.get("folders", {}),
                    "types": data.get("types", {}),
                    "version": cache_version
                }
        except Exception as e:
            log_warning("Could not load sync cache: " + safe_str(e))
    return {"objects": {}, "folders": {}, "types": {}, "version": CACHE_VERSION}


def save_sync_cache(base_dir, objects_cache, folder_hashes=None, type_cache=None):
    """Save the synchronization cache to sync_cache.json in the base directory."""
    cache_path = os.path.join(base_dir, "sync_cache.json")
    cache_data = {
        "version": CACHE_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "folders": folder_hashes or {},
        "types": type_cache or {},
        "objects": objects_cache
    }
    try:
        with codecs.open(cache_path, "w", "utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        log_warning("Could not save sync cache: " + safe_str(e))


def check_version_compatibility(base_dir):
    """Check if export was done with compatible script version"""
    from codesys_constants import SCRIPT_VERSION
    
    proj_version = get_project_prop("cds-sync-version")
    if proj_version is None:
        proj_version = "not set"
    
    metadata_path = os.path.join(base_dir, "sync_metadata.json")
    
    if proj_version != SCRIPT_VERSION:
        msg = "Version mismatch: Project (v{}) vs Current (v{})".format(proj_version, SCRIPT_VERSION)
        return False, msg
    
    if os.path.exists(metadata_path):
        try:
            with codecs.open(metadata_path, "r", "utf-8") as f:
                data = json.load(f)
            export_version = data.get("script_version")
            if export_version and export_version != SCRIPT_VERSION:
                msg = "Version mismatch: Export (v{}) vs Current (v{})".format(export_version, SCRIPT_VERSION)
                return False, msg
        except:
            pass
    
    return True, None


def save_sync_metadata(base_dir, action, stats, elapsed):
    """Save sync_metadata.json and update project version property.

    Used by both Project_export.py and Project_import.py.
    Args:
        base_dir: Export/import directory path
        action: "export" or "import"
        stats: Statistics dict
        elapsed: Elapsed time in seconds (float)
    """
    from codesys_constants import SCRIPT_VERSION
    metadata = {
        "script_version": SCRIPT_VERSION,
        "last_action": action,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_sec": round(elapsed, 2),
        "statistics": stats
    }
    metadata_path = os.path.join(base_dir, "sync_metadata.json")
    try:
        with codecs.open(metadata_path, "w", "utf-8") as f:
            json.dump(metadata, f, indent=2)
        log_info("%s metadata saved to sync_metadata.json (v%s)" % (action.capitalize(), SCRIPT_VERSION))
    except Exception as e:
        log_warning("Failed to save %s metadata: %s" % (action, safe_str(e)))
    try:
        set_project_prop("cds-sync-version", SCRIPT_VERSION)
    except Exception as e:
        log_warning("Failed to save version to project property: " + safe_str(e))


def finalize_sync_operation(base_dir, projects_obj, is_import=False, verbose=True):
    """Handle final document save or binary backup according to user settings."""
    save_prop = "cds-sync-save-after-import" if is_import else "cds-sync-save-after-export"
    save_after_op = get_project_prop(save_prop, True)
    backup_binary = get_project_prop("cds-sync-backup-binary", False)

    if backup_binary and projects_obj and getattr(projects_obj, 'primary', None):
        try:
            if verbose:
                print("Action: Updating binary backup...")
            backup_project_binary(base_dir, projects_obj, verbose=verbose)
        except Exception as e:
            if verbose:
                print("Warning: Could not update binary backup: " + safe_str(e))
    elif save_after_op and projects_obj and getattr(projects_obj, 'primary', None):
        try:
            if verbose:
                print("Action: Saving project...")
            projects_obj.primary.save()
            if verbose:
                print("Project saved successfully.")
        except Exception as e:
            op_str = "import" if is_import else "export"
            if verbose:
                print("Warning: Could not save project after " + op_str + ": " + safe_str(e))


def create_safety_backup(base_dir, projects_obj, items_to_import):
    """Create a timestamped safety backup of the project before importing changes."""
    backup_filename = None
    safety_backup = get_project_prop("cds-sync-safety-backup", True)
    if safety_backup and items_to_import:
        retention = get_project_prop("cds-sync-backup-retention-count", 10)
        backup_filename = backup_project_binary(base_dir, projects_obj, timestamped=True, retention_count=retention)
    return backup_filename

