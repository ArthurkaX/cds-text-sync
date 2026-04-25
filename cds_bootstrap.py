# -*- coding: utf-8 -*-
"""
Shared bootstrap helpers for root-level CODESYS scripts.

This keeps the public script layer thin while preserving compatibility with
embedded runtimes that may only support `imp`.
"""
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


def _module_path(name, script_file=None, extension=".pyw"):
    script_dir = _script_dir(script_file)
    runtime_path = os.path.join(script_dir, ".runtime", name + extension)
    if os.path.exists(runtime_path):
        return runtime_path
    root_path = os.path.join(script_dir, name + extension)
    if os.path.exists(root_path):
        return root_path
    return None


def load_module(name, script_file=None, extension=".pyw", force=False):
    if force and name in sys.modules:
        del sys.modules[name]

    if not force and name in sys.modules:
        return sys.modules[name]

    path = _module_path(name, script_file=script_file, extension=extension)
    if not path:
        return None

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

    return None


def load_hidden_module(name, script_file=None, force=False):
    return load_module(name, script_file=script_file, extension=".pyw", force=force)


def clear_hidden_modules(prefix="codesys_"):
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(prefix):
            del sys.modules[mod_name]


def load_hidden_modules(module_names, script_file=None, clear=False):
    if clear:
        clear_hidden_modules()

    loaded = {}
    for name in module_names:
        loaded[name] = load_hidden_module(name, script_file=script_file)
    return loaded


def run_project_command(command, params=None, script_file=None, caller_globals=None):
    runtime_module = load_hidden_module("codesys_runtime", script_file=script_file)
    if not runtime_module:
        raise RuntimeError("codesys_runtime.pyw not found.")
    return runtime_module.run_project_command(
        command,
        caller_globals=caller_globals,
        params=params,
        script_file=script_file,
    )
