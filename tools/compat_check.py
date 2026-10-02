# -*- coding: utf-8 -*-
"""IronPython 2.7 compatibility lint for modules the CODESYS host imports.

Everything under the host's ``src/ide_bridge/`` runs inside the CODESYS
ScriptEngine, whose interpreter is IronPython 2.7: the ``Project_*.py``
entrypoints, the FMT workflow, and the reverse-pipe daemon.  The repo-local
modules they import (``cts_shared.*``, the shared ``cds_text_sync.engine``
helpers, the rest of the bridge) must therefore stay Python-2-compatible even
though the unit tests run under CPython 3.  This tool statically checks them
for Python 3-only syntax, builtin calls and source that IronPython 2.7 cannot
even parse.

The checked set is *computed*, not hand-listed: it seeds with every module the
host loads and follows their repo-local imports to a fixed point.  The old
hand-maintained list drifted -- the encoding defect in ``cts_shared/coerce.py``
slipped through it and only surfaced on the CODESYS VM as a SyntaxError dialog
-- so a new module is now gated by being dropped into ``ide_bridge/`` or
imported from it, with no edit here.

Usage::

    python tools/compat_check.py            # lint the discovered host set
    python tools/compat_check.py <paths...> # lint explicit files
    python tools/compat_check.py --ci       # exit 1 on any finding

It is deliberately dependency-free (stdlib ``ast`` only) so the same command
can run on a developer machine and in CI.
"""

from __future__ import print_function

import ast
import os
import re
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Where the host tree lives ──────────────────────────────────────────────

HOST_ROOT = os.path.join(ROOT, "products", "codesys-host")
IDE_BRIDGE_DIR = os.path.join(HOST_ROOT, "src", "ide_bridge")
ENGINE_DIR = os.path.join(
    ROOT, "products", "cds-text-sync", "src", "cds_text_sync", "engine"
)
PRODUCT_SRC_DIR = os.path.join(ROOT, "products", "cds-text-sync", "src")
SHARED_SRC_DIR = os.path.join(ROOT, "shared", "src")

# Where an import name is looked up.  Order matters only for a name that is
# shadowed; the bridge comes first because its modules are imported by name
# and its directory outranks the host root on the CODESYS sys.path.  The
# engine directory is on the host's sys.path at runtime (ide_runtime_common
# adds it), so its modules are imported by bare name, the same way the bridge
# imports them.
MODULE_SEARCH_ROOTS = (
    IDE_BRIDGE_DIR,
    ENGINE_DIR,
    SHARED_SRC_DIR,
    PRODUCT_SRC_DIR,
    HOST_ROOT,
)

# Entry points nothing imports, so the walk has to be seeded with them
# explicitly: the host's own Project_*.py stubs, the shared bootstrap they all
# go through, and the headless CRC script CODESYS runs by path
# (--runscript).  These are the only hand-listed members of the set.
EXPLICIT_ENTRYPOINTS = (
    os.path.join(HOST_ROOT, "cds_bootstrap.py"),
    os.path.join(HOST_ROOT, "headless", "plc_crc.py"),
)

# Files deliberately kept out of the gate, keyed by their repository-relative
# path, valued with the reason.  Empty today: every module the host reaches is
# meant to be IronPython-clean, and a fresh walk of ide_bridge/ reaches no
# CPython-only module behind a guarded import.  When that changes -- a
# try/except ImportError fallback that is genuinely CPython-only -- name the
# file here so the exclusion is visible and reviewed, instead of letting the
# walk lint code that never runs on the VM.
EXCLUDED_FILES = {}


# ── Discovering the default file set ───────────────────────────────────────


def _package_parts(path):
    """The dotted package owning *path*, as a list, or ``[]`` when top-level."""
    parts = []
    directory = os.path.dirname(path)
    while os.path.isfile(os.path.join(directory, "__init__.py")):
        parts.insert(0, os.path.basename(directory))
        directory = os.path.dirname(directory)
    return parts


def _module_names_imported(path):
    """Every module name *path* imports, relative imports made absolute.

    Best effort: a file that will not parse yields no names (it is still linted,
    and the lint reports the parse error), and a dynamic import such as
    ``__import__(name)`` cannot be seen.  The host only uses dynamic imports
    with a runtime-computed name, so nothing statically reachable is lost.
    """
    try:
        with open(path, "rb") as stream:
            source = stream.read()
    except (IOError, OSError):
        return []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    package = _package_parts(path)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    continue
                base = package[: len(package) - (node.level - 1)]
                if node.module:
                    names.append(".".join(base + [node.module]))
                else:
                    names.extend(".".join(base + [alias.name]) for alias in node.names)
            elif node.module:
                names.append(node.module)
                # ``from pkg import mod`` may name a submodule.
                names.extend(node.module + "." + alias.name for alias in node.names)
    return names


