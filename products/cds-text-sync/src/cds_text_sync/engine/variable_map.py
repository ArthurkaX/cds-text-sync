# -*- coding: utf-8 -*-
"""
variable_map.py - Parse IEC 61131-3 declarations and expand variables to
readable scalar leaves.

Pure logic, no CODESYS dependency. Written to run on both IronPython 2.7
(inside the daemon) and CPython 3 (offline tests / CLI). Avoid f-strings and
annotations.

The runtime fact this module is built around (verified on a live PLC): only
scalar *leaf* expressions are readable online. Whole structs and whole arrays
return "Invalid expression". So a variable map must expand composite types down
to scalar leaves before reading.

Two inputs feed the same logic:
  - offline: walk project-view/*.st, owner name = file stem, decl = file text
  - daemon: walk GVL/Program objects, owner name = obj name, decl =
    obj.textual_declaration.text

Public API:
  split_decl_impl(text) -> (declaration, implementation_or_None)
  detect_owner_kind(decl) -> 'gvl' | 'program' | 'function_block' | 'function'
                             | 'dut' | None
  parse_var_blocks(decl) -> [ {scope, members:[member,...]} ]
  parse_dut(decl) -> {name, kind, fields, base} or None
  classify_type(typestr) -> dict describing scalar/array/string/ref
  TypeRegistry - holds DUT structs/enums/aliases and FB field layouts
  expand_leaves(path, typestr, registry, ...) -> [leaf, ...]

A "member" is a dict: {name, type, scope, line, initial}.
A "leaf" is a dict: {path, type, leaf(bool), note}.
"""

import io
import os
import re
import sys

try:
    from cts_shared.st import declarations as _shared_declarations
except ImportError:
    _SHARED_SRC = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "..", "shared", "src"
    ))
    if _SHARED_SRC not in sys.path:
        sys.path.insert(0, _SHARED_SRC)
    from cts_shared.st import declarations as _shared_declarations


ST_IMPLEMENTATION_MARKER = "// --- implementation ---"

# Base IEC scalar types (without optional STRING/WSTRING length).
SCALAR_TYPES = set([
    "BOOL", "BIT", "BYTE", "WORD", "DWORD", "LWORD",
    "SINT", "USINT", "INT", "UINT", "DINT", "UDINT", "LINT", "ULINT",
    "REAL", "LREAL",
    "TIME", "LTIME", "TIME_OF_DAY", "TOD", "DATE", "DATE_AND_TIME", "DT",
    "LTIME_OF_DAY", "LTOD", "LDATE", "LDATE_AND_TIME", "LDT",
    "STRING", "WSTRING", "CHAR", "WCHAR",
    "POINTER", "REFERENCE",  # pointers read as their address scalar
])

_VAR_OPENERS = [
    "VAR_GLOBAL", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
    "VAR_TEMP", "VAR_STAT", "VAR_EXTERNAL", "VAR_CONFIG",
    "VAR_INST", "VAR",
]


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _blank_noise(text):
    """Blank comments, strings, and nested pragmas without changing offsets."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                out.append(d)
                if d == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        out.append(text[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "(" and nxt == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == ")"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
            continue
        if c == "{":
            depth = 1
            out.append(" ")
            i += 1
            while i < n and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)

def split_decl_impl(text):
    """Split a .st blob into (declaration, implementation).

    implementation is None when the marker is absent.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    marker = "\n" + ST_IMPLEMENTATION_MARKER + "\n"
    if marker in normalized:
        decl, impl = normalized.split(marker, 1)
        return decl, impl
    if ST_IMPLEMENTATION_MARKER in normalized:
        decl, impl = normalized.split(ST_IMPLEMENTATION_MARKER, 1)
        return decl, impl
    return normalized, None


def detect_owner_kind(decl):
    """Classify a declaration blob by its leading keyword."""
    blanked = _blank_noise(decl or "")
    for raw in blanked.split("\n"):
        line = raw.strip()
        if not line:
            continue
        word = line.split()[0].upper()
        if word in ("PROGRAM",):
            return "program"
        if word in ("FUNCTION_BLOCK",):
            return "function_block"
        if word in ("FUNCTION", "METHOD"):
            return "function"
        if word == "TYPE":
            return "dut"
        if word.startswith("VAR_GLOBAL") or word == "VAR_GLOBAL":
            return "gvl"
        # An attribute-only first line was already blanked; keep scanning.
    return None


