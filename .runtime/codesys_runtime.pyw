# -*- coding: utf-8 -*-
"""
codesys_runtime.py - Shared loader, runtime, and UI adapters for CODESYS scripts.

This module separates interactive and headless execution so the same operation
modules can be used both from user-facing Project_*.py entrypoints and from the
dev automation bridge.
"""
from __future__ import print_function
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


CORE_MODULES = [
    "codesys_constants",
    "codesys_utils",
    "codesys_managers",
    "codesys_ui",
    "codesys_compare_engine"
]

OPERATION_MODULES = {
    "export": "codesys_export_operation",
    "import": "codesys_import_operation",
    "compare": "codesys_compare_operation",
    "build": "codesys_build_operation"
}

OPTIONAL_MODULES = {
    "compare": ["codesys_ui_diff"]
}


def safe_text(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return "<unprintable>"


def make_json_safe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[safe_text(key)] = make_json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    return safe_text(value)


def _get_root_dir(script_file=None):
    path = os.path.abspath(script_file or __file__)
    script_dir = os.path.dirname(path)
    current = script_dir
    while True:
        if os.path.isdir(os.path.join(current, ".runtime")):
            return current
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    if os.path.basename(script_dir).lower() in [".dev_tools", ".runtime"]:
        return os.path.dirname(script_dir)
    return script_dir


def _ensure_sys_path(root_dir):
    runtime_dir = os.path.join(root_dir, ".runtime")
    for path in (runtime_dir, root_dir):
        if path and path not in sys.path:
            sys.path.insert(0, path)


def _load_python_module(name, path):
    if not os.path.exists(path):
        return None

    if _HAS_IMPORTLIB_UTIL:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod

    if _HAS_IMP:
        mod = imp.load_source(name, path)
        sys.modules[name] = mod
        return mod

    return None


def load_hidden_module(name, script_file=None):
    root_dir = _get_root_dir(script_file)
    _ensure_sys_path(root_dir)
    runtime_path = os.path.join(root_dir, ".runtime", name + ".pyw")
    root_path = os.path.join(root_dir, name + ".pyw")
    return _load_python_module(name, runtime_path) or _load_python_module(name, root_path)


def load_script_module(name, script_file=None):
    root_dir = _get_root_dir(script_file)
    _ensure_sys_path(root_dir)
    runtime_path = os.path.join(root_dir, ".runtime", name + ".py")
    root_path = os.path.join(root_dir, name + ".py")
    return _load_python_module(name, runtime_path) or _load_python_module(name, root_path)


def clear_hidden_modules(exclude=None):
    excluded = set(exclude or [])
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("codesys_") and mod_name not in excluded:
            del sys.modules[mod_name]


def ensure_modules(module_names, script_file=None, clear=False):
    if clear:
        clear_hidden_modules(exclude=["codesys_runtime"])

    loaded = {}
    for name in module_names:
        loaded[name] = load_hidden_module(name, script_file)
    return loaded


def load_operation_module(command, script_file=None, clear=False):
    module_names = list(CORE_MODULES)
    module_names.extend(OPTIONAL_MODULES.get(command, []))
    module_name = OPERATION_MODULES.get(command)
    if module_name:
        module_names.append(module_name)
    loaded = ensure_modules(module_names, script_file=script_file, clear=clear)
    return loaded.get(module_name)


def _build_compare_selection(different, new_in_ide, new_on_disk, moved=None):
    selected = []
    if different:
        selected.extend(different)
    if new_in_ide:
        selected.extend(new_in_ide)
    if new_on_disk:
        for item in new_on_disk:
            selected.append({
                "name": item.get("name"),
                "path": item.get("path"),
                "file_path": item.get("file_path"),
                "type": "new",
                "type_guid": "",
                "obj": None
            })
    if moved:
        selected.extend(moved)
    return selected


class ExecutionRuntime(object):
    def __init__(self, system_obj=None, projects_obj=None, ui=None,
                 mode="interactive", params=None, caller_globals=None):
        self.system = system_obj
        self.projects = projects_obj
        self.ui = ui
        self.mode = mode
        self.params = params or {}
        self.caller_globals = caller_globals or {}

    @property
    def is_headless(self):
        return self.mode != "interactive"


class InteractiveUIAdapter(object):
    def __init__(self, system_obj=None, ui_module=None):
        self.system = system_obj
        self.ui_module = ui_module

    def _system_ui(self):
        try:
            return self.system.ui
        except Exception:
            return None

    def info(self, message):
        sys_ui = self._system_ui()
        if sys_ui and hasattr(sys_ui, "info"):
            return sys_ui.info(message)
        print("[IDE INFO] " + safe_text(message))

    def warning(self, message):
        sys_ui = self._system_ui()
        if sys_ui and hasattr(sys_ui, "warning"):
            return sys_ui.warning(message)
        print("[IDE WARNING] " + safe_text(message))

    def error(self, message):
        sys_ui = self._system_ui()
        if sys_ui and hasattr(sys_ui, "error"):
            return sys_ui.error(message)
        print("[IDE ERROR] " + safe_text(message))

    def choose(self, title, options):
        sys_ui = self._system_ui()
        if sys_ui and hasattr(sys_ui, "choose"):
            return sys_ui.choose(title, options)
        return 0

    def prompt(self, message, choice=None, default=None):
        sys_ui = self._system_ui()
        if sys_ui and hasattr(sys_ui, "prompt"):
            try:
                return sys_ui.prompt(message, choice, default)
            except TypeError:
                return sys_ui.prompt(message)
        return default

    def ask_yes_no(self, title, message):
        if self.ui_module and hasattr(self.ui_module, "ask_yes_no"):
            return self.ui_module.ask_yes_no(title, message)
        return False

    def ask_yes_no_cancel(self, title, message):
        if self.ui_module and hasattr(self.ui_module, "ask_yes_no_cancel"):
            return self.ui_module.ask_yes_no_cancel(title, message)
        return "cancel"

    def show_settings_dialog(self, current_settings, version=None):
        if self.ui_module and hasattr(self.ui_module, "show_settings_dialog"):
            return self.ui_module.show_settings_dialog(current_settings, version)
        return None

    def show_compare_dialog(self, different, new_in_ide, new_on_disk, unchanged_count, moved=None):
        if self.ui_module and hasattr(self.ui_module, "show_compare_dialog"):
            action, selected = self.ui_module.show_compare_dialog(
                different, new_in_ide, new_on_disk, unchanged_count, moved
            )
            return {
                "action": action,
                "selected": selected
            }
        return {
            "action": "close",
            "selected": []
        }


class HeadlessUIAdapter(object):
    def __init__(self, params=None):
        self.params = params or {}

    def info(self, message):
        print("[IDE INFO] " + safe_text(message))

    def warning(self, message):
        print("[IDE WARNING] " + safe_text(message))

    def error(self, message):
        print("[IDE ERROR] " + safe_text(message))

    def choose(self, title, options):
        index = self.params.get("choose_index", 0)
        print("[HEADLESS CHOOSE] %s -> %s" % (safe_text(title), safe_text(index)))
        return index

    def prompt(self, message, choice=None, default=None):
        print("[HEADLESS PROMPT] " + safe_text(message))
        return default

    def ask_yes_no(self, title, message):
        result = bool(self.params.get("confirm", True))
        print("[HEADLESS YES/NO] %s -> %s" % (safe_text(title), safe_text(result)))
        return result

    def ask_yes_no_cancel(self, title, message):
        result = safe_text(self.params.get("choice", "yes")).lower() or "yes"
        if result not in ("yes", "no", "cancel"):
            result = "yes"
        print("[HEADLESS YES/NO/CANCEL] %s -> %s" % (safe_text(title), result))
        return result

    def show_settings_dialog(self, current_settings, version=None):
        print("[HEADLESS SETTINGS] returning current settings")
        return current_settings

    def show_compare_dialog(self, different, new_in_ide, new_on_disk, unchanged_count, moved=None):
        action = safe_text(self.params.get("compare_action", "report")).lower() or "report"
        if action not in ("import", "export"):
            action = "report"
        print("[HEADLESS COMPARE] action=%s" % action)
        return {
            "action": action,
            "selected": _build_compare_selection(different, new_in_ide, new_on_disk, moved)
        }


def resolve_runtime(runtime=None, caller_globals=None, params=None, headless=False,
                    system_obj=None, projects_obj=None):
    if runtime is not None:
        if params is not None:
            runtime.params = params
        if caller_globals is not None:
            runtime.caller_globals = caller_globals
        return runtime

    utils_mod = sys.modules.get("codesys_utils")
    ui_module = sys.modules.get("codesys_ui")

    if system_obj is None and utils_mod and hasattr(utils_mod, "resolve_system"):
        system_obj = utils_mod.resolve_system(caller_globals)

    if projects_obj is None and utils_mod and hasattr(utils_mod, "resolve_projects"):
        projects_obj = utils_mod.resolve_projects(None, caller_globals)

    if headless:
        ui_adapter = HeadlessUIAdapter(params)
        mode = "headless"
    else:
        ui_adapter = InteractiveUIAdapter(system_obj, ui_module)
        mode = "interactive"

    return ExecutionRuntime(
        system_obj=system_obj,
        projects_obj=projects_obj,
        ui=ui_adapter,
        mode=mode,
        params=params or {},
        caller_globals=caller_globals
    )


def create_headless_runtime(system_obj=None, projects_obj=None, params=None, caller_globals=None):
    return resolve_runtime(
        runtime=None,
        caller_globals=caller_globals,
        params=params,
        headless=True,
        system_obj=system_obj,
        projects_obj=projects_obj
    )


def run_operation(command, params=None, runtime=None, caller_globals=None, script_file=None):
    operation_module = load_operation_module(command, script_file=script_file, clear=True)
    if not operation_module:
        raise RuntimeError("Operation module not found for command: " + safe_text(command))

    runtime = resolve_runtime(
        runtime=runtime,
        caller_globals=caller_globals,
        params=params or {},
        headless=bool(runtime and runtime.is_headless)
    )

    operation_module.system = runtime.system
    operation_module.projects = runtime.projects
    return operation_module.main(params=params or {}, runtime=runtime)


def run_project_command(command, caller_globals=None, params=None, script_file=None):
    return run_operation(
        command,
        params=params or {},
        runtime=None,
        caller_globals=caller_globals,
        script_file=script_file
    )
