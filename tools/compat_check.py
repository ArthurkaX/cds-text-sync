# -*- coding: utf-8 -*-
"""IronPython 2.7 compatibility lint for modules the CODESYS host imports.

Project_fmt and the reverse-pipe daemon both run inside the CODESYS
ScriptEngine, whose host is IronPython 2.7.  The pure seams they import
(cts_shared.* and the ide_bridge modules) must therefore stay Python
2.7-compatible even though the unit tests run under CPython 3.  This tool
statically checks the exact modules the FMT workflow imports, plus the shared
helpers the daemon imports on top of that, for Python 3-only syntax, builtin
calls and source that IronPython 2.7 cannot even parse.

Usage::

    python tools/compat_check.py            # lint the FMT import graph
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

# The modules the FMT workflow imports at runtime, relative to ROOT, plus
# every bridge module that imports cts_shared.  The daemon reaches those from
# the loop, not from FMT, so they were the population the coerce.py encoding
# defect hid in and the one the list has to keep covered.
DEFAULT_FILES = [
    "shared/src/cts_shared/coerce.py",
    "shared/src/cts_shared/st/blanking.py",
    "shared/src/cts_shared/st/formatting.py",
    "shared/src/cts_shared/st/projection.py",
    "products/codesys-host/src/ide_bridge/fmt_session.py",
    "products/codesys-host/src/ide_bridge/fmt_diff.py",
    "products/codesys-host/src/ide_bridge/fmt_apply.py",
    "products/codesys-host/src/ide_bridge/ide_picker_common.py",
    "products/codesys-host/src/ide_bridge/ide_st_objects.py",
    "products/codesys-host/src/ide_bridge/ide_st_text.py",
    "products/codesys-host/src/ide_bridge/ide_handlers_sync.py",
    "products/codesys-host/src/ide_bridge/ide_handlers_project.py",
    "products/codesys-host/src/ide_bridge/ide_handlers_plc.py",
    "products/codesys-host/src/ide_bridge/ide_handlers_crc.py",
    "products/codesys-host/src/ide_bridge/ide_handlers_build.py",
    "products/codesys-host/src/ide_bridge/ide_xml.py",
    "products/codesys-host/src/ide_bridge/codesys_runtime.py",
    "products/codesys-host/src/ide_bridge/codesys_utils.py",
    "products/codesys-host/src/ide_bridge/codesys_fmt_operation.py",
    "products/codesys-host/src/ide_bridge/codesys_fmt_ui.py",
    "products/codesys-host/src/ide_bridge/snapshot_compare.py",
    "products/codesys-host/src/ide_bridge/project_snapshooter.py",
]

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

    if not has_print_future:
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