# ---------------------------------------------------------------------------
# Statement splitting
# ---------------------------------------------------------------------------

# Type registry
# ---------------------------------------------------------------------------

class TypeRegistry(object):
    """Holds composite type layouts (DUT struct/enum/alias + FB fields) and
    integer constants used as array bounds."""

    def __init__(self):
        self.types = {}        # name -> {kind, fields, base}
        self.constants = {}    # "GVL.NAME" and bare "NAME" -> int

    def add_dut(self, decl):
        d = parse_dut(decl)
        if d:
            self.types[d["name"].lower()] = d
        return d

    def add_fb(self, name, decl):
        """Register a function block's instance-visible fields as a struct."""
        fields = []
        for block in parse_var_blocks(decl):
            # Online-visible FB members: VAR / VAR_INPUT / VAR_OUTPUT.
            if block["scope"] in ("VAR", "VAR_INPUT", "VAR_OUTPUT"):
                for mem in block["members"]:
                    fields.append({"name": mem["name"], "type": mem["type"],
                                   "initial": mem["initial"]})
        self.types[name.lower()] = {"name": name, "kind": "fb",
                                    "fields": fields, "base": None}

    def add_constants_from_gvl(self, owner, decl):
        """Record integer CONSTANT globals for array-bound resolution."""
        for block in parse_var_blocks(decl):
            for mem in block["members"]:
                val = _as_int(mem["initial"])
                if val is not None:
                    # IEC identifiers are case-insensitive; key on lower-case.
                    self.constants[(owner + "." + mem["name"]).lower()] = val
                    self.constants.setdefault(mem["name"].lower(), val)

    def lookup(self, name):
        return self.types.get((name or "").strip().lower())


def _as_int(text):
    """Parse an integer literal that may be typed (INT#5) or based (16#FF)."""
    if text is None:
        return None
    t = text.strip()
    if not t:
        return None
    # Strip typed prefix like INT#, USINT#
    m = re.match(r"(?i)^[A-Z_]\w*#(.+)$", t)
    if m:
        t = m.group(1).strip()
    # Based literal base#digits
    m = re.match(r"^(\d+)#([0-9A-Fa-f_]+)$", t)
    if m:
        try:
            return int(m.group(2).replace("_", ""), int(m.group(1)))
        except (ValueError, TypeError):
            return None
    try:
        return int(t.replace("_", ""))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Leaf expansion
# ---------------------------------------------------------------------------

DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_LEAVES = 5000


def _resolve_bound(expr, registry, resolver):
    """Resolve an array bound expression to an int, or None."""
    val = _as_int(expr)
    if val is not None:
        return val
    if registry is not None:
        c = registry.constants.get(expr.strip().lower())
        if c is not None:
            return c
    if resolver is not None:
        try:
            return resolver(expr.strip())
        except Exception:
            return None
    return None


