# -*- coding: utf-8 -*-
"""Shared bootstrap helpers for the CODESYS-host product entrypoints."""
import os
import sys

def _script_dir(script_file=None):
 return os.path.dirname(os.path.abspath(script_file or __file__))


def ensure_runtime_path(script_file=None):
 script_dir = _script_dir(script_file)
 ide_bridge_dir = os.path.join(script_dir, "src", "ide_bridge")
 # Order matters: src/ide_bridge must outrank the body root. The root holds
 # Project_snapshooter.py, which differs from the bridge module
 # project_snapshooter.py only by case -- and Windows filesystems are
 # case-insensitive. Modules are now imported by name, not by path, so let
 # the bridge win instead of relying on the importer's case check.
 if script_dir not in sys.path:
  sys.path.insert(0, script_dir)
 if ide_bridge_dir not in sys.path:
  sys.path.insert(0, ide_bridge_dir)
 return ide_bridge_dir


def _module_file_exists(name, script_file=None):
 script_dir = _script_dir(script_file)
 for candidate in (
  os.path.join(script_dir, "src", "ide_bridge", name + ".py"),
  os.path.join(script_dir, name + ".py"),
 ):
  if os.path.isfile(candidate):
   return True
 return False


def import_runtime_module(name, script_file=None, force=False):
 ensure_runtime_path(script_file)

 if force and name in sys.modules:
  del sys.modules[name]

 if name in sys.modules:
  return sys.modules[name]

 try:
  __import__(name)
 except ImportError:
  # A module that is simply absent is a normal outcome - callers probe for
  # optional modules and handle None. A module whose file is right there but
  # fails to import is a defect, and swallowing it turns "broken" into
  # "missing": the caller degrades silently instead of showing the real error.
  if _module_file_exists(name, script_file):
   raise
  return None
 return sys.modules.get(name)


def preload_runtime_modules(module_names, script_file=None, force=False):
 ensure_runtime_path(script_file)
 loaded = {}
 for name in module_names:
  loaded[name] = import_runtime_module(name, script_file=script_file, force=force)
 return loaded


def run_project_command(command, params=None, script_file=None, caller_globals=None):
 runtime_module = import_runtime_module("codesys_runtime", script_file=script_file)
 if not runtime_module:
  raise RuntimeError("codesys_runtime.py not found.")
 return runtime_module.run_project_command(
  command,
  caller_globals=caller_globals,
  params=params,
  script_file=script_file,
 )


# ---------------------------------------------------------------------------
# Entrypoint manifest
#
# The single source of truth for the public CODESYS menu commands. Both the
# root scripts in the body and the generated stubs in ScriptDir go through
# launch(); cds_text_sync/install_menu.py reads this list to render the stubs.
# ---------------------------------------------------------------------------

ENTRYPOINTS = [
 {"name": "Project_directory", "kind": "command", "command": "directory",
  "alias": "set_base_directory",
  "summary": "Link the open project to a folder on disk"},
 {"name": "Project_options", "kind": "command", "command": "options",
  "summary": "Sync options and diagnostics"},
 {"name": "Project_export", "kind": "command", "command": "export",
  "summary": "Export the project to the disk view"},
 {"name": "Project_import", "kind": "command", "command": "import",
  "summary": "Import disk changes back into the project"},
 {"name": "Project_compare_ui", "kind": "command", "command": "compare_ui",
  "summary": "Compare with the visual diff window"},
 {"name": "Project_discover", "kind": "command", "command": "discover",
  "summary": "Report the device and application tree"},
 {"name": "Project_resources", "kind": "command", "command": "resources",
  "summary": "Report embedded resources"},
 {"name": "Project_build", "kind": "command", "command": "build",
  "summary": "Build the active application"},
 {"name": "Project_analyze_ui", "kind": "bridge",
  "module": "codesys_analyze_ui_launcher", "entry": "main",
  "entry_kwargs": ["params", "caller_globals"],
  "summary": "Open offline static analysis for this project's sync folder"},
 {"name": "Project_daemon", "kind": "bridge",
  "module": "codesys_daemon_launcher", "entry": "run",
  "entry_kwargs": ["params", "caller_globals"],
  "summary": "Run the reverse-pipe daemon for the cts CLI"},
 {"name": "Project_snapshooter", "kind": "bridge",
  "module": "project_snapshooter", "entry": "interactive",
  "entry_kwargs": [],
  "reexport": [
   "FORMAT_VERSION", "build_tree", "build_tui_tree", "compare", "interactive",
   "load", "load_preset", "read_values", "restore", "restore_preset",
   "save", "save_preset", "snapshooter", "take",
  ],
  "summary": "PLC variable presets (interactive wizard and library)"},
]

