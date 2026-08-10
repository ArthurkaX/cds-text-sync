# -*- coding: utf-8 -*-
"""
codesys_runtime.py - Shared loader, runtime, and UI adapters for CODESYS scripts.

This module separates interactive and headless execution so the same operation
modules can be used both from user-facing entrypoints and from the dev
automation bridge.
"""
from __future__ import print_function
import os
import sys

CORE_MODULES = [
    "codesys_utils",
    "codesys_ui"
]

OPERATION_MODULES = {
    "export": "codesys_extractor_operation",
    "import": "codesys_injector_operation",
    "extract": "codesys_extractor_operation",
    "inject": "codesys_injector_operation",
    "compare_ui": "codesys_compare_ui_operation",
    "options": "codesys_options_operation",
    "build": "codesys_build_operation",
    "directory": "codesys_directory_operation",
    "discover": "codesys_discover_operation",
    "resources": "codesys_resources_operation",
    "fmt": "codesys_fmt_operation"
}

OPTIONAL_MODULES = {
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


def _normalize_params(params):
    if params is None:
        return {}
    if isinstance(params, dict):
        return params
    try:
        if isinstance(params, str):
            text = params.strip()
            if not text:
                return {}
            if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
                import json
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            return {"dump_root": text}
    except Exception:
        pass
    return {"dump_root": safe_text(params)}


def _get_root_dir(script_file=None):
    path = os.path.abspath(script_file or __file__)
    script_dir = os.path.dirname(path)
    # Fast path: if this file lives inside src/ide_bridge, root is two levels up
    if os.path.basename(script_dir).lower() == "ide_bridge":
        parent = os.path.dirname(script_dir)
        if os.path.basename(parent).lower() == "src":
            return os.path.dirname(parent)
    # Walk up looking for src/ide_bridge as the new stable sentinel
    current = script_dir
    while True:
        if os.path.isdir(os.path.join(current, "src", "ide_bridge")):
            return current
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    # Legacy fallbacks
    if os.path.basename(script_dir).lower() == ".dev_tools":
        return os.path.dirname(script_dir)
    return script_dir


def _ensure_sys_path(root_dir):
    ide_bridge_dir = os.path.join(root_dir, "src", "ide_bridge")
    engine_dir = _find_engine_dir(root_dir)
    old_engine_dir = os.path.join(root_dir, "src", "external_engine")
    # Inserted at 0 in turn, so this tuple is walked back-to-front: the
    # resulting order is ide_bridge, engine, old_engine, root. The bridge must
    # outrank the root because modules are imported by name now, and the root
    # holds Project_snapshooter.py next to the bridge's project_snapshooter.py
    # -- names that collide on a case-insensitive filesystem.
    for path in (root_dir, old_engine_dir, engine_dir, ide_bridge_dir):
        if path and path not in sys.path:
            sys.path.insert(0, path)


def _find_engine_dir(root_dir):
    """Find the CPython engine from a host product checkout or installation."""
    current = os.path.abspath(root_dir)
    while True:
        candidate = os.path.join(
            current, "products", "cds-text-sync", "src", "cds_text_sync", "engine"
        )
        if os.path.isdir(candidate):
            return candidate
        legacy = os.path.join(current, "src", "external_engine")
        if os.path.isdir(legacy):
            return legacy
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return os.path.join(
        root_dir, "products", "cds-text-sync", "src", "cds_text_sync", "engine"
    )


def _module_file_exists(root_dir, name):
    for candidate in (
        os.path.join(root_dir, "src", "ide_bridge", name + ".py"),
        os.path.join(root_dir, name + ".py"),
    ):
        if os.path.isfile(candidate):
            return True
    return False


def load_hidden_module(name, script_file=None):
    root_dir = _get_root_dir(script_file)
    _ensure_sys_path(root_dir)
    try:
        __import__(name)
    except ImportError:
        # A module that is simply absent is a normal outcome - callers probe
        # for optional modules and handle None. A module whose file is right
        # there but fails to import is a defect, and swallowing it turns
        # "broken" into "missing": the caller then degrades silently, which is
        # how a resolve_runtime with no system object reaches the user as a
        # command that quietly does nothing.
        if _module_file_exists(root_dir, name):
            raise
        return None
    return sys.modules.get(name)


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

    def show_project_options_dialog(self, current_settings):
        if self.ui_module and hasattr(self.ui_module, "show_project_options_dialog"):
            return self.ui_module.show_project_options_dialog(current_settings)
        return None

    def confirm_overwrite_dirty(self, report):
        """Ask the user how to handle local changes before export.

        Returns a dict {overwrite_dirty, remove_orphans} to proceed, None to
        cancel the export, or None when no dialog is available (caller falls
        back to the safe skip mode).
        """
        if self.ui_module and hasattr(self.ui_module, "show_overwrite_confirm_dialog"):
            report = report or {}
            dirty_paths = [item.get("path") for item in report.get("dirty") or []]
            orphan_paths = [item.get("path") for item in report.get("orphans") or []]
            return self.ui_module.show_overwrite_confirm_dialog(
                dirty_paths, orphan_paths
            )
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

    def show_project_options_dialog(self, current_settings):
        print("[HEADLESS PROJECT OPTIONS] returning current settings")
        return current_settings

    def confirm_overwrite_dirty(self, report):
        decision = {
            "overwrite_dirty": bool(self.params.get("overwrite_dirty", False)),
            "remove_orphans": bool(self.params.get("remove_orphans", False)),
        }
        print("[HEADLESS OVERWRITE-DIRTY] -> %s" % decision)
        return decision

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
    params = _normalize_params(params)
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


def _ensure_bridge_path(root_dir):
    bridge_dir = os.path.join(root_dir, "src", "ide_bridge")
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)
    return bridge_dir


def run_bridge_operation(params, runtime, caller_globals, operation_name, invoke_bridge, failure_message):
    from codesys_utils import load_base_dir, init_logging, resolve_projects

    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=caller_globals, params=params)

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}

    init_logging(base_dir)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)

    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    _ensure_bridge_path(_get_root_dir())

    try:
        success = invoke_bridge(
            runtime.system,
            projects_obj.primary,
            base_dir,
            params.get("view_root"),
            params.get("layout"),
        )
        if success:
            return {"status": "success"}
        runtime.ui.error(failure_message)
        return {"status": "error"}
    except Exception as error:
        message = "Error invoking " + operation_name + " bridge: " + safe_text(error)
        runtime.ui.error(message)
        return {"status": "error", "error": safe_text(error)}


def run_operation(command, params=None, runtime=None, caller_globals=None, script_file=None):
    params = _normalize_params(params)
    ensure_modules(CORE_MODULES, script_file=script_file, clear=True)

    operation_module = load_operation_module(command, script_file=script_file, clear=False)
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

    if command in ("export", "import"):
        try:
            utils_mod = sys.modules.get("codesys_utils")
            if utils_mod and hasattr(utils_mod, "set_info_logging"):
                verbose_key = command + "_verbose"
                verbose = bool((params or {}).get(verbose_key, False) or (params or {}).get("verbose", False))
                utils_mod.set_info_logging(verbose)
                if hasattr(utils_mod, "set_console_silence"):
                    utils_mod.set_console_silence(not verbose)
        except Exception:
            pass

    return operation_module.main(params=params or {}, runtime=runtime)


def run_project_command(command, caller_globals=None, params=None, script_file=None):
    return run_operation(
        command,
        params=params,
        runtime=None,
        caller_globals=caller_globals,
        script_file=script_file
    )