def expand_leaves(path, typestr, registry,
                  bound_resolver=None, max_depth=DEFAULT_MAX_DEPTH,
                  max_leaves=DEFAULT_MAX_LEAVES, _depth=0, _budget=None):
    """Expand a variable into readable scalar leaves.

    Returns a list of leaf dicts: {path, type, leaf, note}.
      leaf=True  -> a scalar expression that read_value should accept
      leaf=False -> could not expand (unresolved bound / unknown type / too deep)

    bound_resolver(expr)->int|None lets the daemon resolve array bounds at
    runtime; offline callers may pass None and rely on registry.constants.
    """
    if _budget is None:
        _budget = [max_leaves]

    def _emit(p, t, leaf, note):
        if _budget[0] <= 0:
            return [{"path": p, "type": t, "leaf": False, "note": "leaf-limit"}]
        _budget[0] -= 1
        return [{"path": p, "type": t, "leaf": leaf, "note": note}]

    if _depth > max_depth:
        return _emit(path, typestr, False, "max-depth")

    info = classify_type(typestr)

    if info["kind"] == "scalar":
        if info["base"] in ("POINTER", "REFERENCE"):
            return _emit(path, info["base"], True, "pointer-or-reference")
        return _emit(path, info["base"], True, "")

    if info["kind"] == "array":
        # Resolve each dimension; build index tuples.
        ranges = []
        for (lo, hi) in info["dims"]:
            loi = _resolve_bound(lo, registry, bound_resolver)
            hii = _resolve_bound(hi, registry, bound_resolver)
            if loi is None or hii is None or hii < loi:
                return _emit(path, typestr, False, "unresolved-bound")
            ranges.append((loi, hii))
        out = []
        for idx in _index_product(ranges):
            sub = path + "[" + ",".join(str(x) for x in idx) + "]"
            out.extend(expand_leaves(sub, info["elem"], registry,
                                     bound_resolver, max_depth, max_leaves,
                                     _depth + 1, _budget))
            if _budget[0] <= 0:
                break
        return out

    # ref: DUT / FB / enum / alias / unknown
    name = info["name"]
    entry = registry.lookup(name) if registry is not None else None
    if entry is None:
        # Unknown type — not reliably readable as a scalar leaf.
        # leaf=false keeps the snapshot clean and prevents failed reads.
        return _emit(path, name, False, "unknown-type")
    if entry["kind"] == "enum":
        return _emit(path, name, True, "enum")
    if entry["kind"] == "alias":
        return expand_leaves(path, entry["base"], registry, bound_resolver,
                             max_depth, max_leaves, _depth + 1, _budget)
    if entry["kind"] in ("struct", "fb"):
        out = []
        for field in entry["fields"]:
            sub = path + "." + field["name"]
            out.extend(expand_leaves(sub, field["type"], registry,
                                     bound_resolver, max_depth, max_leaves,
                                     _depth + 1, _budget))
            if _budget[0] <= 0:
                break
        if not out:
            return _emit(path, name, False, "empty-composite")
        return out
    return _emit(path, name, True, "unknown-kind")


def _index_product(ranges):
    """Yield index tuples for a list of (lo, hi) inclusive ranges."""
    if not ranges:
        return
    idx = [lo for (lo, hi) in ranges]
    while True:
        yield tuple(idx)
        k = len(ranges) - 1
        while k >= 0:
            idx[k] += 1
            if idx[k] <= ranges[k][1]:
                break
            idx[k] = ranges[k][0]
            k -= 1
        if k < 0:
            return


# ---------------------------------------------------------------------------
# High-level map builder (CLI / offline use)
# ---------------------------------------------------------------------------

def pou_name(decl, default):
    """Extract the POU name from a PROGRAM/FUNCTION_BLOCK/FUNCTION header."""
    blanked = _blank_noise(decl or "")
    m = re.search(
        r"(?im)^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_]\w*)",
        blanked)
    return m.group(1) if m else default


def _read_text(path):
    f = io.open(path, "r", encoding="utf-8", errors="replace")
    try:
        return f.read()
    finally:
        f.close()


def iter_st_files(root):
    """Yield absolute paths of every .st file under root."""
    for dirpath, _dirs, names in os.walk(root):
        for nm in names:
            if nm.lower().endswith(".st"):
                yield os.path.join(dirpath, nm)


# Which declaration blocks count as "the owner's own variables" per owner kind.
_OWNER_SCOPES = {
    "gvl": ("VAR_GLOBAL",),
    "program": ("VAR", "VAR_GLOBAL"),
}


