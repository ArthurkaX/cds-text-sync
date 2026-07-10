# -*- coding: utf-8 -*-
"""Shared bootstrap helpers for root-level CODESYS scripts."""
import os
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

def _script_dir(script_file=None):
 return os.path.dirname(os.path.abspath(script_file or __file__))


def ensure_runtime_path(script_file=None):
 script_dir = _script_dir(script_file)
 ide_bridge_dir = os.path.join(script_dir, "src", "ide_bridge")
 if ide_bridge_dir not in sys.path:
  sys.path.insert(0, ide_bridge_dir)
 return ide_bridge_dir


def import_runtime_module(name, script_file=None, force=False):
 ensure_runtime_path(script_file)

 if force and name in sys.modules:
  del sys.modules[name]

 if not force and name in sys.modules:
  return sys.modules[name]

 script_dir = _script_dir(script_file)
 # Prefer src/ide_bridge, then repo root
 module_path = os.path.join(script_dir, "src", "ide_bridge", name + ".pyw")
 if not os.path.exists(module_path):
  module_path = os.path.join(script_dir, name + ".pyw")
  if not os.path.exists(module_path):
   return None

 if _HAS_IMPORTLIB_UTIL:
  spec = importlib.util.spec_from_file_location(name, module_path)
  if spec and spec.loader:
   module = importlib.util.module_from_spec(spec)
   sys.modules[name] = module
   spec.loader.exec_module(module)
   return module

 if _HAS_IMP:
  module = imp.load_source(name, module_path)
  sys.modules[name] = module
  return module

 return None


def preload_runtime_modules(module_names, script_file=None, force=False):
 ensure_runtime_path(script_file)
 loaded = {}
 for name in module_names:
  loaded[name] = import_runtime_module(name, script_file=script_file, force=force)
 return loaded


def run_project_command(command, params=None, script_file=None, caller_globals=None):
 runtime_module = import_runtime_module("codesys_runtime", script_file=script_file)
 if not runtime_module:
  raise RuntimeError("codesys_runtime.pyw not found.")
 return runtime_module.run_project_command(
  command,
  caller_globals=caller_globals,
  params=params,
  script_file=script_file,
 )
