# -*- coding: utf-8 -*-
"""
gvl.py - GVL (Global Variable List) generation for CODESYS.

This module detects runtime variable references in SVG-derived element specs
and generates a ``.st`` GVL file with the required declarations.  It is called
from ``commands.from_svg`` when ``--gvl`` or ``--gvl-file`` is used.

Usage::

    from cds_text_sync.visu import gvl

    vars = gvl.collect_variables(elements)
    st = gvl.generate_gvl(vars, gvl_name="VisuVars")
    gvl.write_gvl_file("path/to/VisuVars.st", st)
"""

from __future__ import print_function

import os
import re

# ---------------------------------------------------------------------------
# Variable detection
# ---------------------------------------------------------------------------

_DOTTED_VAR_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")

_FMT_RE = re.compile(r"%[-+ 0#]*[0-9]*(?:\.[0-9]+)?([diufFeEgGsxX])")


def collect_variables(elements):
    """Scan a list of ElementSpec dicts for runtime variable references.

    Checks these sources:

    - ``params["text_var"]`` (``data-text-var``)
    - ``params["tap_var"]`` (``data-cds-tap`` with ``st:`` prefix)
    - ``params["toggle_var"]`` (``data-cds-tap`` with ``toggle:`` prefix)
    - ``params["configured_inputs"][*]["values"]["variable"]``
    - ``params["input_actions"][*]["values"]`` keys like ``variable``,
      ``snippet`` (ST snippet content is scanned for dotted variables).

    Returns a deduplicated dict mapping *variable path* → *variable name*
    (the last segment of the dotted path).  Example::

        {"HMI.Temperature": "Temperature", "HMI.PumpRunning": "PumpRunning"}
    """
    variables = {}  # full_path -> short_name

    for elem in elements:
        params = elem.get("params", {})

        # data-text-var
        text_var = params.get("text_var")
        if text_var:
            _record_var(text_var, variables)

        # Golden-template control binding (lamp, image-switcher, combobox, ...).
        var = params.get("var")
        if var:
            _record_var(var, variables)

        # data-cds-tap / data-cds-action: tap_var
        tap_var = params.get("tap_var")
        if tap_var:
            _record_var(tap_var, variables)

        # toggle_var
        toggle_var = params.get("toggle_var")
        if toggle_var:
            _record_var(toggle_var, variables)

        # configured_complex_inputs (used by the new action parser)
        for action in params.get("configured_inputs", []):
            vals = action.get("values", {})
            for key in ("variable",):
                v = vals.get(key)
                if v:
                    _record_var(v, variables)
            # ST snippet content may contain variable references.
            snippet = vals.get("snippet", "")
            if snippet:
                for m in _DOTTED_VAR_RE.finditer(snippet):
                    _record_var(m.group(), variables)

        # input_actions (used by the old action parser)
        for action in params.get("input_actions", []):
            vals = action.get("values", {})
            for key in ("variable",):
                v = vals.get(key)
                if v:
                    _record_var(v, variables)
            snippet = vals.get("snippet", "")
            if snippet:
                for m in _DOTTED_VAR_RE.finditer(snippet):
                    _record_var(m.group(), variables)

    return variables


def _record_var(var_expr, variables):
    """Parse a variable expression and record it in the *variables* dict.

    Handles dotted paths (``HMI.Temperature``) and bare names.
    Skips ST keyword expressions.
    """
    expr = var_expr.strip()
    # If it looks like a dotted variable path, extract it.
    if "." in expr:
        parts = expr.split(".")
        # Take the full dotted path as the key.
        variables[expr] = parts[-1]
    elif re.match(r"^[A-Za-z_]\w*$", expr):
        # Bare name (no GVL prefix).
        variables[expr] = expr


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

# printf conversion letter -> ST type. Anything unmapped falls back to BOOL.
_TYPE_BY_CONV = {
    "f": "REAL",
    "F": "REAL",
    "e": "REAL",
    "E": "REAL",
    "g": "REAL",
    "G": "REAL",
    "d": "INT",
    "i": "INT",
    "u": "INT",
    "x": "INT",
    "X": "INT",
    "s": "STRING",
}


