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

# --- Global Thread Lock ---
_metadata_thread_lock = threading.Lock()
from codesys_constants import IMPL_MARKER, FORBIDDEN_CHARS, TYPE_GUIDS, PROPERTY_GET_MARKER, PROPERTY_SET_MARKER


# --- Logging System ---
# --- Logging System ---
class Logger:
    def __init__(self):
        self.log_file = None
        self.is_final = False
        
    def _initialize(self, base_dir=None):
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
            import projects
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
        self._initialize()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = "[%s] [%s] %s\n" % (timestamp, level, message)
        
        if include_traceback:
            log_entry += traceback.format_exc() + "\n"
            
        print("[%s] %s" % (level, message))
        
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

def init_logging(base_dir):
    """Explicitly set the logging directory"""
    if base_dir and os.path.exists(base_dir):
        _logger._initialize(base_dir)

def log_error(message, critical=False):
    _logger.log("ERROR", message, include_traceback=True)
    if critical:
        try:
            import system
            system.ui.error("CRITICAL ERROR: " + message + "\n\nSee sync_debug.log for details.")
        except:
            pass

# --- Utility Functions ---


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


def clean_filename(name):
    """Clean filename from invalid characters"""
    clean_name = name
    for char in FORBIDDEN_CHARS:
        clean_name = clean_name.replace(char, "_")
    return clean_name


def get_project_prop(key, default=None):
    """Safely get a project property using the appropriate API for this CODESYS version."""
    try:
        import __main__
        proj = None
        if hasattr(__main__, 'projects'): proj = __main__.projects.primary
        else:
            try: proj = projects.primary
            except: pass
            
        if not proj: return default
        
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
        import __main__
        proj = None
        if hasattr(__main__, 'projects'): proj = __main__.projects.primary
        else:
            try: proj = projects.primary
            except: pass
            
        if not proj: return False
        
        info = proj.get_project_info() if hasattr(proj, "get_project_info") else getattr(proj, "project_info", None)
        if not info: return False
        
        props = info.values if hasattr(info, "values") else info
        props[key] = str(value)
        return True
    except:
        return False