def _resolve_module(module_name, search_roots):
    """Return ``(module_file, package_init_files)`` for a repo module, or None.

    A dotted name executes the ``__init__.py`` of each package on the way, so
    those are part of the runtime set too.  Only the packages *inside* the
    search root count: a top-level module imported by bare name never runs the
    ``__init__.py`` of the directory that happens to contain it.
    """
    parts = module_name.split(".")
    for root in search_roots:
        module_file = os.path.join(root, *parts) + ".py"
        if not os.path.isfile(module_file):
            module_file = os.path.join(root, *parts, "__init__.py")
            if not os.path.isfile(module_file):
                continue
        inits = []
        for depth in range(1, len(parts)):
            init = os.path.join(root, *parts[:depth], "__init__.py")
            if os.path.isfile(init):
                inits.append(init)
        return module_file, inits
    return None


def _is_excluded(path, excluded):
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    return rel in excluded or os.path.normpath(path) in excluded


def _entrypoint_files(host_root=None):
    """The explicit seeds: host entrypoint stubs plus the by-path scripts."""
    host_root = HOST_ROOT if host_root is None else host_root
    if host_root == HOST_ROOT:
        entrypoints = list(EXPLICIT_ENTRYPOINTS)
    else:
        # A different root (tests on a temp tree) has no known by-path scripts.
        entrypoints = []
    try:
        names = sorted(os.listdir(host_root))
    except OSError:
        names = []
    entrypoints.extend(
        os.path.join(host_root, name)
        for name in names
        if name.startswith("Project_") and name.endswith(".py")
    )
    return entrypoints


def discover_default_files(
    bridge_dir=None, search_roots=None, entrypoints=None, excluded=None
):
    """The modules the CODESYS host runs, as absolute paths.

    Seeds with every ``*.py`` in the bridge directory and the explicit
    entrypoints, then follows repo-local imports until the set stops growing.
    """
    bridge_dir = IDE_BRIDGE_DIR if bridge_dir is None else bridge_dir
    roots = MODULE_SEARCH_ROOTS if search_roots is None else tuple(search_roots)
    if entrypoints is None:
        entrypoints = _entrypoint_files()
    if excluded is None:
        excluded = EXCLUDED_FILES

    seeds = []
    try:
        walk_names = sorted(os.listdir(bridge_dir))
    except OSError:
        walk_names = []
    seeds.extend(
        os.path.join(bridge_dir, name)
        for name in walk_names
        if name.endswith(".py")
    )
    seeds.extend(entrypoints)

    files = set()
    seen = set()
    queue = list(seeds)
    while queue:
        path = os.path.normpath(queue.pop(0))
        if path in seen or _is_excluded(path, excluded) or not os.path.isfile(path):
            continue
        seen.add(path)
        files.add(path)
        for module_name in _module_names_imported(path):
            resolved = _resolve_module(module_name, roots)
            if resolved is None:
                continue
            module_file, inits = resolved
            for candidate in inits + [module_file]:
                candidate = os.path.normpath(candidate)
                if candidate not in seen and not _is_excluded(candidate, excluded):
                    queue.append(candidate)
    return sorted(files)


def default_files():
    """``discover_default_files()`` as repository-relative POSIX paths."""
    return [
        os.path.relpath(path, ROOT).replace(os.sep, "/")
        for path in discover_default_files()
    ]


DEFAULT_FILES = default_files()

# PEP 263 coding cookie, e.g. ``# -*- coding: utf-8 -*-``.
_SOURCE_ENCODING_RE = re.compile(rb"coding[:=]\s*([-\w.]+)")


def _declares_source_encoding(source):
    """True when the file carries a PEP 263 coding cookie.

    Only the first two lines are searched: that is where Python 2 looks for
    it, and the cookie is ignored anywhere else.
    """
    for line in source.splitlines()[:2]:
        if _SOURCE_ENCODING_RE.search(line):
            return True
    return False


# Builtin calls whose keyword arguments are Python 3-only.  IronPython 2.7
# raises TypeError for the keyword form.
_KEYWORD_ONLY_BUILTINS = {
    "max": ("default",),
    "min": ("default",),
    "sum": ("start",),
    "open": ("encoding", "errors", "newline"),
    "print": ("file", "flush", "end", "sep"),
    "super": (),
}

