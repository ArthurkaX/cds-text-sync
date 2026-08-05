# -*- coding: utf-8 -*-
"""
test_daemon_name_resolution.py — Static name-resolution guard for CODESYS daemon modules.

Protects against missing-import NameErrors in IronPython 2.7 daemon modules when
running under CPython 3.12. Stubs out all CODESYS/.NET-only dependencies so the
imports succeed, then walks every function's bytecode to find LOAD_GLOBAL references
to names that are not in the module's globals or builtins.

Modules guarded:
 - ide_reverse_pipe_loop.py (MUST import — failure is a test failure)
 - ide_daemon_state.py (MUST import — failure is a test failure)
 - all other ide_*.py under src/ide_bridge/ (skipped on import error)
 - ide_daemon_ui* modules are always xfail/skipped (WinForms — no CPython support)
 - all other *.py modules under src/ide_bridge/ (codesys_* and
   project_snapshooter, formerly .pyw; skipped on import error — expected)
"""

from __future__ import annotations

import builtins
import dis
import importlib
import importlib.util
import inspect
import sys
import types
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Locate ide_bridge directory and project root
# ---------------------------------------------------------------------------

_IDE_BRIDGE = Path(__file__).parent.parent.parent / "src" / "ide_bridge"
assert _IDE_BRIDGE.is_dir(), f"ide_bridge not found at {_IDE_BRIDGE}"

_PROJECT_ROOT = Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# Auto-stub infrastructure
# ---------------------------------------------------------------------------


class _AutoStub:
    """A module-like, callable no-op that returns itself for any attribute access."""

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name: str) -> "_AutoStub":
        return _STUB_SINGLETON

    def __iter__(self):
        return iter([])

    def __repr__(self):
        return "<AutoStub>"

    # Support 'from System.Windows.Forms import Form, ...' style:
    # importlib's 'from X import Y' resolves Y on the module's __dict__,
    # so __getattr__ covers it.


_STUB_SINGLETON = _AutoStub()


def _make_stub_module(name: str) -> ModuleType:
    """Return a ModuleType whose attribute access returns _STUB_SINGLETON."""
    mod = ModuleType(name)
    mod.__spec__ = None  # type: ignore[attr-defined]

    def _getattr(attr):
        return _STUB_SINGLETON

    mod.__getattr__ = _getattr  # type: ignore[attr-defined]
    return mod


def _install_stubs() -> dict[str, ModuleType]:
    """Install clr and common .NET namespace stubs into sys.modules.

    Returns the previous values so they can be restored after import.
    """
    STUB_NAMES = [
        "clr",
        "System",
        "System.IO",
        "System.IO.Pipes",
        "System.Threading",
        "System.Windows",
        "System.Windows.Forms",
        "System.Drawing",
        "System.Collections",
        "System.Collections.Generic",
        "System.Array",
        "System.Byte",
        # CODESYS scripting engine — injected by the host in real runs;
        # stub it so bridge modules that do `import scriptengine` or
        # `from scriptengine import ...` can be imported under CPython.
        "scriptengine",
    ]

    saved: dict[str, ModuleType] = {}
    for name in STUB_NAMES:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = _make_stub_module(name)

    return saved


def _restore_stubs(saved: dict[str, ModuleType]) -> None:
    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


# ---------------------------------------------------------------------------
# Module discovery
# ---------------------------------------------------------------------------

MUST_IMPORT = {"ide_reverse_pipe_loop", "ide_daemon_state"}
UI_MODULES = {"ide_daemon_ui"}


# ---------------------------------------------------------------------------
# Discovery: all *.py modules in src/ide_bridge/
#
# ide_*.py are the daemon modules; the codesys_*/project_snapshooter bridges
# used to ship as .pyw and were discovered by a second glob. After the
# .pyw -> .py rename a single glob covers everything. discover_report.py stays
# out: it is pure logic with its own dedicated test suite.
# ---------------------------------------------------------------------------