def load_base_dir():
    """Load base directory from the project property 'cds-sync-folder'.
    
    Supports both absolute and relative paths:
    - Absolute paths: Used as-is (e.g., C:\\MySync\\)
    - Relative paths: Resolved relative to project file location (e.g., ./ or ./src/)
    
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
            # Get project file path
            proj = None
            try:
                import __main__
                if hasattr(__main__, 'projects'):
                    proj = __main__.projects.primary
            except:
                pass
            
            if not proj:
                try:
                    proj = projects.primary
                except:
                    pass
            
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
    
    # Check for PC mismatch to handle projects shared between colleagues
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
                res = sys_ui.choose(message, ("Yes, Re-configure", "No, Keep Current", "Cancel Operation"))
                if res and res[0] == 0:
                    try:
                        import Project_directory
                        Project_directory.set_base_directory()
                        base_dir = get_project_prop("cds-sync-folder")
                        # Re-resolve if it's still relative after reconfiguration
                        if base_dir and (base_dir.startswith('.' + os.sep) or base_dir.startswith('./') or base_dir.startswith('.\\') or base_dir == '.'):
                            try:
                                proj = None
                                try:
                                    import __main__
                                    if hasattr(__main__, 'projects'): proj = __main__.projects.primary
                                except: pass
                                if not proj:
                                    try: proj = projects.primary
                                    except: pass
                                if proj and hasattr(proj, 'path'):
                                    project_dir = os.path.dirname(safe_str(proj.path))
                                    normalized_base = base_dir.replace('/', os.sep).replace('\\', os.sep)
                                    base_dir = os.path.normpath(os.path.join(project_dir, normalized_base))
                            except:
                                pass
                    except Exception as e:
                        log_warning("Could not launch Project_directory: " + safe_str(e))
                        return None, "Please run 'Project_directory.py' manually to re-configure sync."
                elif res and res[0] == 2:
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


class MetadataLock:
    """
    File-based lock to prevent race conditions during metadata access.
    Combines threading lock for same-process safety and directory-based 
    lock for cross-process/script safety.
    """
    def __init__(self, base_dir, timeout=30):
        self.base_dir = base_dir
        self.lock_path = os.path.join(base_dir, ".metadata.lock")
        self.info_path = os.path.join(self.lock_path, "owner.info")
        self.timeout = timeout
        self.locked = False

    def _get_owner_info(self):
        """Get information about the script and PID holding the lock."""
        try:
            import __main__
            script_name = os.path.basename(__main__.__file__) if hasattr(__main__, "__file__") else "Unknown script"
        except:
            script_name = "Unknown script"
            
        try:
            import os
            pid = os.getpid()
        except:
            pid = "Unknown PID"
            
        return "Script: %s, PID: %s" % (script_name, pid)

    def acquire(self):
        start = time.time()
        owner_info = self._get_owner_info()
        
        while time.time() - start < self.timeout:
            try:
                # os.mkdir is atomic on Windows/Linux and fails if exists
                os.mkdir(self.lock_path)
                
                # Write owner info
                try:
                    with open(self.info_path, "w") as f:
                        f.write(owner_info)
                except:
                    pass
                    
                self.locked = True
                return True
            except OSError:
                # Directory exists or other OS error
                # Check for stale lock (older than 2 minutes)
                try:
                    mtime = os.path.getmtime(self.lock_path)
                    if time.time() - mtime > 120: # Stale after 2 minutes
                        log_warning("Breaking stale metadata lock (older than 2 mins)...")
                        self.release(force=True)
                        continue
                except:
                    pass
                time.sleep(1.0)
        return False

    def release(self, force=False):
        if self.locked or force:
            try:
                if os.path.exists(self.info_path):
                    os.remove(self.info_path)
                if os.path.exists(self.lock_path):
                    os.rmdir(self.lock_path)
            except:
                pass
            self.locked = False

    def __enter__(self):
        _metadata_thread_lock.acquire()
        if not self.acquire():
            # Try to read who owns it for better error message
            owner = "Unknown"
            try:
                if os.path.exists(self.info_path):
                    with open(self.info_path, "r") as f:
                        owner = f.read().strip()
            except:
                pass
                
            _metadata_thread_lock.release()
            err_msg = "Metadata lock timeout. Current owner: %s. Please wait for the other operation to finish or delete the '.metadata.lock' folder in your sync directory if no operation is running." % owner
            log_error(err_msg)
            raise Exception(err_msg)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        _metadata_thread_lock.release()


def load_metadata(base_dir):
    """
    Load metadata from _config.json and _metadata.csv.
    Maintains backward compatibility by returning a merged dictionary.
    """
    metadata = {}
    
    if not base_dir:
        return None
        
    # 1. Load configuration from Project Properties (Source of Truth)
    metadata["project_path"] = safe_str(projects.primary.path) if "projects" in globals() and projects.primary else "N/A"
    metadata["project_name"] = safe_str(projects.primary) if "projects" in globals() and projects.primary else "N/A"
    metadata["sync_timeout"] = get_project_prop("cds-sync-timeout", 10000)
    metadata["export_xml"] = get_project_prop("cds-sync-export-xml", False)
    metadata["autosync"] = get_project_prop("cds-sync-autosync", "STOPPED")
    metadata["export_timestamp"] = get_project_prop("cds-sync-timestamp", "N/A")
    
    # 2. Check if we have object metadata at all
    if not os.path.exists(os.path.join(base_dir, "_metadata.csv")):
        # If no CSV, this might be a fresh folder, but we still have config from project
        pass

    # 3. Load object metadata from _metadata.csv
    metadata["objects"] = {}
    csv_path = os.path.join(base_dir, "_metadata.csv")
    if "objects" not in metadata:
        metadata["objects"] = {}
        
    if os.path.exists(csv_path):
        try:
            # Python 2/3 compatible opening for CSV
            if sys.version_info[0] < 3:
                f = open(csv_path, 'rb')
            else:
                f = open(csv_path, 'r', encoding='utf-8', newline='')
            
            try:
                reader = csv.reader(f, delimiter=';')
                header = next(reader, None) # Skip header: GUID;Name;Path;LastModified;Type;Parent;ContentHash
                
                if header:
                    for row in reader:
                        if not row: continue
                        if len(row) >= 7:
                            # In Python 2, we need to decode manually
                            if sys.version_info[0] < 3:
                                row = [cell.decode('utf-8') for cell in row]
                                
                            guid, name, path, last_mod, obj_type, parent, content_hash = row[:7]
                            metadata["objects"][path] = {
                                "guid": guid,
                                "name": name,
                                "last_modified": last_mod,
                                "type": obj_type,
                                "parent": parent if parent != "None" else None,
                                "content_hash": content_hash
                            }
            finally:
                f.close()
        except Exception as e:
            log_error("Error reading _metadata.csv: " + safe_str(e))
            
    return metadata


def format_st_content(declaration, implementation):
    """
    Format ST file content with clean structure.
    Uses markers for import script to parse sections.
    Ensures consistent whitespace for reliable hashing.
    """
    content = []
    
    decl = (declaration or "").strip()
    if decl:
        content.append(decl)
    
    impl = (implementation or "").strip()
    if impl:
        if content:
            content.append("")  # Empty line separator
        content.append(IMPL_MARKER)
        content.append(impl)
    
    return "\n".join(content)


def format_property_content(declaration, get_impl, set_impl):
    """
    Format property file content with GET and SET accessors combined.
    
    Args:
        declaration: Property declaration (e.g., "PROPERTY PUBLIC Test_prop : BOOL")
        get_impl: GET accessor implementation
        set_impl: SET accessor implementation
    
    Returns:
        Formatted content string with markers separating sections
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
    
    return "\n".join(content)


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


