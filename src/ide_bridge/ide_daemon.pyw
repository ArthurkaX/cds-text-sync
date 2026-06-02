# -*- coding: utf-8 -*-
"""
ide_daemon.pyw — CODESYS Background Daemon (IronPython).
Run via Project_daemon.py.
Runs in memory without blocking CODESYS.
Listens on Named Pipe for commands from external CLI.
"""

from __future__ import print_function
import clr
import sys
import os
import io
import json
import time
import traceback
import struct

# Add ide_bridge dir to path for helper imports
_DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
if _DAEMON_DIR not in sys.path:
    sys.path.insert(0, _DAEMON_DIR)

import ide_online_helpers as _ide_online_helpers
try:
    reload(_ide_online_helpers)
except Exception:
    pass

connect_to_device_impl = _ide_online_helpers.connect_to_device_impl
disconnect_from_device_impl = _ide_online_helpers.disconnect_from_device_impl
read_variable_impl = _ide_online_helpers.read_variable_impl
write_variable_impl = _ide_online_helpers.write_variable_impl
set_simulation_mode_impl = _ide_online_helpers.set_simulation_mode_impl
set_credentials_impl = _ide_online_helpers.set_credentials_impl
get_application_state_impl = _ide_online_helpers.get_application_state_impl

clr.AddReference("System.IO.Pipes")
clr.AddReference("System.IO")
clr.AddReference("System.Threading")

from System.IO.Pipes import NamedPipeServerStream, NamedPipeClientStream, PipeDirection
from System.Threading import Thread, ThreadStart, ApartmentState

# ── Global state (lives in sys) ───────────────────────────────────

if not hasattr(sys, "_codesys_daemon"):
    sys._codesys_daemon = {
        "running": False,
        "pipe_server": None,
        "pipe_thread": None,
        "projects": None,
        "system": None,
        "started_at": None,
    }

PIPE_NAME = "cds-daemon-" + os.environ.get("USERNAME", "default")
LOG_FILE = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "cds-daemon-debug.log")


def _now():
    return time.strftime("%H:%M:%S")


def _log(msg):
    line = "[daemon {0}] {1}".format(_now(), msg)
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Capture CODESYS global objects ────────────────────────────────────

def capture_codesys_globals():
    g = globals()
    projects_obj = g.get("projects")
    system_obj = g.get("system")

    if projects_obj is not None and hasattr(projects_obj, "primary"):
        sys._codesys_daemon["projects"] = projects_obj
        _log("projects captured from globals()")
    else:
        try:
            import __main__
            if hasattr(__main__, "projects"):
                proj = __main__.projects
                if hasattr(proj, "primary"):
                    sys._codesys_daemon["projects"] = proj
                    _log("projects captured from __main__")
            if hasattr(__main__, "system"):
                sys._codesys_daemon["system"] = __main__.system
                _log("system captured from __main__")
        except Exception:
            pass

    if system_obj is not None:
        sys._codesys_daemon["system"] = system_obj
        _log("system captured from globals()")

    if sys._codesys_daemon["projects"] is None:
        _log("WARNING: projects not captured!")
    if sys._codesys_daemon["system"] is None:
        _log("WARNING: system not captured!")


def _show_info(msg):
    try:
        system = sys._codesys_daemon.get("system")
        if system and hasattr(system, "ui") and hasattr(system.ui, "info"):
            system.ui.info(msg)
            return
    except Exception:
        pass
    _log("[INFO] {0}".format(msg))


# ── Pipe Server ──────────────────────────────────────────────────────────

