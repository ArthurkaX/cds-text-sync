# -*- coding: utf-8 -*-
"""IronPython 2.7 compatibility lint for the headless CRC script.

``products/codesys-host/headless/plc_crc.py`` runs inside the CODESYS
ScriptEngine, whose interpreter is IronPython 2.7 (the menu entry is generated
by cts.exe and loads the C# agent).  It must stay Python-2-compatible even
though the unit tests run under CPython 3.  This tool statically checks it for
Python 3-only syntax, builtin calls and source that IronPython 2.7 cannot even
parse.  It imports nothing from the repository, so it is the whole set.

Usage::

    python tools/compat_check.py            # lint the headless CRC script
    python tools/compat_check.py <paths...> # lint explicit files

It is deliberately dependency-free (stdlib ``ast`` only) so the same command
can run on a developer machine and in CI.
"""

from __future__ import print_function

import ast
import os
import re
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The files CODESYS runs as IronPython, relative to the repository.
DEFAULT_FILES = ["products/codesys-host/headless/plc_crc.py"]

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


def _import_aliases(tree, guarded):
    """Local names bound by imports, as (module aliases, from-import members).

    ``import subprocess as sp`` binds ``sp`` to the module ``subprocess``;
    ``from os import scandir as scan`` binds ``scan`` to the attribute path
    ``os.scandir``.  Without this map those shapes sail past the denylists:
    ``sp.run(...)`` is not the literal ``subprocess.run`` the lint looks for,
    and ``run(...)`` after ``from subprocess import run`` is a bare Name, never
    an attribute call.
    """
    modules = {}
    members = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if id(node) in guarded:
                continue
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    # ``import a.b`` binds the top-level name ``a``, not ``a.b``.
                    root = alias.name.split(".")[0]
                    modules[root] = root
        elif isinstance(node, ast.ImportFrom):
            if id(node) in guarded or not node.module:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                members[alias.asname or alias.name] = node.module + "." + alias.name
    return modules, members


def _resolve_dotted(dotted, modules, members):
    """Replace the leading name of *dotted* with what the imports bound it to."""
    root, separator, rest = dotted.partition(".")
    target = members.get(root)
    if target is None:
        target = modules.get(root, root)
    return target + (separator + rest if separator else "")


def _call_path(func, modules, members):
    """The dotted callee path, import aliases resolved, or None.

    A bare Name is only interesting when a from-import bound it
    (``from os import scandir`` -> ``scandir`` -> ``os.scandir``); an ordinary
    function call resolves to nothing and is skipped.
    """
    if isinstance(func, ast.Name):
        return members.get(func.id)
    if isinstance(func, ast.Attribute):
        dotted = _attribute_path(func)
        if dotted is None:
            return None
        return _resolve_dotted(dotted, modules, members)
    return None


def _import_findings(path, tree, errors):
    """Flag Python 3-only stdlib imports and calls the tree cannot run under 2.7."""
    guarded = _guarded_import_nodes(tree)
    modules, members = _import_aliases(tree, guarded)
    # Names already reported at their from-import (``from subprocess import
    # run``), so the call that follows is not flagged a second time.
    flagged_names = set()
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
            for alias in node.names:
                if alias.name == "*":
                    continue
                member_path = node.module + "." + alias.name
                reason = PY3_ONLY_ATTRIBUTES.get(member_path)
                if reason:
                    # ``from os import scandir`` itself raises ImportError on
                    # 2.7, whether or not the name is ever called.
                    flagged_names.add(alias.asname or alias.name)
                    errors.append(
                        "{0}:{1}: imports Python 3-only {2} ({3})".format(
                            label, node.lineno, member_path, reason
                        )
                    )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in flagged_names:
                continue
            dotted = _call_path(node.func, modules, members)
            if not dotted:
                continue
            reason = PY3_ONLY_ATTRIBUTES.get(dotted)
            method_reason = PY3_ONLY_METHODS.get(dotted.rpartition(".")[2])
            if reason:
                errors.append(
                    "{0}:{1}: {2}(...) is Python 3-only ({3})".format(
                        label, node.lineno, dotted, reason
                    )
                )
            elif method_reason:
                errors.append(
                    "{0}:{1}: .{2}(...) is Python 3-only ({3})".format(
                        label, node.lineno, dotted.rpartition(".")[2], method_reason
                    )
                )
            keywords = PY3_ONLY_KEYWORDS.get(dotted)
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
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
