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

import re

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


def _blank_noise(text):
    """Replace comments and pragmas with spaces, preserving offsets/newlines.

    String literals are respected so a // or (* inside a string is not treated
    as a comment. Newlines are kept so line numbers stay correct.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "'" or c == '"':
            # Copy the string literal verbatim (handles doubled-quote escape).
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
            # blank the closing *)
            if i < n:
                out.append("  ")
                i += 2
            continue
        if c == "{":
            while i < n and text[i] != "}":
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append(" ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


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

def _split_statements(body):
    """Yield (statement_text, offset_in_body) split on top-level ';'.

    Respects (), [], and string literals so initializers spanning lines or
    containing ';' are kept whole.
    """
    stmts = []
    depth = 0
    start = 0
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "'" or c == '"':
            quote = c
            i += 1
            while i < n:
                if body[i] == quote:
                    if i + 1 < n and body[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            if depth > 0:
                depth -= 1
        elif c == ";" and depth == 0:
            stmts.append((body[start:i], start))
            start = i + 1
        i += 1
    tail = body[start:]
    if tail.strip():
        stmts.append((tail, start))
    return stmts


def _split_top_level(text, sep):
    """Find the first top-level occurrence of sep (':' or ':=').

    Returns index or -1. Respects brackets and strings.
    """
    depth = 0
    i = 0
    n = len(text)
    slen = len(sep)
    while i < n:
        c = text[i]
        if c == "'" or c == '"':
            quote = c
            i += 1
            while i < n:
                if text[i] == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            if depth > 0:
                depth -= 1
        elif depth == 0 and text[i:i + slen] == sep:
            # For ':' make sure it is not ':='
            if sep == ":" and text[i:i + 2] == ":=":
                i += 2
                continue
            return i
        i += 1
    return -1


def _parse_member_statement(stmt):
    """Parse 'name [AT %...] : type [:= init]' -> (name, type, initial) or None."""
    colon = _split_top_level(stmt, ":")
    if colon < 0:
        return None
    left = stmt[:colon].strip()
    right = stmt[colon + 1:].strip()
    if not left or not right:
        return None
    # Left side: may be "a, b, c" (multi-decl) and may contain "AT %MW0".
    # Drop an AT clause.
    at_idx = re.search(r"(?i)\bAT\b", left)
    if at_idx:
        left = left[:at_idx.start()].strip()
    names = [p.strip() for p in left.split(",") if p.strip()]
    if not names:
        return None
    # Reject if a name is not an identifier (guards against parsing garbage).
    for nm in names:
        if not re.match(r"^[A-Za-z_]\w*$", nm):
            return None
    # Right side: split type and initializer.
    assign = _split_top_level(right, ":=")
    if assign >= 0:
        typ = right[:assign].strip()
        init = right[assign + 2:].strip()
    else:
        typ = right.strip()
        init = ""
    typ = re.sub(r"\s+", " ", typ)
    return (names, typ, init)


def parse_var_blocks(decl):
    """Parse all VAR_* blocks. Returns [ {scope, members} ].

    member = {name, type, scope, line, initial}
    """
    blanked = _blank_noise(decl or "")
    blocks = []
    # Iterate lines to find block boundaries, then parse bodies by absolute
    # offset so line numbers stay accurate.
    lines = blanked.split("\n")
    line_starts = []
    pos = 0
    for ln in lines:
        line_starts.append(pos)
        pos += len(ln) + 1

    i = 0
    nlines = len(lines)
    while i < nlines:
        stripped = lines[i].strip()
        first = stripped.split()[0].upper() if stripped else ""
        opener = None
        if first in _VAR_OPENERS:
            opener = first
        if opener is None:
            i += 1
            continue
        scope = opener
        # Body starts right after this opener line.
        body_start = line_starts[i] + len(lines[i]) + 1
        # Find END_VAR.
        j = i + 1
        while j < nlines and lines[j].strip().upper() != "END_VAR" \
                and not lines[j].strip().upper().startswith("END_VAR"):
            j += 1
        body_end = line_starts[j] if j < nlines else len(blanked)
        body = blanked[body_start:body_end]
        members = []
        for stmt, off in _split_statements(body):
            parsed = _parse_member_statement(stmt)
            if not parsed:
                continue
            names, typ, init = parsed
            abs_off = body_start + off
            # Skip leading whitespace to point at the name.
            lead = len(stmt) - len(stmt.lstrip())
            line_no = blanked[:abs_off + lead].count("\n") + 1
            for nm in names:
                members.append({
                    "name": nm,
                    "type": typ,
                    "scope": scope,
                    "line": line_no,
                    "initial": init,
                })
        blocks.append({"scope": scope, "members": members})
        i = j + 1
    return blocks


def parse_dut(decl):
    """Parse a TYPE...END_TYPE declaration.

    Returns {name, kind: 'struct'|'enum'|'alias'|'union', fields, base} or None.
    fields is a list of member dicts for structs/unions.
    """
    blanked = _blank_noise(decl or "")
    m = re.search(r"(?is)\bTYPE\s+([A-Za-z_]\w*)\s*:(.*?)\bEND_TYPE\b", blanked)
    if not m:
        return None
    name = m.group(1)
    body = m.group(2)
    upper = body.upper()
    for kw, end_kw in (("STRUCT", "END_STRUCT"), ("UNION", "END_UNION")):
        if kw in upper and end_kw in upper:
            inner = re.search(r"(?is)" + kw + r"(.*?)" + end_kw, body)
            fields = []
            if inner:
                for stmt, _off in _split_statements(inner.group(1)):
                    parsed = _parse_member_statement(stmt)
                    if not parsed:
                        continue
                    names, typ, init = parsed
                    for nm in names:
                        fields.append({"name": nm, "type": typ,
                                       "initial": init})
            # Unions expand like structs (every member is a readable leaf).
            return {"name": name, "kind": "struct", "fields": fields,
                    "base": None}
    # Enum: a parenthesised list, optionally with a trailing base type.
    paren = body.strip()
    if paren.startswith("("):
        close = paren.rfind(")")
        base = ""
        inside = ""
        if close >= 0:
            inside = paren[1:close]
            base = paren[close + 1:].strip().rstrip(";").strip()
        # Parse member list: NAME [ := <int-expr> ] [, NAME [...]]
        # Split on top-level commas (respecting parens/strings).
        items = []
        depth = 0
        cur = []
        i = 0
        n = len(inside)
        in_str = None
        while i < n:
            c = inside[i]
            if in_str:
                cur.append(c)
                if c == in_str and (i + 1 >= n or inside[i + 1] != in_str):
                    in_str = None
                i += 1
                continue
            if c in ("'", '"'):
                in_str = c
                cur.append(c)
                i += 1
                continue
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth = max(0, depth - 1)
            if c == "," and depth == 0:
                items.append("".join(cur).strip())
                cur = []
            else:
                cur.append(c)
            i += 1
        if cur:
            items.append("".join(cur).strip())

        fields = []
        last_value = -1
        for raw_item in items:
            if not raw_item:
                continue
            # Strip attribute blocks and inline comments
            stmt_clean = re.sub(r"\{[^}]*\}", " ", raw_item)
            stmt_clean = re.sub(r"//.*?$", "", stmt_clean, flags=re.M)
            stmt_clean = stmt_clean.strip().rstrip(",").strip()
            if not stmt_clean:
                continue
            m_em = re.match(r"^([A-Za-z_]\w*)\s*(?::=\s*([^,]+))?$",
                            stmt_clean)
            if not m_em:
                continue
            mem_name = m_em.group(1)
            mem_val_expr = m_em.group(2)
            if mem_val_expr is not None:
                expr = mem_val_expr.strip()
                try:
                    val = int(expr, 0)  # supports 0x.., decimal
                except ValueError:
                    val = last_value + 1
            else:
                val = last_value + 1
            last_value = val
            fields.append({"name": mem_name, "type": "INT",
                           "initial": str(val), "value": val})
        return {"name": name, "kind": "enum", "fields": fields,
                "base": base or "INT"}
    # Alias: TYPE x : SOMETYPE;
    alias = paren.rstrip(";").strip()
    return {"name": name, "kind": "alias", "fields": [], "base": alias}


# ---------------------------------------------------------------------------
# Type classification
# ---------------------------------------------------------------------------

def _base_type_name(typestr):
    """Strip STRING/WSTRING length, return upper base token."""
    t = typestr.strip()
    m = re.match(r"(?i)^(W?STRING)\s*(\(.*\)|\[.*\])?\s*$", t)
    if m:
        return m.group(1).upper()
    # POINTER TO X / REFERENCE TO X
    m = re.match(r"(?i)^(POINTER|REFERENCE)\s+TO\b", t)
    if m:
        return m.group(1).upper()
    return t.upper()


def classify_type(typestr):
    """Return a dict describing the type.

    kinds:
      scalar: {kind:'scalar', base}
      array:  {kind:'array', elem, dims:[(lo,hi),...]}  (lo/hi are raw strings)
      ref:    {kind:'ref', name}   (DUT/FB/enum/alias/unknown)
    """
    t = (typestr or "").strip()
    m = re.match(r"(?is)^ARRAY\s*\[(.*?)\]\s*OF\s+(.+)$", t)
    if m:
        dims_raw = m.group(1)
        elem = m.group(2).strip()
        dims = []
        for part in _split_dims(dims_raw):
            rng = part.split("..")
            if len(rng) == 2:
                dims.append((rng[0].strip(), rng[1].strip()))
            else:
                dims.append((part.strip(), part.strip()))
        return {"kind": "array", "elem": elem, "dims": dims}
    base = _base_type_name(t)
    if base in SCALAR_TYPES:
        return {"kind": "scalar", "base": base}
    return {"kind": "ref", "name": t}


def _split_dims(dims_raw):
    """Split multi-dim 'a..b, c..d' on top-level commas."""
    parts = []
    depth = 0
    cur = []
    for ch in dims_raw:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


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
            return _emit(path, info["base"], False, "pointer-or-reference")
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

import io
import os


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