def save_metadata(base_dir, metadata):
    """
    Save metadata: configuration to _config.json and objects to _metadata.csv.
    Uses atomic writes (temp file + replace) to prevent data corruption.
    """
    config_path = os.path.join(base_dir, "_config.json")
    csv_path = os.path.join(base_dir, "_metadata.csv")
    
    config_tmp = config_path + ".tmp"
    csv_tmp = csv_path + ".tmp"
    
    def _atomic_replace(src, dst):
        """Helper for atomic replacement, compatible with Python 2.7 and 3.x"""
        if hasattr(os, 'replace'):
            os.replace(src, dst)
        else:
            # Fallback for Python 2.7 (Windows)
            if os.path.exists(dst):
                os.remove(dst)
            os.rename(src, dst)

    try:
        # 1. Update Project Properties (Source of Truth)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        metadata["export_timestamp"] = current_time
        
        set_project_prop("cds-sync-timestamp", current_time)
        set_project_prop("cds-sync-timeout", metadata.get("sync_timeout", 10000))
        set_project_prop("cds-sync-export-xml", metadata.get("export_xml", False))
        set_project_prop("cds-sync-autosync", metadata.get("autosync", "STOPPED"))
        
        # 2. Save configuration snapshot to _config.json (Mirror)
        config_fields = [
            "project_name", "project_path", "export_timestamp", 
            "autosync", "sync_timeout", "export_xml"
        ]
        config_data = {}
        for field in config_fields:
            if field in metadata:
                config_data[field] = metadata[field]
        
        with codecs.open(config_tmp, "w", "utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        _atomic_replace(config_tmp, config_path)
            
        # 2. Save object metadata to CSV
        if "objects" in metadata:
            # Debug: Count methods before saving
            method_count = sum(1 for obj in metadata["objects"].values() if obj.get("type") == TYPE_GUIDS.get("method"))
            print("DEBUG save_metadata: Saving " + str(len(metadata["objects"])) + " objects to CSV, including " + str(method_count) + " methods")
            
            if sys.version_info[0] < 3:
                f = open(csv_tmp, 'wb')
            else:
                f = open(csv_tmp, 'w', encoding='utf-8', newline='')
            
            try:
                writer = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
                # Header
                writer.writerow(["GUID", "Name", "Path", "LastModified", "Type", "Parent", "ContentHash"])
                
                # Sort objects by path for consistency
                paths = sorted(metadata["objects"].keys())
                rows_written = 0
                methods_written = 0
                
                for path in paths:
                    obj = metadata["objects"][path]
                    row = [
                        safe_str(obj.get("guid", "")),
                        safe_str(obj.get("name", "")),
                        safe_str(path),
                        safe_str(obj.get("last_modified", "")),
                        safe_str(obj.get("type", "")),
                        safe_str(obj.get("parent", "")),
                        safe_str(obj.get("content_hash", ""))
                    ]
                    
                    # In Python 2, we need to encode manually
                    if sys.version_info[0] < 3:
                        # Use unicode check for IronPython/Python 2 compatibility
                        unicode_type = unicode if sys.version_info[0] < 3 else str
                        row = [cell.encode('utf-8') if isinstance(cell, unicode_type) else str(cell) for cell in row]
                        
                    writer.writerow(row)
                    rows_written += 1
                    
                    # Debug: Count methods written
                    if obj.get("type") == TYPE_GUIDS.get("method"):
                        methods_written += 1
                        print("DEBUG save_metadata: Wrote method to CSV: " + path)
                
                print("DEBUG save_metadata: Wrote " + str(rows_written) + " rows to CSV, including " + str(methods_written) + " methods")
            finally:
                f.close()
            
            _atomic_replace(csv_tmp, csv_path)
        
        return True
    except Exception as e:
        log_error("Error saving split metadata: " + safe_str(e))
        for tmp_file in [config_tmp, csv_tmp]:
            if os.path.exists(tmp_file):
                try: os.remove(tmp_file)
                except: pass
        return False


def extract_libraries_from_project(project):
    """
    Extract library info from all library managers in project.
    Uses XML export to reliably get library details (name, version, company).
    """
    libraries = []
    import tempfile
    import re
    
    try:
        # Find all library manager objects
        all_objs = project.get_children(recursive=True)
        lib_manager_type = TYPE_GUIDS.get("library_manager", "adb5cb65-8e1d-4a00-b70a-375ea27582f3")
        managers = [obj for obj in all_objs if safe_str(obj.type) == lib_manager_type]
        
        for manager in managers:
            try:
                # Export Library Manager to XML to extract library information
                temp_dir = tempfile.gettempdir()
                xml_path = os.path.join(temp_dir, "libman_export_{0}.xml".format(safe_str(manager.guid)[:8]))
                
                if os.path.exists(xml_path):
                    os.remove(xml_path)
                
                # Export to XML
                project.export_native([manager], xml_path, recursive=True)
                
                if os.path.exists(xml_path):
                    with codecs.open(xml_path, 'r', 'utf-8') as f:
                        content = f.read()
                    
                    # Store raw matches to process after
                    raw_libraries = []

                    # Pattern 1: Placeholder Resolution (Key/Value)
                    p1 = r'<Key>\s*<Single Type="string">([^<]+)</Single>\s*</Key>\s*<Value>\s*<Single Type="string">([^<]+)</Single>'
                    matches1 = re.findall(p1, content, re.DOTALL)
                    for lib_name, lib_info in matches1:
                        raw_libraries.append((lib_name.strip(), lib_info.strip()))

                    # Pattern 2: DefaultResolution or Name tags with full info string
                    # Filter: ensure no '<' in properties to avoid XML junk
                    p2 = r'<Single Name="(?:DefaultResolution|Name)" Type="string">([^<,]+,\s*[^<,\(]+\s*\([^<,\)]+\))</Single>'
                    matches2 = re.findall(p2, content)
                    for lib_info in matches2:
                        name = lib_info.split(',')[0].strip()
                        raw_libraries.append((name, lib_info.strip()))

                    # Pattern 3: Any other text blocks following the library info format
                    p3 = r'>([^<,]+,\s*[^<,\(]+\s*\([^<,\)]+\))<'
                    matches3 = re.findall(p3, content)
                    for lib_info in matches3:
                        name = lib_info.split(',')[0].strip()
                        raw_libraries.append((name, lib_info.strip()))
                    
                    for lib_name, lib_info in raw_libraries:
                        # Skip if it looks like XML junk (contains brackets or too long)
                        if '<' in lib_name or '>' in lib_name or len(lib_name) > 100:
                            continue

                        version = "Unknown"
                        company = "Unknown"
                        namespace = lib_name
                        
                        # Parse "LibName, Version (Company)" format
                        info_match = re.search(r'([^,]+),\s*([^\(]+)\s*\(([^\)]+)\)', lib_info)
                        if info_match:
                            version = info_match.group(2).strip()
                            company = info_match.group(3).strip()
                        else:
                            # Try simpler format: "LibName, Version"
                            info_match = re.search(r'([^,]+),\s*([^<]+)', lib_info)
                            if info_match:
                                version = info_match.group(2).strip()
                        
                        libraries.append({
                            "name": lib_name,
                            "version": version,
                            "company": company,
                            "namespace": namespace,
                            "is_placeholder": True
                        })
                    
                    # Cleanup
                    os.remove(xml_path)
            except Exception as e:
                log_warning("Could not extract libraries from manager: " + safe_str(e))
                continue
                
    except Exception as e:
        log_error("Error extracting libraries: " + safe_str(e))
    
    # Deduplicate libraries by name
    # If multiple versions exist, prefer a specific version over '*'
    unique_libs_dict = {}
    for lib in libraries:
        name = lib["name"]
        version = lib["version"]
        
        if name not in unique_libs_dict:
            unique_libs_dict[name] = lib
        else:
            # If existing is '*' and new is specific, replace it
            current_version = unique_libs_dict[name]["version"]
            if current_version == "*" and version != "*":
                unique_libs_dict[name] = lib
            # Also prefer longer version strings if both are specific
            elif version != "*" and current_version != "*" and len(version) > len(current_version):
                unique_libs_dict[name] = lib
    
    unique_libs = sorted(unique_libs_dict.values(), key=lambda x: x["name"])
    return unique_libs


def load_libraries(base_dir):
    """
    Load library list from _libraries.csv.
    """
    libraries = []
    csv_path = os.path.join(base_dir, "config", "_libraries.csv")
    
    if not os.path.exists(csv_path):
        # Fallback to root for backward compatibility
        root_csv = os.path.join(base_dir, "_libraries.csv")
        if os.path.exists(root_csv):
            csv_path = root_csv
        else:
            return libraries

    try:
        if sys.version_info[0] < 3:
            f = open(csv_path, 'rb')
        else:
            f = open(csv_path, 'r', encoding='utf-8', newline='')
        
        try:
            reader = csv.reader(f, delimiter=';')
            header = next(reader, None) # Skip header
            
            if header:
                for row in reader:
                    if not row or len(row) < 5: continue
                    
                    if sys.version_info[0] < 3:
                        row = [cell.decode('utf-8') for cell in row]
                    
                    name, version, company, namespace, is_placeholder = row[:5]
                    libraries.append({
                        "name": name,
                        "version": version,
                        "company": company,
                        "namespace": namespace,
                        "is_placeholder": is_placeholder.lower() == "true"
                    })
        finally:
            f.close()
    except Exception as e:
        log_error("Error reading _libraries.csv: " + safe_str(e))
        
    return libraries


def save_libraries(base_dir, libraries):
    """
    Save library list to _libraries.csv.
    """
    config_dir = os.path.join(base_dir, "config")
    if not os.path.exists(config_dir):
        try:
            os.makedirs(config_dir)
        except:
            pass
            
    csv_path = os.path.join(config_dir, "_libraries.csv")
    csv_tmp = csv_path + ".tmp"
    
    def _atomic_replace(src, dst):
        if hasattr(os, 'replace'):
            os.replace(src, dst)
        else:
            if os.path.exists(dst):
                os.remove(dst)
            os.rename(src, dst)

    try:
        if sys.version_info[0] < 3:
            f = open(csv_tmp, 'wb')
        else:
            f = open(csv_tmp, 'w', encoding='utf-8', newline='')
        
        try:
            writer = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
            # Header
            writer.writerow(["Name", "Version", "Company", "Namespace", "IsPlaceholder"])
            
            for lib in libraries:
                row = [
                    safe_str(lib.get("name", "")),
                    safe_str(lib.get("version", "")),
                    safe_str(lib.get("company", "")),
                    safe_str(lib.get("namespace", "")),
                    safe_str(lib.get("is_placeholder", "False"))
                ]
                
                if sys.version_info[0] < 3:
                    unicode_type = unicode if sys.version_info[0] < 3 else str
                    row = [cell.encode('utf-8') if isinstance(cell, unicode_type) else str(cell) for cell in row]
                
                writer.writerow(row)
        finally:
            f.close()
        
        _atomic_replace(csv_tmp, csv_path)
        return True
    except Exception as e:
        log_error("Error saving _libraries.csv: " + safe_str(e))
        if os.path.exists(csv_tmp):
            try: os.remove(csv_tmp)
            except: pass
        return False


def parse_st_file(file_path):
    """
    Parse an ST file and extract declaration and implementation sections.
    Returns tuple (declaration, implementation).
    """
    try:
        with codecs.open(file_path, "r", "utf-8") as f:
            content = f.read()
    except Exception as e:
        print("Error reading file " + file_path + ": " + safe_str(e))
        return None, None
    
    declaration = None
    implementation = None
    
    if IMPL_MARKER in content:
        parts = content.split(IMPL_MARKER)
        declaration = parts[0].strip()
        implementation = parts[1].strip() if len(parts) > 1 else None
    else:
        # No implementation marker - entire content is declaration
        declaration = content.strip()
    
    return declaration, implementation


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
    
    # Return first match if no parent filter or no parent match
    return found[0]


def backup_project_binary(export_dir, projects_obj=None):
    """
    Copy the current project binary to the /project folder.
    Forces a project save before copying to ensure the backup is current.
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
            print("Debug: Cannot identify project for backup (projects_obj missing or invalid).")
            return

        # Force save to ensure we backup the latest state
        try:
            projects_obj.primary.save()
            log_info("Project saved for backup.")
        except Exception as e:
            msg = "Could not save project before backup: " + safe_str(e)
            log_warning(msg)
            print("Debug: " + msg)

        if not hasattr(projects_obj.primary, "path") or not projects_obj.primary.path:
            log_warning("Project not saved to disk yet. Skipping binary backup.")
            print("Debug: Project has no path on disk.")
            return

        project_path = projects_obj.primary.path
        project_folder = os.path.join(export_dir, "project")
        
        if not os.path.exists(project_folder):
            os.makedirs(project_folder)
            
        # Determine target filename
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
        
        # Check if we should delete old backups if using a fixed name? 
        # Actually user said "always save to one file", so overwriting is fine.
        
        shutil.copy2(project_path, target_path)
        log_info("Binary backup updated: project/" + file_name)
        print("Binary backup updated.")
        
    except Exception as e:
        log_error("Warning: Could not create binary backup: " + str(e))
        print("Warning: Could not create binary backup: " + str(e))