# Stdlib modules absent from the Python 2.7 standard library that IronPython
# 2.7 mirrors.  An *unguarded* import of any of these raises ImportError when
# the module loads on the VM, killing the host command that reaches it.  The
# match is by dotted prefix, so listing "concurrent" also flags
# "concurrent.futures" and listing "importlib.resources" does not flag plain
# "importlib" (which 2.7 does have).  Backports (enum34, typing) exist but are
# not part of the interpreter, so they must not be assumed on a bare VM.
PY3_ONLY_MODULES = frozenset([
    "pathlib",
    "dataclasses",
    "typing",
    "enum",
    "asyncio",
    "concurrent",  # the whole package arrived in 3.2
    "contextvars",
    "secrets",
    "statistics",
    "importlib.resources",
])

# Py3-only attributes of modules that *do* exist in 2.7, keyed by dotted
# attribute path.  Every entry is verified missing from the Python 2.7 stdlib.
PY3_ONLY_ATTRIBUTES = {
    "subprocess.run": "Python 3.5+; use subprocess.call/check_output on 2.7",
    "os.scandir": "Python 3.5+; use os.listdir on 2.7",
    "shutil.which": "Python 3.3+; not in the 2.7 stdlib",
}

# Method names that only exist in Python 3, by bare name.  ``str.format_map``
# is the only one worth naming: a method of this name is not defined anywhere
# in the checked tree, so flagging the call has no false-positive surface.
PY3_ONLY_METHODS = {
    "format_map": "str.format_map is Python 3.2+",
}

# Calls whose keyword argument did not exist in 2.7: the interpreter accepts
# the name as a keyword and raises TypeError, so the file imports but the call
# fails at runtime.  Keyed by dotted attribute path.
PY3_ONLY_KEYWORDS = {
    "os.makedirs": ("exist_ok",),
}


def _catches_import_error(handlers):
    """True when an except clause would swallow an ImportError."""
    for handler in handlers:
        if handler.type is None:  # bare ``except:``
            return True
        names = []
        if isinstance(handler.type, ast.Name):
            names = [handler.type.id]
        elif isinstance(handler.type, ast.Tuple):
            names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
        if any(name in ("ImportError", "Exception", "BaseException") for name in names):
            return True
    return False


def _guarded_import_nodes(tree):
    """id()s of import nodes inside a ``try`` guarded against ImportError.

    The host uses this shape deliberately: ``try: import clr / except
    ImportError: clr = None`` keeps a module importable under CPython for the
    unit tests while it uses the .NET API on the VM.  Such an import cannot
    break the VM, so it is not linted.
    """
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not _catches_import_error(node.handlers):
            continue
        for statement in node.body:
            for inner in ast.walk(statement):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    guarded.add(id(inner))
    return guarded


def _py3_only_module(name):
    """The denylist entry *name* falls under, or None."""
    for denied in PY3_ONLY_MODULES:
        if name == denied or name.startswith(denied + "."):
            return denied
    return None


