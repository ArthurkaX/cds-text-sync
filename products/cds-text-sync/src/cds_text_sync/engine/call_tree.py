# -*- coding: utf-8 -*-
"""
call_tree.py - Offline static call-graph builder for CODESYS projects.

Builds a JSON call tree from exported project data without connecting to the
CODESYS daemon.  Uses heuristic regex-based tokenisation consistent with the
existing variable_map.py parser style.
"""

from __future__ import annotations

import io
import json
import os
import re
import time

from variable_map import (
    detect_owner_kind,
    iter_st_files,
    parse_var_blocks,
    pou_name,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ST_IMPLEMENTATION_MARKER = "// --- implementation ---"
_CODESYS_IMPLEMENTATION_KEYWORD = "IMPLEMENTATION"

# Regex to find the opening of a top-level implementation section after the
# declaration block.  This mirrors what split_decl_impl() does but we need
# to work with the raw ST text ourselves.
_CALL_PATTERN = re.compile(
    r"""
    (\b[A-Za-z_]\w*)\s*\(          # identifier  followed by '('
    """,
    re.VERBOSE,
)

_METHOD_CALL_PATTERN = re.compile(
    r"""
    (\b[A-Za-z_]\w*)               # instance / THIS
    \s*\.\s*                        # dot
    (\b[A-Za-z_]\w*)               # method name
    \s*\(
    """,
    re.VERBOSE,
)

# Assignment operators that may appear before a function call.
_ASSIGN_OPS = re.compile(r"\b[A-Za-z_]\w*\s*:=")


def _split_decl_impl(text):
    """Split a .st blob into (declaration, implementation).

    Handles both the CODESYS ``IMPLEMENTATION`` keyword (used in
    ``project-view/*.st`` files exported by the IDE) and the daemon-era
    ``// --- implementation ---`` comment marker (used by
    ``variable_map.split_decl_impl``).

    Returns (decl, None) when no implementation marker is found.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Try CODESYS IMPLEMENTATION keyword first (most common for offline files).
    kw_marker = "\n" + _CODESYS_IMPLEMENTATION_KEYWORD + "\n"
    if kw_marker in normalized:
        decl, impl = normalized.split(kw_marker, 1)
        return decl, impl
    # Fallback: daemon comment marker.
    comment_marker = "\n" + ST_IMPLEMENTATION_MARKER + "\n"
    if comment_marker in normalized:
        decl, impl = normalized.split(comment_marker, 1)
        return decl, impl
    if ST_IMPLEMENTATION_MARKER in normalized:
        decl, impl = normalized.split(ST_IMPLEMENTATION_MARKER, 1)
        return decl, impl
    return normalized, None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_text(path: str) -> str:
    """Read a text file with lenient encoding."""
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def load_system_catalog(path: str | None = None) -> dict:
    """Load the system-function catalog.

    Returns a dict with keys ``functions`` and ``function_blocks``, each a
    ``set`` of uppercase names.
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "sys_funcs.json")
    with io.open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        "functions": {n.upper() for n in data.get("functions", [])},
        "function_blocks": {n.upper() for n in data.get("function_blocks", [])},
    }


def _blank_comments(text: str) -> str:
    """Replace comments and pragmas with spaces, preserving line numbers.

    This is a simplified version of variable_map._blank_noise that handles
    line comments (//), block comments (*...*), and pragmas ({...}).
    String literals are preserved so separators inside strings are safe.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        # String literal
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
        # Line comment //
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        # Block comment (* ... *)
        if c == "(" and nxt == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == ")"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
            continue
        # Pragmas { ... }
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


def _trim_string_literals(text: str) -> str:
    """Replace string-literal contents with spaces to reduce false matches."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                if d == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        out.append(" ")
                        i += 2
                        continue
                    out.append(c)
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _clean_for_calls(text: str) -> str:
    """Prepare implementation text for call extraction.

    1. Blank comments (preserving line numbers).
    2. Blank string-literal contents (preserving delimiters and line numbers).
    """
    return _trim_string_literals(_blank_comments(text))