_EXCLUDED_STEMS = frozenset({"discover_report"})

_all_modules: list[str] = [
    _p.stem
    for _p in sorted(_IDE_BRIDGE.glob("*.py"))
    if _p.stem not in _EXCLUDED_STEMS
]

# ---------------------------------------------------------------------------
# Parametrization: (stem, filepath_or_None)
# filepath is always None — the path is resolved inside the test body from
# _IDE_BRIDGE / stem + ".py". (Kept as a tuple for signature stability.)
# ---------------------------------------------------------------------------

_ALL_CASES: list[tuple[str, Path | None]] = [(stem, None) for stem in _all_modules]


# ---------------------------------------------------------------------------
# Name-resolution analysis helpers
# ---------------------------------------------------------------------------


def _collect_global_names(code_obj) -> set[str]:
    """Recursively collect all LOAD/STORE/DELETE_GLOBAL argval names from a code object.

    Uses dis.get_instructions() at each level and recurses manually into
    nested code objects found in co_consts.
    """
    GLOBAL_OPS = frozenset({"LOAD_GLOBAL", "STORE_GLOBAL", "DELETE_GLOBAL"})
    names: set[str] = set()

    def _visit(co):
        for instr in dis.get_instructions(co):
            if instr.opname in GLOBAL_OPS:
                argval = instr.argval
                # CPython 3.11+ LOAD_GLOBAL has a (push_null, name) tuple argval form;
                # dis normalises it to the name string in .argval, but guard anyway.
                if isinstance(argval, tuple):
                    # (NULL_flag, name) — take the string element
                    for part in argval:
                        if isinstance(part, str):
                            argval = part
                            break
                if isinstance(argval, str):
                    names.add(argval)
        # Recurse into nested code objects (lambdas, comprehensions, nested defs)
        for const in co.co_consts:
            if isinstance(const, type(co)):  # type: ignore[arg-type]
                _visit(const)

    _visit(code_obj)
    return names


def _functions_in_module(module: ModuleType):
    """Yield (qualified_name, code_object) for every function/method in module."""
    mod_name = module.__name__

    def _yield_from(func, qualname: str):
        try:
            code = func.__code__
        except AttributeError:
            return
        yield qualname, code

    seen_ids: set[int] = set()

    for attr_name, obj in vars(module).items():
        if isinstance(obj, types.FunctionType) and obj.__module__ == mod_name:
            if id(obj) not in seen_ids:
                seen_ids.add(id(obj))
                yield from _yield_from(obj, attr_name)
        elif isinstance(obj, type):
            for method_name, method in inspect.getmembers(obj, predicate=inspect.isfunction):
                if id(method) not in seen_ids:
                    seen_ids.add(id(method))
                    qname = f"{attr_name}.{method_name}"
                    yield from _yield_from(method, qname)


# ---------------------------------------------------------------------------
# Names that are always available at daemon runtime or are intentionally
# probed with try/except guarding.
# ---------------------------------------------------------------------------

# CODESYS runtime globals injected into the exec'd script context:
_CODESYS_INJECTED = frozenset({"projects", "system", "__main__"})

# Python 2 builtins that exist in IronPython 2.7 but not CPython 3.
# Daemon code uses the canonical try/except NameError guard pattern, e.g.:
# try:
#     string_types = (basestring,) # IronPython 2
# except NameError:
#     string_types = (str,) # CPython 3
# The NameError IS the intended fallback — these are not missing imports.
_IRONPYTHON2_BUILTINS = frozenset({
    "basestring", "unicode", "xrange", "long", "execfile",
    "raw_input", "reduce", "reload", "StandardError",
})


# Optional CODESYS API objects that modules probe for via try/except Exception,
# e.g. `try: PouType; except Exception: pass` in _find_pou_type_enum.
# Missing these at runtime is intentional and handled by the caller.
_CODESYS_OPTIONAL_PROBES = frozenset({"PouType", "ScriptEngine"})