def _infer_type(fmt):
    """Infer an ST type from a textfield format string.

    ``%3.1f`` -> ``REAL``, ``%d`` -> ``INT``, ``%s`` -> ``STRING``. When no
    printf conversion is present (or *fmt* is empty/None) returns ``BOOL`` --
    the sensible default for tap/toggle/action booleans.
    """
    if not fmt:
        return "BOOL"
    m = _FMT_RE.search(fmt)
    if not m:
        return "BOOL"
    return _TYPE_BY_CONV.get(m.group(1), "BOOL")


# ST type of a golden-template control's ``var`` binding, keyed by element
# type. Anything not listed defaults to BOOL.
_VAR_TYPE_BY_ELEMENT = {
    "lamp": "BOOL",
    "image-switcher": "BOOL",
    "combobox": "INT",
}


def collect_variable_types(elements):
    """Return ``{full_path: st_type}`` inferred from *elements*.

    Only textfields carry a format string, so their bound ``text_var`` gets a
    type inferred from ``params["text"]``. Every other variable source (tap,
    toggle, actions, ST snippets) is boolean by nature and maps to ``BOOL``.
    Golden-template controls bind through ``params["var"]``; their type comes
    from ``_VAR_TYPE_BY_ELEMENT`` (lamp/image-switcher -> BOOL, combobox -> INT).

    A variable that appears both as a typed textfield and elsewhere keeps the
    inferred (non-BOOL) type -- the format string is the stronger signal.
    """
    types = {}  # full_path -> st_type

    def _assign(path, st_type):
        path = (path or "").strip()
        if not path:
            return
        # Let a concrete type win over a previously recorded BOOL default.
        if types.get(path, "BOOL") == "BOOL":
            types[path] = st_type

    for elem in elements:
        params = elem.get("params", {})

        text_var = params.get("text_var")
        if text_var:
            _assign(text_var, _infer_type(params.get("text")))

        # Golden-template control binding. The ST type depends on the control:
        # a lamp/image-switcher reads a BOOL, a combobox an INT.
        var = params.get("var")
        if var:
            _assign(var, _VAR_TYPE_BY_ELEMENT.get(elem.get("type"), "BOOL"))

        for key in ("tap_var", "toggle_var"):
            v = params.get(key)
            if v:
                _assign(v, "BOOL")

        for source in ("configured_inputs", "input_actions"):
            for action in params.get(source, []):
                vals = action.get("values", {})
                v = vals.get("variable")
                if v:
                    _assign(v, "BOOL")
                snippet = vals.get("snippet", "")
                if snippet:
                    for m in _DOTTED_VAR_RE.finditer(snippet):
                        _assign(m.group(), "BOOL")

    return types


# ---------------------------------------------------------------------------
# ST generation
# ---------------------------------------------------------------------------

_HEADER = """\
{attribute 'qualified_only'}
VAR_GLOBAL
"""

_FOOTER = """\
END_VAR
"""

_VAR_DECL = """\
    {name} : {type};
"""

_HIDED_ATTR = """\
    {attribute 'hide'}
"""


def generate_gvl(variables, gvl_name="VisuVars", default_type="BOOL", types=None):
    """Generate a GVL ``.st`` file as a string.

    *variables*: dict of ``{full_path: short_name}`` (from ``collect_variables``).
    *gvl_name*: name of the GVL (used in file header, e.g. ``GVL_VisuVars``).
    *default_type*: ST type to use when none can be inferred (default ``BOOL``).
    *types*: optional ``{full_path: st_type}`` (from ``collect_variable_types``)
        overriding *default_type* per variable.

    Returns the full ``.st`` file text.
    """
    if not variables:
        return ""

    types = types or {}

    lines = []
    lines.append(_HEADER)
    lines.append(_HIDED_ATTR)
    lines.append("    // Auto-generated by cts visu from-svg --gvl\n")

    # Sort for deterministic output.
    for full_path in sorted(variables, key=lambda s: s.lower()):
        short_name = variables[full_path]
        vtype = types.get(full_path, default_type)
        if "." in full_path:
            # For dotted paths like HMI.Temperature, we declare the short name.
            # The 'qualified_only' attribute ensures the GVL prefix is used.
            lines.append(
                "    {name} : {type};\n".format(name=short_name, type=vtype)
            )
        else:
            lines.append(
                "    {name} : {type};\n".format(name=full_path, type=vtype)
            )

    lines.append(_FOOTER)
    return "".join(lines)