ENTRYPOINTS_BY_NAME = dict((spec["name"], spec) for spec in ENTRYPOINTS)

# Globals the CODESYS ScriptEngine injects into the executed script.
_HOST_GLOBALS = ("system", "projects")


def body_is_valid(body_dir):
 """True when body_dir looks like a cds-text-sync tree."""
 if not body_dir:
  return False
 return (
  os.path.isdir(os.path.join(body_dir, "src", "ide_bridge"))
  and os.path.isfile(os.path.join(body_dir, "cds_bootstrap.py"))
 )


def resolve_body(script_file=None):
 """Body root for an entry script.

 Flat layout: script_file lives in the body, so its own directory wins.
 Split layout: the stub passes a script_file pinned into the body.
 The upward walk is a safety net for a stub with a stale CDS_HOME that
 happens to sit inside a tree anyway; it mirrors codesys_runtime._get_root_dir.
 """
 start = _script_dir(script_file)
 current = start
 while True:
  if body_is_valid(current):
   return current
  parent = os.path.dirname(current)
  if not parent or parent == current:
   break
  current = parent
 return start


def _host_global(name, caller_globals):
 if caller_globals and name in caller_globals:
  return caller_globals[name]
 main_module = sys.modules.get("__main__")
 return getattr(main_module, name, None)


def _inject_host_globals(module, caller_globals):
 """Mirror what codesys_runtime.run_operation does for operation modules."""
 for name in _HOST_GLOBALS:
  value = _host_global(name, caller_globals)
  if value is not None:
   setattr(module, name, value)


def _load_bridge_module(module_name, script_file, caller_globals):
 module = import_runtime_module(module_name, script_file=script_file)
 if module is None:
  raise RuntimeError("Bridge module not found: " + module_name + ".py")
 _inject_host_globals(module, caller_globals)
 return module


def _call_entry(func, entry_kwargs, params, caller_globals):
 kwargs = {}
 for key in entry_kwargs or []:
  if key == "params":
   kwargs["params"] = params
  elif key == "caller_globals":
   kwargs["caller_globals"] = caller_globals
 return func(**kwargs)


def launch(name, script_file=None, caller_globals=None):
 """Return a callable f(params=None) for the named entrypoint.

 Used by both the root scripts in the body and the generated ScriptDir stubs.
 The only difference between the two is which script_file they pass.
 """
 spec = ENTRYPOINTS_BY_NAME.get(name)
 if spec is None:
  raise KeyError("Unknown cds-text-sync entrypoint: " + str(name))

 body = resolve_body(script_file)
 if not body_is_valid(body):
  raise RuntimeError(
   "cds-text-sync installation not found at: " + str(body)
   + "\nThe menu scripts point at a folder that no longer holds the tool."
   + "\nRe-run: cts install-menu"
  )

 anchor = os.path.join(body, name + ".py")
 kind = spec.get("kind")

 if kind == "command":
  command = spec["command"]

  def _entry(params=None):
   return run_project_command(
    command,
    params=params,
    script_file=anchor,
    caller_globals=caller_globals,
   )

 elif kind == "bridge":
  module_name = spec["module"]
  entry_name = spec.get("entry", "main")
  entry_kwargs = spec.get("entry_kwargs", [])

  def _entry(params=None):
   module = _load_bridge_module(module_name, anchor, caller_globals)
   func = getattr(module, entry_name, None)
   if func is None:
    raise RuntimeError(
     "Entry '" + entry_name + "' not found in " + module_name + ".py"
    )
   return _call_entry(func, entry_kwargs, params, caller_globals)

 else:
  raise RuntimeError("Unknown entrypoint kind: " + str(kind))

 reexport = spec.get("reexport")
 if reexport and caller_globals is not None:
  module = _load_bridge_module(spec["module"], anchor, caller_globals)
  for attr in reexport:
   if hasattr(module, attr):
    caller_globals[attr] = getattr(module, attr)

 return _entry