def _line_number(text: str, offset: int) -> int:
    """Return 1-based line number for *offset* in *text*."""
    return text[:offset].count("\n") + 1


def _collect_local_symbols(decl: str) -> dict[str, str]:
    """Build a dict ``{variable_name: type_name}`` from VAR blocks."""
    symbols: dict[str, str] = {}
    for block in parse_var_blocks(decl):
        for member in block.get("members", []):
            name = member.get("name", "")
            typ = member.get("type", "")
            if name and typ:
                # Strip array dimensions like ARRAY[0..7] OF BOOL -> BOOL
                bare = re.sub(
                    r"\bARRAY\b.*?\bOF\b", "", typ, flags=re.IGNORECASE
                ).strip()
                if not bare:
                    bare = typ
                symbols[name] = bare
    return symbols


# ---------------------------------------------------------------------------
# Call extraction
# ---------------------------------------------------------------------------


def _extract_method_calls(
    clean_text: str,
    original_text: str,
) -> list[dict]:
    """Find ``instance.method(...)`` patterns."""
    calls: list[dict] = []
    for m in _METHOD_CALL_PATTERN.finditer(clean_text):
        instance = m.group(1)
        method = m.group(2)
        offset = m.start()
        calls.append(
            {
                "kind": "method_call",
                "instance": instance,
                "method": method,
                "callee_raw": f"{instance}.{method}",
                "offset": offset,
                "line": _line_number(original_text, offset),
            }
        )
    return calls


def _extract_function_calls(
    clean_text: str,
    original_text: str,
    method_call_offsets: set[int],
) -> list[dict]:
    """Find bare ``identifier(...)`` patterns, filtering out method calls and
    keywords."""
    keywords = {
        "IF",
        "FOR",
        "WHILE",
        "REPEAT",
        "CASE",
        "UNTIL",
        "ELSIF",
        "AND",
        "OR",
        "NOT",
        "XOR",
        "MOD",
        "DIV",
        "TRUE",
        "FALSE",
        "THIS",
        "SUPER",
        "VAR",
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_IN_OUT",
        "VAR_STAT",
        "VAR_GLOBAL",
        "END_VAR",
        "END_IF",
        "END_FOR",
        "END_WHILE",
        "END_REPEAT",
        "END_CASE",
        "THEN",
        "DO",
        "OF",
        "TO",
        "BY",
        "RETURN",
        "EXIT",
        "CONTINUE",
        "PROGRAM",
        "FUNCTION",
        "FUNCTION_BLOCK",
        "METHOD",
        "ACTION",
        "TYPE",
        "END_TYPE",
        "STRUCT",
        "END_STRUCT",
        "INTERFACE",
        "END_INTERFACE",
        "IMPLEMENTATION",
        "INT",
        "DINT",
        "UINT",
        "UDINT",
        "WORD",
        "DWORD",
        "BYTE",
        "BOOL",
        "REAL",
        "LREAL",
        "SINT",
        "USINT",
        "LINT",
        "ULINT",
        "TIME",
        "DATE",
        "STRING",
        "WSTRING",
        "CHAR",
        "ARRAY",
        "REFERENCE",
        "POINTER",
        "TRUE",
        "FALSE",
        "NULL",
        "SELF",
    }
    calls: list[dict] = []
    for m in _CALL_PATTERN.finditer(clean_text):
        offset = m.start()
        # Skip if offset is part of a method call (already handled)
        if offset in method_call_offsets:
            continue
        name = m.group(1).upper()
        if name in keywords:
            continue
        # Skip if this looks like it was already handled as a method call
        # (instance.method(...)).  Dot-prefixed calls are extracted by
        # _extract_method_calls, so we skip them here to avoid duplicates.
        preceding = clean_text[:offset].rstrip()
        if preceding and preceding[-1] == ".":
            continue

        calls.append(
            {
                "kind": "function_call",
                "callee_raw": m.group(1),
                "offset": offset,
                "line": _line_number(original_text, offset),
            }
        )
    return calls