class DaemonPipeServer(object):
    def __init__(self, pipe_name):
        self.pipe_name = pipe_name
        self._pipe = None
        self._running = False

    def start(self):
        self._running = True
        _log("Pipe server thread started.")
        for attempt in range(30):
            try:
                self._pipe = NamedPipeServerStream(self.pipe_name)
                _log("Pipe created: {0}".format(self.pipe_name))
                break
            except Exception as e:
                _log("Pipe create attempt {0} failed: {1}".format(attempt + 1, e))
                if attempt < 29:
                    time.sleep(0.5)
                else:
                    _log("Failed to create pipe after 30 attempts.")
                    self._running = False
                    return
        self._listen_loop()
        _log("Pipe server thread ended.")

    def stop(self):
        self._running = False
        # Send a stop command to unblock WaitForConnection and trigger clean shutdown
        try:
            client = NamedPipeClientStream(".", self.pipe_name, PipeDirection.Out)
            client.Connect(3000)
            # Send stop command using length-prefix protocol
            stop_msg = json.dumps({"method": "stop", "params": {}}).encode("utf-8")
            n = len(stop_msg)
            client.WriteByte(n & 0xFF)
            client.WriteByte((n >> 8) & 0xFF)
            client.WriteByte((n >> 16) & 0xFF)
            client.WriteByte((n >> 24) & 0xFF)
            for ch in stop_msg:
                client.WriteByte(ord(ch))
            client.Flush()
            client.Close()
        except Exception as e:
            _log("Stop: client connect/send failed: {0}".format(e))
            # Fallback: dispose the pipe to unblock WaitForConnection
            try:
                if self._pipe:
                    self._pipe.Dispose()
            except Exception:
                pass

    def _listen_loop(self):
        while self._running and self._pipe:
            try:
                self._pipe.WaitForConnection()
                if not self._running:
                    # Stop was requested during WaitForConnection
                    try:
                        self._pipe.Disconnect()
                    except Exception:
                        pass
                    break
                msg = self._read_message()
                if msg is None:
                    try:
                        self._pipe.Disconnect()
                    except Exception:
                        pass
                    continue
                method = msg.get("method", "")
                params = msg.get("params", {})
                response = self._handle_command(method, params)
                self._send_response(response)
                try:
                    self._pipe.Disconnect()
                except Exception:
                    pass
                if method == "stop":
                    self._running = False
                    break
            except Exception as e:
                _log("Pipe error: {0}\n{1}".format(e, traceback.format_exc()))
                try:
                    self._pipe.Disconnect()
                except Exception:
                    pass
                if not self._running:
                    break
                time.sleep(0.2)

    def _read_message(self):
        """Read a length-prefixed JSON message via ReadByte()."""
        try:
            raw_len = []
            while len(raw_len) < 4:
                b = self._pipe.ReadByte()
                if b == -1:
                    return None
                raw_len.append(b)
            msg_len = (raw_len[0] | (raw_len[1] << 8) |
                       (raw_len[2] << 16) | (raw_len[3] << 24))
            if msg_len <= 0 or msg_len > 1048576:
                return None
            raw_data = []
            while len(raw_data) < msg_len:
                b = self._pipe.ReadByte()
                if b == -1:
                    return None
                raw_data.append(b)
            raw_str = ''.join(chr(b) for b in raw_data)
            return json.loads(raw_str.decode('utf-8'))
        except Exception as e:
            _log("Read error: {0}".format(e))
            return None

    def _send_response(self, data):
        """Send JSON response via WriteByte()."""
        try:
            msg_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
            n = len(msg_bytes)
            self._pipe.WriteByte(n & 0xFF)
            self._pipe.WriteByte((n >> 8) & 0xFF)
            self._pipe.WriteByte((n >> 16) & 0xFF)
            self._pipe.WriteByte((n >> 24) & 0xFF)
            for b in msg_bytes:
                self._pipe.WriteByte(ord(b))
            self._pipe.Flush()
        except Exception as e:
            _log("Send error: {0}".format(e))

    def _handle_command(self, method, params):
        _log("Command: {0} {1}".format(method, json.dumps(params or {})))
        if method == "ping":
            return {"ok": True, "data": {
                "status": "pong",
                "pid": os.getpid(),
            }}
        elif method == "stop":
            _log("Stop command received.")
            sys._codesys_daemon["running"] = False
            return {"ok": True, "data": {"message": "Daemon stopping..."}}
        elif method == "reload":
            return self._reload()
        elif method == "status":
            return {"ok": True, "data": {
                "running": sys._codesys_daemon.get("running", False),
                "projects_captured": sys._codesys_daemon.get("projects") is not None,
                "system_captured": sys._codesys_daemon.get("system") is not None,
                "started_at": sys._codesys_daemon.get("started_at"),
                "pid": os.getpid(),
            }}
        elif method == "project_info":
            return self._get_project_info()
        elif method == "project_tree":
            depth = params.get("depth", 0)
            return self._get_project_tree(depth=depth)
        elif method == "read_object":
            return self._read_object(params)
        elif method == "project_open":
            return self._project_open(params)
        elif method == "project_close":
            return self._project_close()
        elif method == "project_list":
            return self._project_list()
        elif method == "export":
            return self._ide_export(params)
        elif method == "build":
            return self._ide_build()
        elif method == "list_devices":
            return self._list_devices()
        elif method == "compare":
            return self._ide_compare(params)
        elif method in ("import", "validate", "resources"):
            return self._call_engine_cli(method, params)
        elif method == "exec":
            args = params.get("args", [])
            if not args:
                return {"ok": False, "error": "Missing 'args' in params"}
            return self._call_engine_cli_raw(args)
        elif method == "discover":
            return self._discover()
        elif method == "device_status":
            return self._device_status(params)
        elif method == "connect_to_device":
            return self._connect_to_device(params)
        elif method == "disconnect_from_device":
            return self._disconnect_from_device(params)
        elif method == "read_variable":
            return self._read_variable(params)
        elif method == "write_variable":
            return self._write_variable(params)
        elif method == "set_simulation_mode":
            return self._set_simulation_mode(params)
        elif method == "set_credentials":
            return self._set_credentials(params)
        elif method == "test-online":
            return self._test_online(params)
        elif method == "application_state":
            return self._application_state(params)
        else:
            return {"ok": False, "error": "Unknown method: {0}".format(method)}