_ALL_ALLOWED_GLOBALS = (
    _CODESYS_INJECTED | _IRONPYTHON2_BUILTINS | _CODESYS_OPTIONAL_PROBES
)

# ---------------------------------------------------------------------------
# Parametrize: one test case per module
# ---------------------------------------------------------------------------


def _make_test_ids():
    return [stem for stem, _ in _ALL_CASES]


@pytest.mark.parametrize("module_stem,module_filepath", _ALL_CASES, ids=_make_test_ids())
def test_daemon_name_resolution(module_stem: str, module_filepath: "Path | None", tmp_path):
    """Import one daemon module with .NET stubs and verify no unresolved global names."""

    # --- UI modules: always skip under CPython ---
    if module_stem in UI_MODULES:
        pytest.skip(f"{module_stem}: WinForms-only, not importable under CPython")

    # --- Determine the actual file path ---
    if module_filepath is None:
        # Legacy ide_*.py: always in src/ide_bridge/
        actual_path = _IDE_BRIDGE / f"{module_stem}.py"
    else:
        actual_path = module_filepath

    # --- Prepare sys.path so intra-package imports resolve ---
# Insert src/ide_bridge at the front so that bridge modules that import
# each other can resolve those imports.
    paths_to_insert: list[str] = []
    bridge_str = str(_IDE_BRIDGE)

    if bridge_str not in sys.path:
        sys.path.insert(0, bridge_str)
        paths_to_insert.append(bridge_str)

    # Ensure sys._codesys_daemon_loop exists before importing
    had_loop = hasattr(sys, "_codesys_daemon_loop")
    if not had_loop:
        sys._codesys_daemon_loop = {}  # type: ignore[attr-defined]

    saved_stubs = _install_stubs()

    # Remove previously-cached module entry so we get a fresh import
    _evict_key = module_stem
    evicted = sys.modules.pop(_evict_key, None)

    module = None
    try:
        # Build a spec from the file path so we control the import cleanly
        spec = importlib.util.spec_from_file_location(module_stem, str(actual_path))
        assert spec is not None and spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_stem] = module

        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:
            # Restore stubs before deciding what to do
            _restore_stubs(saved_stubs)
            if module_stem in MUST_IMPORT:
                pytest.fail(
                    f"{module_stem} MUST import cleanly but raised {type(exc).__name__}: {exc}"
                )
            else:
                pytest.skip(
                    f"{module_stem}: import failed under CPython ({type(exc).__name__}: {exc})"
                )
            return  # unreachable, keeps type checker happy

        _restore_stubs(saved_stubs)

    except Exception:
        _restore_stubs(saved_stubs)
        raise
    finally:
        # Remove our stub entry; put back the previously cached one if any
        if evicted is not None:
            sys.modules[module_stem] = evicted
        else:
            sys.modules.pop(module_stem, None)
        # Remove any paths we inserted
        for p in paths_to_insert:
            try:
                sys.path.remove(p)
            except ValueError:
                pass
        if not had_loop:
            try:
                del sys._codesys_daemon_loop  # type: ignore[attr-defined]
            except AttributeError:
                pass

    if module is None:
        pytest.skip(f"{module_stem}: module not loaded")
        return

    # --- Collect module globals and builtins ---
    module_globals: set[str] = set(vars(module).keys())
    builtin_names: set[str] = set(dir(builtins))
    allowed: set[str] = module_globals | builtin_names | _ALL_ALLOWED_GLOBALS

    # --- Walk every function and detect missing names ---
    unresolved: list[str] = []

    for func_qualname, code_obj in _functions_in_module(module):
        global_refs = _collect_global_names(code_obj)
        for name in sorted(global_refs):
            if name not in allowed:
                unresolved.append(f"{module_stem}::{func_qualname} -> {name}")

    assert not unresolved, (
        f"Unresolved global name(s) in {module_stem}:\n"
        + "\n".join(f"  {item}" for item in unresolved)
    )