def _merge_calls(func_calls, method_calls):
    """Merge and sort call candidates by offset."""
    combined = func_calls + method_calls
    combined.sort(key=lambda c: c["offset"])
    return combined


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_calls(
    calls: list[dict],
    local_symbols: dict[str, str],
    project_symbols: dict[str, dict],
    system_catalog: dict,
    owner_name: str,
    file_path: str,
    global_instance_types: dict[str, str] | None = None,
    gvl_members: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Resolve each raw call candidate against known symbols.

    Parameters
    ----------
    calls : list of dicts from extraction (with 'kind', 'callee_raw', 'line')
    local_symbols : variable_name -> type_name
    project_symbols : name -> {kind, guid} for project-defined POUs
    system_catalog : {functions, function_blocks} sets of uppercase names
    owner_name : name of the POU/FB/function containing this code
    file_path : relative path of the .st file
    global_instance_types : cross-file variable_name -> type_name map
    gvl_members : {gvl_name: {member_name: type_name}} for GVL files

    Returns
    -------
    list of resolved call records matching the output schema.
    """
    resolved: list[dict] = []
    for call in calls:
        kind = call["kind"]
        if kind == "method_call":
            instance = call["instance"]
            method = call["method"]

            # Case 1: GVL member call — GVL_Name.Instance(...)
            # This is calling an FB instance via a GVL path.
            if gvl_members and instance.lower() in gvl_members:
                gvl_name_lower = instance.lower()
                if method.lower() in gvl_members[gvl_name_lower]:
                    member_type = gvl_members[gvl_name_lower][method.lower()]
                    resolved.append(
                        {
                            "caller": owner_name,
                            "callee": member_type,
                            "callee_kind": _resolve_callee_kind(
                                member_type, project_symbols, system_catalog
                            ),
                            "call_kind": "function_call",
                            "instance": f"{instance}.{method}",
                            "instance_type": member_type,
                            "file": file_path,
                            "line": call["line"],
                        }
                    )
                    continue

            # Case 2: Known instance type (local or global)
            instance_type = local_symbols.get(instance, "")
            if not instance_type and global_instance_types:
                instance_type = global_instance_types.get(instance.lower(), "")

            if instance_type:
                callee = f"{instance_type}.{method}"
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee,
                        "callee_kind": _resolve_callee_kind(
                            callee, project_symbols, system_catalog
                        ),
                        "call_kind": "fb_method_call",
                        "instance": instance,
                        "instance_type": instance_type,
                        "file": file_path,
                        "line": call["line"],
                    }
                )
            else:
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": f"?{instance}.{method}",
                        "callee_kind": "unknown",
                        "call_kind": "unresolved_method",
                        "instance": instance,
                        "instance_type": "?",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
        elif kind == "function_call":
            callee_raw = call["callee_raw"]
            callee_upper = callee_raw.upper()

            # FB instance call — bare variable name that resolves to an FB type
            if global_instance_types and callee_raw.lower() in global_instance_types:
                inst_type = global_instance_types[callee_raw.lower()]
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": inst_type,
                        "callee_kind": _resolve_callee_kind(
                            inst_type, project_symbols, system_catalog
                        ),
                        "call_kind": "function_call",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
                continue

            if callee_raw in project_symbols:
                # Internal call
                sym = project_symbols[callee_raw]
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee_raw,
                        "callee_kind": sym.get("kind", "unknown"),
                        "call_kind": "function_call",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
            elif callee_upper in system_catalog.get("function_blocks", set()):
                # System FB (like TON, R_TRIG)
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee_raw,
                        "callee_kind": "system_function_block",
                        "call_kind": "system_call",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
            elif callee_upper in system_catalog.get("functions", set()):
                # System function (like ABS, SEL)
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee_raw,
                        "callee_kind": "system_function",
                        "call_kind": "system_call",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
            elif _is_implicit_type_conversion(callee_upper):
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee_raw,
                        "callee_kind": "system_function",
                        "call_kind": "system_call",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
            elif _is_standard_iec_operator(callee_upper):
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee_raw,
                        "callee_kind": "system_function",
                        "call_kind": "system_call",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
            else:
                # Unresolved
                resolved.append(
                    {
                        "caller": owner_name,
                        "callee": callee_raw,
                        "callee_kind": "unknown",
                        "call_kind": "unresolved",
                        "file": file_path,
                        "line": call["line"],
                    }
                )
    return resolved


def _resolve_callee_kind(
    callee: str, project_symbols: dict, system_catalog: dict
) -> str:
    """Determine the kind of a resolved callee name."""
    # Try direct match (for simple names)
    name = callee.split(".")[-1]
    if name in project_symbols:
        return project_symbols[name].get("kind", "unknown")
    if name.upper() in system_catalog.get("function_blocks", set()):
        return "system_function_block"
    if name.upper() in system_catalog.get("functions", set()):
        return "system_function"
    return "unknown"


def _is_implicit_type_conversion(name: str) -> bool:
    """Check if name looks like an implicit type conversion (e.g. INT_TO_BOOL)."""
    return bool(re.match(r"^[A-Z_]+_TO_[A-Z_]+$", name)) or name in {
        "TO_INT",
        "TO_DINT",
        "TO_REAL",
        "TO_LREAL",
        "TO_BOOL",
        "TO_STRING",
        "TO_WSTRING",
        "TO_TIME",
        "TO_DATE",
        "TO_BYTE",
        "TO_WORD",
        "TO_DWORD",
    }


def _is_standard_iec_operator(name: str) -> bool:
    """Check if name is a standard IEC operator that uses function-call syntax."""
    return name in {
        "MOVE",
        "SEL",
        "MUX",
        "GT",
        "GE",
        "EQ",
        "LE",
        "LT",
        "NE",
        "AND",
        "OR",
        "XOR",
        "NOT",
        "MOD",
        "DIV",
        "MUL",
        "ADD",
        "SUB",
        "SHL",
        "SHR",
        "ROL",
        "ROR",
        "ADR",
        "REF",
        "SIZEOF",
    }


# ---------------------------------------------------------------------------
# Snapshot-based symbol extraction
# ---------------------------------------------------------------------------


def _collect_project_symbols_from_snapshot(ide_model) -> dict[str, dict]:
    """Build a dict of all POU/FB/Function names from the IDE model.

    Returns {name: {"kind": str, "guid": str}}.
    """
    symbols: dict[str, dict] = {}
    if ide_model is None:
        return symbols
    for guid, node in ide_model.nodes.items():
        name = node.name
        if not name:
            continue
        # Infer kind from type GUID or code
        kind = _infer_pou_kind(node)
        if kind:
            symbols[name] = {"kind": kind, "guid": guid}
    return symbols


def _infer_pou_kind(node) -> str:
    """Try to determine the POU kind from a project node."""
    # Check code text first if available
    if node.code:
        decl, _ = _split_decl_impl(node.code)
        if decl:
            kind = detect_owner_kind(decl)
            if kind:
                return kind
    # Fallback: heuristic from type GUID
    # POU type GUID: 6f9dac99-8de1-4efc-8465-68ac443b7d08
    # We don't have a fine-grained GUID map, so just return "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Project-symbol extraction from ST files (when no snapshot)
# ---------------------------------------------------------------------------


def _collect_project_symbols_from_st_files(
    project_root: str,
) -> dict[str, dict]:
    """Scan .st files and extract POU/FB/function names from declarations.

    Returns {name: {"kind": str, "guid": ""}}.
    """
    symbols: dict[str, dict] = {}
    for st_path in iter_st_files(project_root):
        try:
            text = _read_text(st_path)
        except OSError:
            continue
        decl, _ = _split_decl_impl(text)
        if not decl:
            continue
        name = pou_name(decl, None)
        if name and name not in symbols:
            kind = detect_owner_kind(decl)
            symbols[name] = {"kind": kind or "unknown", "guid": ""}
        # Also check for methods (METHOD keyword in declaration)
        method_kind = _collect_methods(decl)
        if method_kind:
            symbols.update(method_kind)
    return symbols


def _collect_methods(decl: str) -> dict[str, dict]:
    """Extract METHOD definitions from a declaration block.

    Methods are defined as:

        METHOD MyMethod : INT
        VAR_INPUT
        ...
        END_VAR
        END_METHOD

    Returns {qualified_name: {"kind": "method", "guid": ""}}.
    """
    methods: dict[str, dict] = {}
    # Find the POU name first
    owner = pou_name(decl, None)
    blanked = _blank_comments(decl)
    # Look for METHOD blocks
    for m in re.finditer(
        r"(?im)^\s*METHOD\s+([A-Za-z_]\w*)",
        blanked,
    ):
        method_name = m.group(1)
        qualified = f"{owner}.{method_name}" if owner else method_name
        methods[qualified] = {"kind": "method", "guid": ""}
        # Also add a simple entry for the method name itself
        methods[method_name] = {"kind": "method", "guid": ""}
    return methods


# ---------------------------------------------------------------------------
# Global symbol tables (cross-file variable resolution)
# ---------------------------------------------------------------------------


def _build_global_instance_types(project_root: str) -> dict[str, str]:
    """Build a global ``{variable_name: type_name}`` map from ALL ``.st`` files.

    Keys are stored in *lowercase* for case-insensitive lookup because
    CODESYS is case-insensitive.  Includes variables from VAR / VAR_INPUT /
    VAR_OUTPUT / VAR_STAT blocks in every file, as well as GVL declarations.
    """
    types: dict[str, str] = {}
    for st_path in iter_st_files(project_root):
        try:
            text = _read_text(st_path)
        except OSError:
            continue
        decl, _ = _split_decl_impl(text)
        if not decl:
            continue
        local_types = _collect_local_symbols(decl)
        for name, typ in local_types.items():
            key = name.lower()
            # Only add if not already registered, or prefer non-empty types
            if key not in types or (typ and not types[key]):
                types[key] = typ
    return types


def _build_gvl_members(project_root: str) -> dict[str, dict[str, str]]:
    """Build a ``{gvl_name: {member_name: type_name}}`` map from GVL files.

    Keys are stored in *lowercase* for case-insensitive lookup because
    CODESYS is case-insensitive.  Scans all files whose declaration kind is
    ``gvl`` and collects the variable declarations inside them.
    """
    members: dict[str, dict[str, str]] = {}
    for st_path in iter_st_files(project_root):
        try:
            text = _read_text(st_path)
        except OSError:
            continue
        decl, _ = _split_decl_impl(text)
        if not decl:
            continue
        kind = detect_owner_kind(decl)
        if kind != "gvl":
            continue
        # GVL name isn't captured by pou_name() (which only handles
        # PROGRAM/FUNCTION_BLOCK/FUNCTION keywords).  Fall back to the
        # file stem (e.g. LogComponent.st -> LogComponent).
        gvl_name = pou_name(decl, None)
        if not gvl_name:
            gvl_name = os.path.splitext(os.path.basename(st_path))[0]
        local_types = _collect_local_symbols(decl)
        if local_types:
            members[gvl_name.lower()] = {k.lower(): v for k, v in local_types.items()}
    return members


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def _process_st_file(
    st_path: str,
    project_root: str,
    project_symbols: dict[str, dict],
    system_catalog: dict,
    global_instance_types: dict[str, str] | None = None,
    gvl_members: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Process a single .st file and return its resolved call records."""
    try:
        text = _read_text(st_path)
    except OSError:
        return []

    decl, impl = _split_decl_impl(text)
    if not impl:
        # No implementation section - nothing to analyze for calls
        return []

    # Owner info
    owner_name = pou_name(decl, os.path.basename(st_path))
    local_symbols = _collect_local_symbols(decl)

    # Relative file path
    rel_path = os.path.relpath(st_path, project_root)

    # Clean implementation text for call extraction
    clean_impl = _clean_for_calls(impl)

    # Extract calls
    method_calls = _extract_method_calls(clean_impl, impl)
    method_offsets = {c["offset"] for c in method_calls}
    func_calls = _extract_function_calls(clean_impl, impl, method_offsets)

    all_calls = _merge_calls(func_calls, method_calls)

    # Resolve
    resolved = _resolve_calls(
        all_calls,
        local_symbols,
        project_symbols,
        system_catalog,
        owner_name,
        rel_path,
        global_instance_types=global_instance_types,
        gvl_members=gvl_members,
    )

    return resolved


# ---------------------------------------------------------------------------
# Build call tree
# ---------------------------------------------------------------------------


def build_call_tree(
    project_root: str,
    snapshot_path: str | None = None,
    system_catalog_path: str | None = None,
) -> dict:
    """Build a call tree from a CODESYS project directory.

    Parameters
    ----------
    project_root :
        The project root directory (containing ``project-view/`` or the
        ``.st`` files).
    snapshot_path :
        Optional path to ``IDE.xml`` for richer symbol data (GUIDs).
    system_catalog_path :
        Optional path to a custom system-function catalog JSON.

    Returns
    -------
    dict matching the output schema (meta + calls + symbols).
    """
    system_catalog = load_system_catalog(system_catalog_path)

    # Build project symbols
    project_symbols: dict[str, dict] = {}

    if snapshot_path:
        from snapshot_reader import SnapshotReader  # local import avoids a cycle

        reader = SnapshotReader(
            snapshot_path,
            project_name=os.path.basename(project_root),
        )
        ide_model = reader.read()
        project_symbols = _collect_project_symbols_from_snapshot(ide_model)

    # Always enrich/collect from .st files (more precise parse)
    st_symbols = _collect_project_symbols_from_st_files(project_root)
    # Merge - st_symbols overrides/supplements snapshot data
    for name, info in st_symbols.items():
        if name not in project_symbols:
            project_symbols[name] = info
        elif info.get("guid") == "" and project_symbols[name].get("guid"):
            # Keep the snapshot guid if st_symbols doesn't have one
            pass

    # Build cross-file variable maps for instance resolution
    global_instance_types = _build_global_instance_types(project_root)
    gvl_members = _build_gvl_members(project_root)

    # Process each .st file
    all_calls: list[dict] = []
    source_count = 0
    for st_path in iter_st_files(project_root):
        calls = _process_st_file(
            st_path,
            project_root,
            project_symbols,
            system_catalog,
            global_instance_types=global_instance_types,
            gvl_members=gvl_members,
        )
        if calls:
            all_calls.extend(calls)
        source_count += 1

    # Build symbols section for output
    output_symbols: dict[str, dict] = {}
    for name, info in project_symbols.items():
        output_symbols[name] = {
            "kind": info.get("kind", "unknown"),
            "guid": info.get("guid", ""),
        }

    return {
        "meta": {
            "source_count": source_count,
            "system_catalog": system_catalog_path or "sys_funcs.json",
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "calls": all_calls,
        "symbols": output_symbols,
    }


def write_call_tree(data: dict, output_path: str) -> None:
    """Write the call tree report as formatted JSON."""
    with io.open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def run_call_tree(
    project_root: str,
    snapshot_path: str | None = None,
    output_path: str | None = None,
    system_catalog_path: str | None = None,
) -> dict:
    """Convenience entry point: build and optionally write the call tree.

    Returns the call tree dict.
    """
    data = build_call_tree(project_root, snapshot_path, system_catalog_path)
    if output_path:
        write_call_tree(data, output_path)
    return data