def _attribute_path(node):
    """``subprocess.run`` for a call like ``subprocess.run(...)``, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _import_findings(path, tree, errors):
    """Flag Python 3-only stdlib imports and calls the tree cannot run under 2.7."""
    guarded = _guarded_import_nodes(tree)
    label = os.path.basename(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if id(node) in guarded:
                continue
            for alias in node.names:
                denied = _py3_only_module(alias.name)
                if denied:
                    errors.append(
                        "{0}:{1}: imports Python 3-only module '{2}'".format(
                            label, node.lineno, denied
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            if id(node) in guarded or not node.module:
                continue
            denied = _py3_only_module(node.module)
            if denied:
                errors.append(
                    "{0}:{1}: imports Python 3-only module '{2}'".format(
                        label, node.lineno, denied
                    )
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            dotted = _attribute_path(node.func)
            reason = PY3_ONLY_ATTRIBUTES.get(dotted) if dotted else None
            method_reason = PY3_ONLY_METHODS.get(node.func.attr)
            if reason:
                errors.append(
                    "{0}:{1}: {2}(...) is Python 3-only ({3})".format(
                        label, node.lineno, dotted, reason
                    )
                )
            elif method_reason:
                errors.append(
                    "{0}:{1}: .{2}(...) is Python 3-only ({3})".format(
                        label, node.lineno, node.func.attr, method_reason
                    )
                )
            keywords = PY3_ONLY_KEYWORDS.get(dotted) if dotted else None
            if keywords:
                for keyword in node.keywords:
                    if keyword.arg in keywords:
                        errors.append(
                            "{0}:{1}: {2}(... {3}=...) is Python 3-only".format(
                                label, node.lineno, dotted, keyword.arg
                            )
                        )


def _findings(path):
    """Return (errors, warnings) for one module."""
    with open(path, "rb") as stream:
        source = stream.read()
    try:
        text = source.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = source.decode("latin-1")
    errors = []
    warnings = []

    # PEP 263.  IronPython 2.7 reads source as ASCII unless the file declares
    # an encoding, so a single non-ASCII character in a docstring is already a
    # SyntaxError there -- the module never imports, and every caller that
    # reaches it breaks.  CPython 3 reads the same file as UTF-8 and parses it
    # happily, so the offline test suite cannot see this: only the declaration
    # check catches it.
    if not _declares_source_encoding(source):
        try:
            source.decode("ascii")
        except UnicodeDecodeError as error:
            errors.append(
                "non-ASCII byte at offset {0} without a source-encoding "
                "declaration next to the first two lines".format(error.start)
            )

    # Python 3-only *node kinds* (detected by walking the AST; CPython 3.x
    # rejects ``feature_version=(2, 7)`` since 3.9, so syntax detection is
    # emulated with node types instead).  IronPython 2.7 cannot parse any of
    # these forms.
    py3_syntax_kinds = [
        ast.JoinedStr,  # f-strings
        ast.NamedExpr,  # walrus :=
        ast.AnnAssign,  # x: int = 1
        ast.AsyncFunctionDef,
        ast.AsyncFor,
        ast.AsyncWith,
        ast.Await,
        ast.YieldFrom,
    ]
    py3_syntax_seen = set()
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as error:
        errors.append("unparsable at line {0}: {1}".format(error.lineno, error.msg))
        return errors, warnings

    for node in ast.walk(tree):
        for kind in py3_syntax_kinds:
            if isinstance(node, kind):
                py3_syntax_seen.add(
                    "{0}:{1}:{2}".format(
                        os.path.basename(path),
                        getattr(node, "lineno", 0),
                        kind.__name__,
                    )
                )
        if isinstance(node, ast.arg) and getattr(node, "annotation", None) is not None:
            py3_syntax_seen.add(
                "{0}:{1}:type annotation on parameter".format(
                    os.path.basename(path), getattr(node, "lineno", 0)
                )
            )
        if isinstance(node, ast.arguments) and getattr(node, "kwonlyargs", None):
            for arg in node.kwonlyargs:
                py3_syntax_seen.add(
                    "{0}:{1}:keyword-only argument".format(
                        os.path.basename(path), getattr(arg, "lineno", 0)
                    )
                )

    for finding in sorted(py3_syntax_seen):
        errors.append("py3-only syntax: " + finding)

    # Imports and calls that parse fine but cannot run on IronPython 2.7.
    _import_findings(path, tree, errors)

    has_print_future = "from __future__ import print_function" in text

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            py3_kwargs = _KEYWORD_ONLY_BUILTINS.get(name)
            if py3_kwargs is None:
                continue
            for keyword in node.keywords:
                if keyword.arg in py3_kwargs:
                    errors.append(
                        "{0}:{1}: {2}(... {3}=...) is Python 3-only".format(
                            os.path.basename(path), node.lineno, name, keyword.arg
                        )
                    )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            pass  # attribute calls are 2.7-safe

    # Only a module that actually calls ``print`` needs the future import: it
    # is what makes ``print("a", "b")`` a call under IronPython 2.7 instead of
    # a statement printing a tuple.  A module that never prints is fine
    # without it, and warning about those buried the real cases once the
    # default set grew to the whole host tree.
    uses_print = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        for node in ast.walk(tree)
    )
    if uses_print and not has_print_future:
        warnings.append("no 'from __future__ import print_function' at module top")
    return errors, warnings


def lint(paths):
    total_errors = 0
    for path in paths:
        if not os.path.isfile(path):
            print("[missing] {0}".format(path))
            total_errors += 1
            continue
        errors, warnings = _findings(path)
        if not errors and not warnings:
            continue
        print("[module] {0}".format(path))
        for error in errors:
            total_errors += 1
            print("  [error]   {0}".format(error))
        for warning in warnings:
            print("  [warning] {0}".format(warning))
    return total_errors


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ci = False
    if "--ci" in argv:
        ci = True
        argv.remove("--ci")
    if argv:
        paths = [p if os.path.isabs(p) else os.path.join(ROOT, p) for p in argv]
    else:
        paths = [os.path.join(ROOT, rel) for rel in DEFAULT_FILES]

    missing = [p for p in paths if not os.path.isfile(p)]
    for path in missing:
        print("[missing] {0}".format(path))
    if missing:
        return 1

    errors = lint(paths)
    print("IronPython compat lint: {0} error(s)".format(errors))
    if errors:
        return 1
    if ci:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