def build_map_from_dir(root, include_programs=True, bound_resolver=None):
    """Walk a project-view directory and build variable-map rows.

    Returns (rows, stats). Each row is a dict:
      path, name, type, scope, owner, file, line, initial, leaf, note

    'leaf' is True when the expression is a scalar that read_value should accept.
    Rows with leaf=False (unresolved bound / too deep) are still listed so the
    map is complete; snapshot skips them.
    """
    registry = TypeRegistry()
    owners = []  # (owner_name, kind, decl, relpath)

    for path in iter_st_files(root):
        decl, _impl = split_decl_impl(_read_text(path))
        kind = detect_owner_kind(decl)
        stem = os.path.splitext(os.path.basename(path))[0]
        rel = os.path.relpath(path, root)
        if kind == "dut":
            registry.add_dut(decl)
        elif kind == "function_block":
            registry.add_fb(pou_name(decl, stem), decl)
        # Harvest integer constants from every owner for bound resolution.
        registry.add_constants_from_gvl(stem, decl)
        owners.append((stem, kind, decl, rel))

    rows = []
    stats = {"owners": 0, "members": 0, "leaves": 0, "readable": 0}

    wanted = ("gvl",) if not include_programs else ("gvl", "program")
    for owner, kind, decl, rel in owners:
        if kind not in wanted:
            continue
        scopes = _OWNER_SCOPES.get(kind, ())
        stats["owners"] += 1
        for block in parse_var_blocks(decl):
            if block["scope"] not in scopes:
                continue
            for mem in block["members"]:
                stats["members"] += 1
                root_path = owner + "." + mem["name"]
                resolver = None
                if bound_resolver is not None:
                    resolver = _make_owner_resolver(owner, bound_resolver)
                leaves = expand_leaves(root_path, mem["type"], registry,
                                       bound_resolver=resolver)
                for lf in leaves:
                    stats["leaves"] += 1
                    if lf["leaf"]:
                        stats["readable"] += 1
                    leaf_name = lf["path"].rsplit(".", 1)[-1]
                    is_root = lf["path"] == root_path
                    rows.append({
                        "path": lf["path"],
                        "name": leaf_name,
                        "type": lf["type"],
                        "scope": block["scope"],
                        "owner": owner,
                        "file": rel,
                        "line": mem["line"],
                        "initial": mem["initial"] if is_root else "",
                        "leaf": lf["leaf"],
                        "note": lf["note"],
                    })
    return rows, stats


def build_enum_registry(root):
    """Walk a project-view directory and return {DUT_name: {member: int_value}}
    for every enum found. Used by restore to translate 'TYPE.member' snapshot
    values into numeric literals acceptable to CODESYS set_prepared_value
    (which double-prefixes qualified enumerators).
    """
    registry = TypeRegistry()
    for path in iter_st_files(root):
        decl, _impl = split_decl_impl(_read_text(path))
        if detect_owner_kind(decl) == "dut":
            registry.add_dut(decl)
    result = {}
    for name, entry in registry.types.items():
        if entry.get("kind") == "enum":
            result[name] = {
                f["name"]: f.get("value")
                for f in entry.get("fields", [])
                if f.get("value") is not None
            }
    return result


def _make_owner_resolver(owner, bound_resolver):
    """Wrap a raw value reader so array bounds resolve in the owner's scope."""
    def _resolve(expr):
        for cand in (owner + "." + expr, expr):
            try:
                val = bound_resolver(cand)
            except Exception:
                val = None
            iv = _as_int(val) if isinstance(val, str) else val
            if isinstance(iv, int):
                return iv
        return None
    return _resolve


def filter_rows_by_path(rows, path_filter):
    """Keep rows equal to path_filter or under it (dot/bracket descendants)."""
    if not path_filter:
        return rows
    pf = path_filter
    # Allow an optional leading "Application." in the filter.
    alt = pf[len("Application."):] if pf.startswith("Application.") else None
    out = []
    for r in rows:
        p = r["path"]
        for base in (pf, alt):
            if not base:
                continue
            if p == base or p.startswith(base + ".") or p.startswith(base + "["):
                out.append(r)
                break
    return out


MAP_COLUMNS = ["path", "name", "type", "scope", "owner", "file", "line",
               "initial"]

# Keep the engine's historical API names while making the shared parser the
# implementation used by all public callers. The old definitions above remain
# only as a compatibility reference for IronPython source consumers and can be
# removed once the bridge no longer loads this module as a flat script.
SCALAR_TYPES = set(_shared_declarations.SCALAR_TYPES)
_split_statements = _shared_declarations._split_statements
_split_top_level = _shared_declarations._split_top_level
_parse_member_statement = _shared_declarations._parse_member_statement
parse_var_blocks = _shared_declarations.parse_var_blocks
parse_dut = _shared_declarations.parse_dut
_base_type_name = _shared_declarations._base_type_name
classify_type = _shared_declarations.classify_type
_split_dims = _shared_declarations._split_dims