# ── Actions on project ───────────────────────────────────────────

    def _get_active_project(self):
        projects = sys._codesys_daemon.get("projects")
        if projects is None:
            return None, {"ok": False, "error": "projects not captured"}
        try:
            project = projects.primary
            if project is None:
                return None, {"ok": False, "error": "No active project"}
            return project, None
        except Exception as e:
            return None, {"ok": False, "error": "Project error: {0}".format(e)}

    def _obj_name(self, obj):
        try:
            n = obj.get_name()
            if n:
                return str(n)
        except Exception:
            pass
        try:
            n = obj.Name
            if n:
                return str(n)
        except Exception:
            pass
        try:
            n = obj.Title
            if n:
                return str(n)
        except Exception:
            pass
        return ""

    def _get_project_info(self):
        project, err = self._get_active_project()
        if err:
            return err
        try:
            info = {
                "name": self._obj_name(project),
                "captured_at": sys._codesys_daemon.get("started_at", ""),
                "daemon_pid": os.getpid(),
            }
            for attr in ['filename', 'FileName', 'FullName', 'Path']:
                try:
                    val = getattr(project, attr)
                    if val:
                        info["filename"] = str(val)
                        break
                except Exception:
                    pass
            try:
                children = project.get_children(recursive=True)
                info["object_count"] = len(list(children))
            except Exception:
                info["object_count"] = -1
            try:
                apps = project.get_children()
                app_list = []
                for app in apps:
                    name = self._obj_name(app)
                    if name:
                        app_list.append(name)
                info["applications"] = app_list
            except Exception:
                pass
            return {"ok": True, "data": info}
        except Exception as e:
            return {"ok": False, "error": "Project info error: {0}".format(e)}

    def _get_project_tree(self, depth=0):
        project, err = self._get_active_project()
        if err:
            return err
        try:
            tree = self._build_tree(project, depth=depth, current_depth=0)
            return {"ok": True, "data": tree}
        except Exception as e:
            return {"ok": False, "error": "Project tree error: {0}".format(e)}

    def _build_tree(self, obj, depth=0, current_depth=0):
        node = {"name": self._obj_name(obj)}
        try:
            guid = obj.Guid
            if guid:
                node["guid"] = str(guid)
        except Exception:
            pass
        if depth > 0 and current_depth >= depth:
            return node
        try:
            children = obj.get_children()
            child_list = []
            for child in children:
                child_list.append(self._build_tree(child, depth=depth,
                                  current_depth=current_depth + 1))
            if child_list:
                node["children"] = child_list
        except Exception:
            pass
        return node

    def _read_object(self, params):
        project, err = self._get_active_project()
        if err:
            return err
        path = params.get("path", "")
        guid = params.get("guid", "")
        name = params.get("name", "")
        try:
            target = None
            all_objs = list(project.get_children(recursive=True))
            if guid:
                for obj in all_objs:
                    try:
                        if str(obj.Guid) == guid:
                            target = obj
                            break
                    except Exception:
                        pass
            if target is None and name:
                for obj in all_objs:
                    if self._obj_name(obj) == name:
                        target = obj
                        break
            if target is None and path:
                for obj in all_objs:
                    if self._build_path(obj) == path:
                        target = obj
                        break
            if target is None:
                return {"ok": False, "error": "Object not found."}
            import tempfile
            tmp = tempfile.mktemp(suffix=".xml")
            try:
                project.export_native([target], tmp, recursive=False)
                with io.open(tmp, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                info = {
                    "name": self._obj_name(target),
                    "content": content,
                    "content_length": len(content),
                }
                try:
                    info["guid"] = str(target.Guid)
                except Exception:
                    pass
                return {"ok": True, "data": info}
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        except Exception as e:
            return {"ok": False, "error": "Read error: {0}".format(e)}

    def _project_open(self, params):
        path = params.get("path", "")
        if not path:
            return {"ok": False, "error": "Missing 'path' parameter"}
        if not os.path.exists(path):
            return {"ok": False, "error": "File not found: {0}".format(path)}
        projects = sys._codesys_daemon.get("projects")
        if projects is None:
            return {"ok": False, "error": "projects not captured"}
        try:
            projects.open(path)
            _log("Project opened: {0}".format(path))
            return {"ok": True, "data": {"message": "Project opened", "path": path}}
        except Exception as e:
            return {"ok": False, "error": "Failed to open project: {0}".format(e)}

    def _project_close(self):
        project, err = self._get_active_project()
        if err:
            return err
        try:
            project.close()
            _log("Project closed.")
            return {"ok": True, "data": {"message": "Project closed"}}
        except Exception as e:
            return {"ok": False, "error": "Failed to close project: {0}".format(e)}

    def _project_list(self):
        projects = sys._codesys_daemon.get("projects")
        if projects is None:
            return {"ok": False, "error": "projects not captured"}
        try:
            proj_list = []
            count = 0
            try:
                count = projects.Count
            except Exception:
                pass
            if count == 0:
                try:
                    count = projects.count
                except Exception:
                    pass
            for i in range(count):
                try:
                    proj = projects.Item(i)
                except Exception:
                    try:
                        proj = projects[i]
                    except Exception:
                        continue
                try:
                    name = self._obj_name(proj)
                    fname = ""
                    try:
                        fname = str(proj.filename)
                    except Exception:
                        pass
                    is_primary = False
                    try:
                        is_primary = proj == projects.primary
                    except Exception:
                        pass
                    proj_list.append({
                        "name": name, "filename": fname, "is_primary": is_primary,
                    })
                except Exception:
                    pass
            if not proj_list:
                try:
                    primary = projects.primary
                    if primary is not None:
                        name = self._obj_name(primary)
                        fname = ""
                        try:
                            fname = str(primary.filename)
                        except Exception:
                            pass
                        proj_list.append({
                            "name": name, "filename": fname, "is_primary": True,
                        })
                except Exception:
                    pass
            return {"ok": True, "data": {"projects": proj_list}}
        except Exception as e:
            return {"ok": False, "error": "List error: {0}".format(e)}

    # ── Export ─────────────────────────────────────────────────────────

    def _ide_export(self, params):
        project, err = self._get_active_project()
        if err:
            return err
        out_path = params.get("output", "")
        if not out_path:
            out_path = os.path.join(
                os.environ.get("TEMP", "C:\\Temp"),
                "cds-snapshot-{0}.xml".format(time.strftime("%Y%m%d_%H%M%S")))
        try:
            output_dir = os.path.dirname(out_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            objects = list(project.get_children(recursive=True))
            import tempfile as _tf
            fd, tmp_path = _tf.mkstemp(prefix="cds_export_", suffix=".xml", dir=output_dir or None)
            os.close(fd)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            try:
                project.export_native(objects, tmp_path, recursive=False)
                from ide_online_helpers import atomic_write
                # Read the temp export and write atomically to output
                with open(tmp_path, 'rb') as f:
                    content = f.read()
                atomic_write(out_path, content)
                os.remove(tmp_path)
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                raise
            size = os.path.getsize(out_path)
            _log("Exported snapshot: {0} ({1} bytes)".format(out_path, size))
            return {"ok": True, "data": {"path": out_path, "size": size}}
        except Exception as e:
            return {"ok": False, "error": "Export error: {0}".format(e)}

    # ── Compare ────────────────────────────────────────────────────────

    def _ide_compare(self, params):
        """Compare live project against a snapshot, output diff to stdout."""
        project, err = self._get_active_project()
        if err:
            return err
        against = params.get("against", "")
        if not against or not os.path.exists(against):
            return {"ok": False, "error": "Missing or invalid 'against' parameter (path to snapshot)"}
        try:
            # Export current project to temp
            import tempfile as _tf
            fd, tmp_path = _tf.mkstemp(prefix="cds_compare_", suffix=".xml")
            os.close(fd)
            try:
                objects = list(project.get_children(recursive=True))
                fd2, export_path = _tf.mkstemp(prefix="cds_live_", suffix=".xml")
                os.close(fd2)
                try:
                    os.remove(export_path)
                except Exception:
                    pass
                try:
                    project.export_native(objects, export_path, recursive=False)
                except Exception:
                    if os.path.exists(export_path):
                        try:
                            os.remove(export_path)
                        except Exception:
                            pass
                    raise
                # Run diff via python's built-in diff or xml comparison
                # Simple approach: use subprocess to run a diff command
                diff_lines = []
                diff_lines.append("Comparing live project with: {0}".format(against))
                diff_lines.append("=" * 60)
                import subprocess
                # Try fc (Windows) or diff
                # Note: IronPython 2.7 — no capture_output, no text= kwarg
                for cmd in [
                    ["fc", "/N", export_path, against],
                    ["diff", "-u", export_path, against],
                ]:
                    try:
                        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE,
                                             creationflags=0x08000000,
                                             shell=True)
                        out_bytes, err_bytes = p.communicate()
                        out = (out_bytes.decode('utf-8', errors='replace') if out_bytes else '')
                        err = (err_bytes.decode('utf-8', errors='replace') if err_bytes else '')
                        combined = out + err
                        if combined.strip():
                            diff_lines.append(combined[:50000])
                        else:
                            diff_lines.append("(files are identical)" + 
                                              chr(10) + "  Live: " + export_path + 
                                              chr(10) + "  Target: " + against)
                        break
                    except Exception as e:
                        _log("Diff tool failed: {0} {1}".format(type(e).__name__, str(e)[:100]))
                else:
                    diff_lines.append("(no diff tool available, files at:)")
                    diff_lines.append("  Live: " + export_path)
                    diff_lines.append("  Target: " + against)
                diff_text = chr(10).join(diff_lines)
                _log("Compare done, diff length: {0}".format(len(diff_text)))
                return {"ok": True, "data": {
                    "diff": diff_text,
                    "live_snapshot": export_path,
                    "target_snapshot": against,
                }}
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            return {"ok": False, "error": "Compare error: {0}".format(e)}

    # ── Build ──────────────────────────────────────────────────────────

    def _ide_build(self):
        project, err = self._get_active_project()
        if err:
            return err
        try:
            # Check what's available on project and system
            found = []
            for attr in ['Build', 'Make', 'Compile', 'GenerateCode', 'CreateBuild',
                         'BuildProject', 'BuildPlc', 'Generate',
                         'get_Build', 'get_Make', 'get_Compile']:
                try:
                    if hasattr(project, attr):
                        fn = getattr(project, attr)
                        c = callable(fn)
                        found.append('project.' + attr + '(c=' + str(c) + ')')
                except Exception as ex:
                    found.append('project.' + attr + '(err)')
            system = sys._codesys_daemon.get("system")
            if system:
                for attr in ['Tools', 'Build', 'IDE', 'Project']:
                    try:
                        if hasattr(system, attr):
                            t = getattr(system, attr)
                            found.append('system.' + attr)
                            for sub in ['Build', 'BuildProject', 'Make', 'Compile']:
                                try:
                                    if hasattr(t, sub):
                                        fn = getattr(t, sub)
                                        found.append('system.' + attr + '.' + sub + '(c=' + str(callable(fn)) + ')')
                                except Exception:
                                    pass
                    except Exception:
                        pass
                # Also check system directly
                for attr in ['Build', 'BuildProject']:
                    try:
                        if hasattr(system, attr):
                            fn = getattr(system, attr)
                            found.append('system.' + attr + '(c=' + str(callable(fn)) + ')')
                    except Exception:
                        pass
            _log("Build methods: " + ', '.join(found))

            # Try in order
            candidates = [
                (lambda: project.Build(), 'project.Build()'),
                (lambda: project.Make(), 'project.Make()'),
                (lambda: project.Compile(), 'project.Compile()'),
                (lambda: project.GenerateCode(), 'project.GenerateCode()'),
            ]
            if system:
                try:
                    t = system.Tools
                    candidates.append((lambda: t.Build(project), 'system.Tools.Build(project)'))
                except Exception:
                    pass
                try:
                    b = system.Build
                    candidates.append((lambda: b.Build(project), 'system.Build.Build(project)'))
                    candidates.append((lambda: system.Build(project), 'system.Build(project)'))
                except Exception:
                    pass
                try:
                    candidates.append((lambda: system.Build(project), 'system.Build(project)'))
                except Exception:
                    pass

            for fn, name in candidates:
                try:
                    result = fn()
                    code = result if isinstance(result, int) else 0
                    _log("Build OK via {0}, code={1}".format(name, code))
                    return {"ok": code == 0,
                            "data": {"build_code": code,
                                     "message": "Build ({0}) code {1}".format(name, code)}}
                except Exception:
                    pass
            return {"ok": False,
                    "error": "Build not available. Found: " + ', '.join(found) if found else "nothing"}
        except Exception as e:
            return {"ok": False, "error": "Build error: {0}".format(e)}

    # ── List Devices ───────────────────────────────────────────────────

    def _list_devices(self):
        project, err = self._get_active_project()
        if err:
            return err
        try:
            devices = []
            all_objs = list(project.get_children(recursive=True))
            for obj in all_objs:
                try:
                    path = self._build_path(obj)
                    name = self._obj_name(obj)
                    if not name:
                        continue
                    children = list(obj.get_children())
                    if children:
                        for child in children:
                            cn = self._obj_name(child)
                            if cn and any(k in cn.lower() for k in
                                         ['ethernet', 'modbus', 'can', 'profinet',
                                          'ethercat', 'device', 'plc', 'drive']):
                                devices.append({"name": name, "path": path})
                                break
                except Exception:
                    pass
            return {"ok": True, "data": {"devices": devices}}
        except Exception as e:
            return {"ok": False, "error": "List devices error: {0}".format(e)}

    # ── Device Status ────────────────────────────────────────────────

    def _device_status(self, params):
        """Check online/connection status of devices."""
        project, err = self._get_active_project()
        if err:
            return err
        try:
            device_filter = (params.get("device") or "").lower()
            all_objs = list(project.get_children(recursive=True))
            status_list = []
            # Properties to try for each object
            status_props = [
                'IsOnline', 'IsConnected', 'State', 'Online', 'Connected',
                'Status', 'IsActive', 'IsRunning', 'DeviceState',
                'get_IsOnline', 'get_IsConnected', 'get_State',
            ]
            for obj in all_objs:
                try:
                    name = self._obj_name(obj)
                    if not name:
                        continue
                    path = self._build_path(obj)
                    entry = {"name": name, "path": path}
                    for prop in status_props:
                        try:
                            val = getattr(obj, prop)
                            if val is not None:
                                if callable(val):
                                    entry[prop] = str(val())
                                else:
                                    entry[prop] = str(val)
                        except Exception:
                            pass
                    if len(entry) > 2:  # has at least one status prop
                        if not device_filter or device_filter in name.lower():
                            status_list.append(entry)
                except Exception:
                    pass
            return {"ok": True, "data": {"devices": status_list}}
        except Exception as e:
            return {"ok": False, "error": "Device status error: {0}".format(e)}

    # ── Online connectivity ───────────────────────────────────────────

    def _connect_to_device(self, params):
        """Connect to a real PLC device."""
        project, err = self._get_active_project()
        if err:
            return err
        try:
            ip_address = params.get("ipAddress", "")
            gateway_name = params.get("gatewayName", "Gateway-1")
            result = connect_to_device_impl(project, ip_address, gateway_name)
            _log("Connected to device: {0}".format(result.get("application", "?")))
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": "Connect error: {0}\n{1}".format(e, traceback.format_exc())}

    def _disconnect_from_device(self, params):
        """Disconnect from PLC device."""
        project, err = self._get_active_project()
        if err:
            return err
        try:
            result = disconnect_from_device_impl(project)
            _log("Disconnected from device.")
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": True, "data": {"state": "disconnected", "note": str(e)}}

    def _read_variable(self, params):
        """Read a PLC variable value."""
        project, err = self._get_active_project()
        if err:
            return err
        try:
            variable_name = params.get("name", "")
            result = read_variable_impl(project, variable_name)
            _log("Read variable: {0} = {1}".format(variable_name, result.get("value", "?")))
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": "Read variable error: {0}\n{1}".format(e, traceback.format_exc())}

    def _write_variable(self, params):
        """Write a value to a PLC variable."""
        project, err = self._get_active_project()
        if err:
            return err
        try:
            variable_name = params.get("name", "")
            value = params.get("value")
            result = write_variable_impl(project, variable_name, value)
            _log("Write variable: {0} = {1}".format(variable_name, value))
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": "Write variable error: {0}\n{1}".format(e, traceback.format_exc())}

    def _set_simulation_mode(self, params):
        """Enable/disable PLC simulation mode."""
        project, err = self._get_active_project()
        if err:
            return err
        try:
            enable_str = str(params.get("enable", "true")).lower()
            enable = enable_str in ("true", "1", "yes", "on")
            result = set_simulation_mode_impl(project, enable)
            _log("Simulation mode: {0}".format(enable))
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": "Simulation mode error: {0}\n{1}".format(e, traceback.format_exc())}

    def _set_credentials(self, params):
        """Set PLC login credentials."""
        try:
            username = params.get("username", "")
            password = params.get("password", "")
            result = set_credentials_impl(username, password)
            _log("Credentials set for: {0}".format(username))
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": "Credentials error: {0}\n{1}".format(e, traceback.format_exc())}

    def _reload(self):
        """Reload daemon code from file, updating all command handlers."""
        try:
            _log("Reloading daemon code...")
            # Re-capture globals in case they changed
            capture_codesys_globals()
            # Read the daemon file
            daemon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide_daemon.pyw")
            if not os.path.exists(daemon_path):
                daemon_path = os.path.abspath(__file__)
            _log("Reloading from: {0}".format(daemon_path))
            import io
            with io.open(daemon_path, "r", encoding="utf-8-sig") as f:
                code = f.read()
            # Create a namespace for the new code
            new_ns = {"__builtins__": __builtins__, "__name__": "__main__", "__file__": daemon_path}
            # Copy essential globals
            for k in ("projects", "system", "NamedPipeServerStream", "NamedPipeClientStream",
                      "Thread", "ThreadStart", "ApartmentState", "clr", "sys", "os",
                      "time", "json", "traceback"):
                if k in globals():
                    new_ns[k] = globals()[k]
            # Execute the code to get the new DaemonPipeServer class
            exec(code, new_ns)
            # Update self's class to the new one
            new_class = new_ns.get("DaemonPipeServer")
            if new_class:
                self.__class__ = new_class
                _log("Reloaded DaemonPipeServer class successfully.")
                return {"ok": True, "data": {"message": "Daemon reloaded.", "class": str(new_class)}}
            else:
                _log("Reload failed: DaemonPipeServer not found in reloaded code.")
                return {"ok": False, "error": "DaemonPipeServer class not found in reloaded code"}
        except Exception as e:
            _log("Reload error: {0}".format(e))
            import traceback as _tb
            _log(_tb.format_exc())
            return {"ok": False, "error": "Reload error: {0}\n{1}".format(e, _tb.format_exc())}

    def _test_online(self, params):
        """Test online connection - exactly like Project_online_test.py."""
        import __main__
        tb = []
        try:
            _log("test_online: step 1 - importing scriptengine")
            import scriptengine as se
            tb.append("se imported OK")
            _log("test_online: step 2 - getting project")
            prj = projects.primary
            tb.append("project: " + str(prj)[:80])
            _log("test_online: step 3 - getting app")
            app = prj.active_application
            tb.append("app: " + str(app)[:80])
            if app is None:
                return {"ok": True, "data": {"state": "no app", "log": tb}}
            _log("test_online: step 4 - calling create_online_application")
            oa = se.online.create_online_application(app)
            tb.append("oa: " + str(oa)[:80])
            if oa is not None:
                state = str(oa.application_state)
                tb.append("state: " + state)
                try:
                    tb.append("oa dir: " + str([x for x in dir(oa) if not x.startswith('_')]))
                except Exception as e:
                    tb.append("oa dir error: " + str(e))
                try:
                    tb.append("oa type dir: " + str([x for x in dir(type(oa)) if not x.startswith('_')]))
                except Exception as e:
                    tb.append("oa type dir error: " + str(e))
            _log("test_online: step 5 - done, state=" + (str(oa.application_state) if oa else "None"))
            return {"ok": True, "data": {"state": str(oa) if oa else "None", "log": tb}}
        except Exception as e:
            _log("test_online EXCEPTION: " + str(e))
            import traceback
            tb.append("ERROR: " + str(e))
            tb.append(traceback.format_exc())
            return {"ok": False, "error": str(e), "log": tb}

    def _application_state(self, params):
        """Get current online application state."""
        try:
            import scriptengine as se
            prj = projects.primary
            app = prj.active_application
            if app is None:
                return {"ok": True, "data": {"state": "unknown", "note": "No active application"}}
            _log("app_state: calling create_online_application")
            oa = se.online.create_online_application(app)
            _log("app_state: oa=" + str(oa))
            if oa is None:
                return {"ok": True, "data": {"state": "disconnected"}}
            info = {}
            for attr in ["application_state", "is_connected", "is_running", "is_online"]:
                if hasattr(oa, attr):
                    try:
                        val = getattr(oa, attr)
                        if callable(val):
                            info[attr] = str(val())
                        else:
                            info[attr] = str(val)
                    except Exception:
                        pass
            _log("Application state: {0}".format(info.get("application_state", "?")))
            return {"ok": True, "data": info}
        except Exception as e:
            _log("app_state ERROR: {0}".format(e))
            import traceback as _tb
            _log(_tb.format_exc())
            err = "Application state error: " + str(e) + chr(10) + _tb.format_exc()
            return {"ok": False, "error": err}

    def _discover(self):
        info = {
            "pid": os.getpid(),
            "codesys_version": "",
            "pipe": PIPE_NAME,
            "projects": [],
        }
        try:
            system = sys._codesys_daemon.get("system")
            if system:
                try:
                    info["codesys_version"] = str(system.Version)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            projects = sys._codesys_daemon.get("projects")
            if projects:
                try:
                    primary = projects.primary
                    if primary:
                        info["active_project"] = self._obj_name(primary)
                        try:
                            info["active_project_path"] = str(primary.filename)
                        except Exception:
                            pass
                except Exception:
                    pass
                proj_list = []
                try:
                    count = projects.Count if hasattr(projects, 'Count') else 0
                    if count == 0:
                        count = projects.count if hasattr(projects, 'count') else 0
                except Exception:
                    count = 0
                for i in range(count):
                    try:
                        p = projects.Item(i)
                        proj_list.append({
                            "name": self._obj_name(p),
                            "filename": str(p.filename) if hasattr(p, 'filename') else "",
                        })
                    except Exception:
                        pass
                info["projects"] = proj_list
        except Exception:
            pass
        return {"ok": True, "data": info}

    def _build_path(self, obj):
        parts = []
        current = obj
        for _ in range(30):
            try:
                name = self._obj_name(current)
                if name:
                    parts.insert(0, name)
                try:
                    parent = current.parent
                except Exception:
                    parent = None
                if parent is None:
                    break
                current = parent
            except Exception:
                break
        return "/".join(parts)

    # ── Fallback to engine_cli (offline commands) ─────────────────────────

    def _call_engine_cli(self, command, params=None):
        return self._call_engine_cli_raw([command] + self._params_to_args(params or {}))

    def _params_to_args(self, params):
        args = []
        for key, value in params.items():
            if value is None or value is False:
                continue
            if isinstance(value, bool):
                if value:
                    args.append("--{0}".format(key.replace("_", "-")))
            else:
                args.append("--{0}".format(key.replace("_", "-")))
                args.append(str(value))
        return args

    def _call_engine_cli_raw(self, args):
        try:
            import subprocess
            script_dir = os.path.dirname(os.path.abspath(__file__))
            workspace = script_dir
            for _ in range(5):
                if (
                    os.path.isdir(os.path.join(workspace, "cli", "external_engine"))
                    or os.path.isdir(os.path.join(workspace, "src", "external_engine"))
                ):
                    break
                workspace = os.path.dirname(workspace)
            engine_cli = os.path.join(workspace, "cli", "external_engine", "engine_cli.py")
            if not os.path.exists(engine_cli):
                engine_cli = os.path.join(workspace, "src", "external_engine", "engine_cli.py")
            if not os.path.exists(engine_cli):
                return {"ok": False, "error": "engine_cli.py not found"}
            cmd = ["python", engine_cli] + args
            _log("Running: {0}".format(" ".join(cmd)))
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
            if os.name == 'nt':
                kwargs["creationflags"] = 0x08000000
            proc = subprocess.Popen(cmd, **kwargs)
            out, err = proc.communicate()
            out_text = out.decode("utf-8", "replace") if out else ""
            err_text = err.decode("utf-8", "replace") if err else ""
            _log("Engine CLI exit: {0}".format(proc.returncode))
            return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                    "stdout": out_text, "stderr": err_text}
        except Exception as e:
            return {"ok": False, "error": "Engine CLI error: {0}\n{1}".format(e, traceback.format_exc())}