def write_gvl_file(path, content):
    """Write *content* to *path*, creating parent directories as needed."""
    if not content:
        return
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


# ---------------------------------------------------------------------------
# Existing GVL scanning (deduplication)
# ---------------------------------------------------------------------------


# A GVL declaration line, e.g. ``    OutTemp : REAL := 0.0;``. PLC globals are
# very often mapped to hardware, which puts an ``AT %IX0.6`` location between
# the name and the colon; missing that made every located variable invisible to
# the cross-GVL dedup below, so ``FIO_SIGNALS.Emitter`` looked undeclared.
_DECL_RE = re.compile(
    r"^\s+(\w+)\s*(?:AT\s+%[\w.*]+\s*)?:", re.IGNORECASE | re.MULTILINE
)


def detect_existing_variables(gvl_path):
    """Scan an existing GVL ``.st`` file for declared variable names.

    Returns a set of variable names (the last segment after ``.`` if dotted).
    """
    if not os.path.isfile(gvl_path):
        return set()
    existing = set()
    with open(gvl_path, "r", encoding="utf-8") as handle:
        for line in handle:
            m = _DECL_RE.match(line)
            if m:
                existing.add(m.group(1))
    return existing


def scan_project_gvls(project_view_dir):
    """Map every GVL in the project to the variable names it declares.

    Returns ``{gvl_name: set(var_names)}`` where *gvl_name* is the ``.st``
    file's basename without extension -- this matches the qualified prefix
    CODESYS uses (e.g. ``HMI.st`` -> ``HMI``, referenced as ``HMI.MyVar``).

    Only files containing a ``VAR_GLOBAL`` block are included, so ordinary
    POUs/functions are ignored. Used to avoid re-declaring a variable that
    already lives in another project GVL.
    """
    result = {}
    if not project_view_dir or not os.path.isdir(project_view_dir):
        return result
    for root, _dirs, files in os.walk(project_view_dir):
        for fname in files:
            if not fname.endswith(".st"):
                continue
            full = os.path.join(root, fname)
            try:
                with open(full, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except (IOError, OSError, UnicodeDecodeError):
                continue
            if "VAR_GLOBAL" not in text:
                continue
            name = fname[:-3]  # strip .st
            names = set(
                m.group(1) for m in _DECL_RE.finditer(text) if m.group(1)
            )
            # Merge in case two files share a basename in different folders.
            result.setdefault(name, set()).update(names)
    return result


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------


def partition_variables(variables, project_gvls, gvl_name):
    """Split referenced paths into what this GVL declares and what it only reads.

    A path names its owner in the *first* segment, not the last: the reference
    ``GVL_Sensors.Scale.Q`` reads member ``Q`` of instance ``Scale``, and what
    ``GVL_Sensors`` actually declares is ``Scale``. Matching on everything
    before the final dot instead looks for a GVL called ``GVL_Sensors.Scale``,
    finds nothing, and re-declares the leaf -- which is how nine lamps once
    produced nine bare ``Q : BOOL;`` lines that CODESYS refuses to compile.

    Returns ``(declare, unresolved)``: *declare* maps full path to the
    identifier to emit, *unresolved* maps full path to why we declined.
    """
    declare = {}
    unresolved = {}
    for full_path in sorted(variables):
        short_name = variables[full_path]
        if "." not in full_path:
            declare[full_path] = short_name
            continue
        owner, _, member_path = full_path.partition(".")
        head = member_path.partition(".")[0]
        if owner == gvl_name:
            # Addressed to us. A nested path names a member of an instance we
            # would have to invent a type for, so say so rather than guess.
            if "." in member_path:
                unresolved[full_path] = (
                    "cannot synthesise nested member {0!r}; declare {1!r} in "
                    "{2} yourself".format(member_path, head, gvl_name)
                )
            else:
                declare[full_path] = member_path
            continue
        known = project_gvls.get(owner)
        if known is not None:
            if head not in known:
                unresolved[full_path] = (
                    "GVL {0!r} declares no {1!r} -- adding it to {2} would "
                    "not satisfy this reference".format(owner, head, gvl_name)
                )
            # Declared in its own GVL: reference it, never re-declare it here.
            continue
        declare[full_path] = short_name

    # Two paths can still land on one identifier. Emitting both repeats the
    # declaration, so keep one and say which reference went unserved.
    kept = {}
    by_name = {}
    for full_path in sorted(declare):
        name = declare[full_path]
        if name in by_name:
            unresolved[full_path] = (
                "identifier {0!r} already declared for {1!r}; two paths cannot "
                "share one declaration".format(name, by_name[name])
            )
            continue
        by_name[name] = full_path
        kept[full_path] = name
    return kept, unresolved


def ensure_gvl(
    project_view_dir, elements, gvl_name="VisuVars", gvl_path=None, warn=None
):
    """Ensure a GVL file exists for the variables referenced by *elements*.

    Returns the path to the GVL file, or ``None`` if no variables were
    detected. See :func:`ensure_gvl_result` when the caller needs to know
    whether the file was actually written.
    """
    path, _written = ensure_gvl_result(
        project_view_dir, elements, gvl_name=gvl_name, gvl_path=gvl_path, warn=warn
    )
    return path


def ensure_gvl_result(
    project_view_dir, elements, gvl_name="VisuVars", gvl_path=None, warn=None
):
    """Ensure a GVL exists, reporting whether anything was written.

    Returns ``(path, written)``. ``path`` is ``None`` when no variables were
    detected at all; otherwise it is the GVL file, and ``written`` says whether
    this call added declarations to it.

    The flag exists because the two outcomes are indistinguishable from the
    path alone, and they mean opposite things to an author: a screen bound
    entirely to GVLs that already exist -- the normal case once a project has
    real signals -- would otherwise be reported as "Updated GVL", sending
    somebody to look for declarations that were never added.

    *project_view_dir*: root of the project-view (used for default path).
    *elements*: list of ElementSpec dicts.
    *gvl_name*: GVL name (default ``VisuVars``).
    *gvl_path*: explicit output path (default
        ``<project_view_dir>/POUs/<gvl_name>.st``).
    *warn*: optional ``callable(message)`` used to report references this GVL
        must not fabricate a declaration for.
    """
    variables = collect_variables(elements)
    if not variables:
        return None, False

    var_types = collect_variable_types(elements)

    if not gvl_path:
        gvl_dir = os.path.join(project_view_dir, "POUs")
        gvl_path = os.path.join(gvl_dir, gvl_name + ".st")

    # A dotted path is only declarable here when it addresses this GVL; the
    # rest either already resolve elsewhere in the project or dangle.
    project_gvls = scan_project_gvls(project_view_dir)
    remaining, unresolved = partition_variables(variables, project_gvls, gvl_name)
    if unresolved and warn:
        for full_path in sorted(unresolved):
            warn("{0} -- {1}".format(full_path, unresolved[full_path]))

    # Check for duplicates against the target file itself (flat HMI.* names
    # that legitimately land in this GVL).
    existing = detect_existing_variables(gvl_path)
    new_vars = {k: v for k, v in remaining.items() if v not in existing}

    if not new_vars:
        # All variables already declared (here or in another project GVL).
        return gvl_path, False

    content = generate_gvl(new_vars, gvl_name=gvl_name, types=var_types)

    if os.path.isfile(gvl_path):
        # Append to existing GVL (insert new declarations before END_VAR).
        with open(gvl_path, "r", encoding="utf-8") as handle:
            existing_text = handle.read()
        end_marker = "END_VAR"
        idx = existing_text.rfind(end_marker)
        if idx >= 0:
            # Extract the variable declarations (skip header/footer).
            new_block = content[len(_HEADER) : -len(_FOOTER)]
            content = existing_text[:idx] + new_block + existing_text[idx:]
        else:
            content = existing_text + "\n" + content

    write_gvl_file(gvl_path, content)
    return gvl_path, True