# ── Main entry point ────────────────────────────────────────────────────

def start_daemon():
    if sys._codesys_daemon.get("running"):
        _log("Daemon already running.")
        return
    _log("=" * 50)
    _log("cds-text-sync Daemon starting...")
    _log("PID: {0}".format(os.getpid()))
    _log("Pipe: {0}".format(PIPE_NAME))
    _log("Log: {0}".format(LOG_FILE))
    capture_codesys_globals()
    sys._codesys_daemon["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sys._codesys_daemon["running"] = True
    pipe_server = DaemonPipeServer(PIPE_NAME)
    pipe_thread = Thread(ThreadStart(pipe_server.start))
    pipe_thread.IsBackground = True
    pipe_thread.SetApartmentState(ApartmentState.STA)
    pipe_thread.Start()
    sys._codesys_daemon["pipe_server"] = pipe_server
    sys._codesys_daemon["pipe_thread"] = pipe_thread
    projects_status = "OK" if sys._codesys_daemon.get("projects") else "NOT CAPTURED"
    system_status = "OK" if sys._codesys_daemon.get("system") else "NOT CAPTURED"
    _log("Daemon startup complete. projects={0} system={1}".format(
        projects_status, system_status))


def stop_daemon():
    pipe_server = sys._codesys_daemon.get("pipe_server")
    if pipe_server:
        pipe_server.stop()
    sys._codesys_daemon["running"] = False
    pipe_thread = sys._codesys_daemon.get("pipe_thread")
    if pipe_thread and pipe_thread.IsAlive:
        pipe_thread.Join(10000)
    # Dispose the old pipe to release the pipe name
    if pipe_server and hasattr(pipe_server, '_pipe') and pipe_server._pipe:
        try:
            pipe_server._pipe.Dispose()
            _log("Old pipe disposed.")
        except Exception as e:
            _log("Error disposing old pipe: {0}".format(e))
    sys._codesys_daemon["pipe_server"] = None
    sys._codesys_daemon["pipe_thread"] = None
    _log("Daemon stopped.")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else None
    if action == "reload":
        # Send reload command to running daemon
        _log("Sending reload command to running daemon...")
        pipe_server = sys._codesys_daemon.get("pipe_server")
        if pipe_server:
            result = pipe_server._reload()
            _log("Reload result: {0}".format(result))
        else:
            _log("No pipe_server found, starting daemon.")
            start_daemon()
    elif sys._codesys_daemon.get("running"):
        _log("Daemon is running. Stopping...")
        stop_daemon()
    else:
        start_daemon()


if __name__ == "__main__":
    main()
