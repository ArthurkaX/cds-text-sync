"""Generate compact, symbol-level documentation for a sync workspace.

Two deliberately separate sources feed the generator: the ``.st`` projection
of the project view (parsed for POU headers, doc comments and VAR blocks) and
the installed CODESYS LibDoc tree (located per library reference from the
Library Manager exports).  The output is markdown meant for LLM consumption -
one document per source, carrying only symbols, descriptions and interface
tables.  No raw ST source text is ever emitted.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cds_text_sync.engine.libdoc import find_libdoc, library_symbols
from cds_text_sync.engine.library_refs import explicit_library_references
from cds_text_sync.analyze_compat import build_compat_snapshot
from cds_text_sync.docs.model import (
    DocBundle,
    DocDiagnostic,
    DocRelation,
    DocSource,
    DocSymbol,
    json_line,
    stable_id,
)
from cds_text_sync.docs.behavior import extract_behavior
from cds_static_analyzer.execution import ExecutionGraph
from cds_static_analyzer.global_access import GlobalAccessIndex
from cds_static_analyzer.model import line_col_of
from cds_static_analyzer.st import kinds as K
from cts_shared.st.blanking import comment_spans
from cts_shared.st.declarations import member_comment, parse_dut, parse_var_blocks

DEFAULT_LIBRARY_PATH = Path(r"C:\ProgramData\CODESYS")

POU_HEADER_RE = re.compile(
    r"^[ \t]*(FUNCTION_BLOCK|FUNCTION|PROGRAM|INTERFACE|METHOD|PROPERTY|ACTION|TYPE)"
    r"[ \t]+([A-Za-z_]\w*)"
    r"(?:[ \t]*:[ \t]*([A-Za-z_][\w.]*))?",
    re.IGNORECASE | re.MULTILINE,
)
INTERFACE_COLUMNS = ("scope", "name", "type", "initial", "comment")


def _pou_sections(text, stem):
    """Split ``text`` into POU sections at every ``POU_HEADER_RE`` match.

    Each section spans from the start of its header match to the start of the
    next match (or end of text).  ``TYPE`` sections are re-parsed as DUTs so
    the kind becomes ``STRUCT``/``ENUM``/``ALIAS`` and the fields travel along
    under ``"dut"``.  Methods, properties and actions coming from
    ``Parent.Method.st`` files carry the qualified ``stem`` as their name.  A
    file with no header at all but a ``VAR_GLOBAL`` block becomes a single
    synthetic ``GVL`` section; a file with neither yields ``[]``.
    """
    matches = list(POU_HEADER_RE.finditer(text))
    if not matches:
        if re.search(r"^[ \t]*VAR_GLOBAL\b", text, re.IGNORECASE | re.MULTILINE):
            return [
                {"kind": "GVL", "name": stem, "start": 0, "text": text, "line": 1}
            ]
        return []
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_text = text[match.start():end]
        kind = match.group(1).upper()
        name = match.group(2)
        return_type = match.group(3) or ""
        section = {
            "kind": kind,
            "name": name,
            "start": match.start(),
            "text": section_text,
            "line": text[: match.start()].count("\n") + 1,
            "return_type": return_type,
        }
        if kind == "TYPE":
            try:
                dut = parse_dut(section_text)
            except Exception:
                dut = None
            if dut is not None:
                section["kind"] = str(dut.get("kind") or "").upper()
                section["name"] = dut.get("name") or name
                section["dut"] = dut
        elif kind in ("METHOD", "PROPERTY", "ACTION") and "." in stem:
            section["name"] = stem
        sections.append(section)
    return sections


def _merge_line_comments(text, spans):
    """Merge runs of consecutive ``//`` spans separated by one blank line.

    Two ``//`` spans whose gap is whitespace containing exactly one newline
    belong to one comment block; their contents are joined with ``\\n`` and
    the run collapses to a single span.  ``(* *)`` spans pass through
    untouched.  The result stays in source order.
    """
    merged = []
    index = 0
    total = len(spans)
    while index < total:
        start, end, content = spans[index]
        if text[start : start + 2] != "//":
            merged.append((start, end, content))
            index += 1
            continue
        contents = [content]
        last_end = end
        while index + 1 < total:
            next_start, next_end, next_content = spans[index + 1]
            if text[next_start : next_start + 2] != "//":
                break
            gap = text[last_end:next_start]
            if gap.strip() or gap.count("\n") != 1:
                break
            contents.append(next_content)
            last_end = next_end
            index += 1
        merged.append((start, last_end, "\n".join(contents)))
        index += 1
    return merged


def _clean_comment(content):
    """Normalise a raw comment body into readable description lines.

    Strips trailing whitespace, a leading ``*`` or ``//`` plus one optional
    space from each line, drops leading/trailing blank lines and dedents by
    the smallest common leading whitespace of the remaining lines.
    """
    lines = []
    for raw in str(content or "").split("\n"):
        line = raw.strip()
        if line.startswith("*"):
            line = line[1:]
        else:
            while line.startswith("/"):
                line = line[1:]
        if line.startswith(" "):
            line = line[1:]
        lines.append(line.rstrip())
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return ""
    indents = [len(line) - len(line.lstrip()) for line in lines if line]
    cut = min(indents) if indents else 0
    return "\n".join(line[cut:] if line else "" for line in lines)


def _section_description(text, section, spans):
    """Pick the doc comment of one section: the one following its header.

    A comment placed after the header line - separated from it by whitespace
    only, and still inside the section - wins.  Otherwise the last comment
    directly before the section start (whitespace gap again) is used.  No
    candidate means an empty description.
    """
    start = section["start"]
    header_line_end = text.find("\n", start)
    if header_line_end < 0:
        header_line_end = len(text)
    section_end = start + len(section["text"])
    winner = ""
    for span_start, _span_end, content in spans:
        if (
            span_start >= header_line_end
            and span_start < section_end
            and not text[header_line_end:span_start].strip()
        ):
            winner = content
            break
    if not winner:
        # Walk backwards over the whole run of comments that touch the header
        # with whitespace only in between.  A method file commonly carries a
        # `(* ... *)` doc block and a trailing `//` note above the header;
        # taking only the nearest span would keep the note and drop the doc.
        preceding = []
        boundary = start
        for span_start, span_end, content in reversed(spans):
            if span_end > boundary:
                continue
            if text[span_end:boundary].strip():
                break
            preceding.append(content)
            boundary = span_start
        winner = "\n".join(_clean_comment(part) for part in reversed(preceding))
    return _clean_comment(winner)


def _member_comment(section_text, line_no):
    """Return the trailing ``//`` comment of the member on ``line_no``.

    ``parse_var_blocks`` blanks comments internally, so the per-member
    comment is recovered from the original section text: the first ``//`` on
    that line that is not inside a single-quoted string literal.
    """
    try:
        line = section_text.split("\n")[int(line_no) - 1]
    except (IndexError, TypeError, ValueError):
        return ""
    in_string = False
    length = len(line)
    index = 0
    while index < length:
        char = line[index]
        if char == "'":
            in_string = not in_string
            index += 1
            continue
        if not in_string and char == "/" and line[index + 1 : index + 2] == "/":
            return line[index + 2 :].strip()
        index += 1
    return ""


def _section_interface(section):
    """Build the interface rows of one section.

    A ``dut`` section yields one ``FIELD`` row per DUT field; anything else
    is resolved through ``parse_var_blocks`` with the per-member trailing
    comment attached. FUNCTION/METHOD/PROPERTY sections with a captured
    return type get a leading ``Return`` row, matching the LibDoc-sourced
    library tables.
    """
    rows = []
    return_type = section.get("return_type")
    if return_type and section.get("kind") in ("FUNCTION", "METHOD", "PROPERTY"):
        rows.append(
            {
                "scope": "Return",
                "name": "",
                "type": return_type,
                "initial": "",
                "comment": "",
            }
        )
    dut = section.get("dut")
    if dut:
        for field in dut.get("fields") or []:
            name = str(field.get("name") or "")
            if not name:
                continue
            rows.append(
                {
                    "scope": "FIELD",
                    "name": name,
                    "type": str(field.get("type") or ""),
                    "initial": str(field.get("initial") or ""),
                    "comment": str(field.get("comment") or ""),
                }
            )
        return rows
    try:
        blocks = parse_var_blocks(section["text"])
    except Exception:
        return rows
    for block in blocks:
        for member in block.get("members") or []:
            name = str(member.get("name") or "")
            if not name:
                continue
            rows.append(
                {
                    "scope": str(member.get("scope") or ""),
                    "name": name,
                    "type": str(member.get("type") or ""),
                    "initial": str(member.get("initial") or ""),
                    "comment": member_comment(section["text"], name),
                }
            )
    return rows


_UNIT_KIND_NAMES = {
    K.PROGRAM: "PROGRAM",
    K.FUNCTION_BLOCK: "FUNCTION_BLOCK",
    K.FUNCTION: "FUNCTION",
    K.METHOD: "METHOD",
    K.ACTION: "ACTION",
    K.PROPERTY_GET: "PROPERTY",
    K.PROPERTY_SET: "PROPERTY",
    K.INTERFACE: "INTERFACE",
    K.GVL: "GVL",
    K.GVL_PERSISTENT: "GVL",
    K.STRUCT: "STRUCT",
    K.UNION: "UNION",
    K.ENUM: "ENUM",
    K.ALIAS: "ALIAS",
    K.UNKNOWN: "UNKNOWN",
}


def _unit_section(unit):
    """Adapt one analyzer Unit to the legacy interface renderer.

    Classification and source ownership come from ProjectSnapshot.  The
    header regex is used only to locate a description and a function return
    type inside the already-classified unit.
    """
    text = unit.declaration or unit.text or ""
    match = POU_HEADER_RE.search(text)
    kind = _UNIT_KIND_NAMES.get(unit.kind, str(unit.kind or "UNKNOWN").upper())
    start = match.start() if match else 0
    section_text = text[start:] if match else text
    section = {
        "kind": kind,
        "name": unit.qualified_name,
        "start": start,
        "text": section_text,
        "line": text[:start].count("\n") + 1,
        "return_type": match.group(3) if match else "",
    }
    if unit.kind in K.TYPE:
        try:
            section["dut"] = parse_dut(text)
        except Exception:
            section["dut"] = None
    return section


def _source_ref(source):
    return {"id": source.id, "line": 1, "end_line": None}


def _interface_table(rows):
    """Render interface rows as a fixed five-column markdown table."""
    if not rows:
        return ["_no interface_"]
    lines = ["| Scope | Name | Type | Initial | Comment |", "|---|---|---|---|---|"]
    for row in rows:
        cells = []
        for column in INTERFACE_COLUMNS:
            value = str(row.get(column) or "").replace("\n", " ").replace("|", "\\|")
            cells.append(value if value else " ")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _card_name(symbol_id, name):
    short_id = str(symbol_id or "symbol").rsplit("::", 1)[-1]
    return f"{_slug(name)}--{short_id}.md"


def _symbol_card(symbol, back_link="../index.md"):
    """Render a declaration-only card; implementation text is never included."""
    declaration = symbol.get("declaration") or {}
    lines = [
        f"# {symbol.get('kind') or 'SYMBOL'} {symbol.get('name') or ''}",
        "",
        f"- Source: `{symbol.get('path') or ''}` (line {symbol.get('line') or 1})",
        f"- Symbol ID: `{symbol.get('id') or ''}`",
        f"- Parse: `{(symbol.get('parse') or {}).get('status', 'unknown')}`",
        f"- Behavior: `{(symbol.get('behavior') or {}).get('status', 'not_extracted')}`",
        f"- Source hash: `{symbol.get('source_sha256') or '-'}`",
        f"- [Back to index]({back_link})",
        "",
        symbol.get("description") or "_undocumented_",
        "",
    ]
    if declaration:
        lines.extend(["## Declaration", ""])
        for key in ("attributes", "base_type", "extends", "signature"):
            value = declaration.get(key)
            if value not in (None, "", []):
                lines.append(f"- {key}: `{value}`")
        lines.append("")
    lines.extend(["## Interface", ""])
    lines.extend(_interface_table(symbol.get("interface") or []))
    lines.append("")
    own_members = symbol.get("own_members")
    inherited_members = symbol.get("inherited_members")
    if own_members is not None or inherited_members is not None:
        lines.extend(["## Members", ""])
        lines.append(f"- Own members: {len(own_members or [])}")
        lines.append(f"- Inherited members: {len(inherited_members or [])}")
        lines.append("")
    for title, key in (("Callers", "callers"), ("Callees", "callees"),
                       ("Tasks", "tasks"), ("Global dependencies", "globals")):
        values = symbol.get(key) or []
        if values:
            lines.extend([f"## {title}", ""])
            lines.extend(f"- `{value}`" for value in values)
            lines.append("")
    behavior = symbol.get("behavior") or {}
    facts = behavior.get("facts") or []
    if facts:
        lines.extend(["## Behavior facts", ""])
        if behavior.get("summary"):
            lines.extend([behavior["summary"], ""])
        for fact in facts:
            detail = ", ".join(
                f"{key}={value}"
                for key, value in sorted(fact.items())
                if key not in ("kind", "confidence", "source_span")
            )
            span = fact.get("source_span") or {}
            lines.append(
                f"- `{fact.get('kind')}` line {span.get('line', '?')} "
                f"({fact.get('confidence', 'unknown')})"
                + (f": {detail}" if detail else "")
            )
        lines.append("")
    warnings = (symbol.get("parse") or {}).get("warnings") or []
    if warnings:
        lines.extend(["## Parse warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    return lines


def _slug(value):
    """Filesystem-safe fragment: keep ``[A-Za-z0-9._-]``, underscore the rest."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value or ""))


def _missing_library_reason(library_root, ref):
    """Classify why a referenced LibDoc could not be loaded."""
    root = Path(library_root)
    libdoc_root = root / "LibDoc" if (root / "LibDoc").is_dir() else root
    if not libdoc_root.is_dir():
        return "library_root_unavailable"
    vendor = str(ref.get("vendor") or "").casefold()
    name = str(ref.get("name") or "").casefold()
    try:
        vendors = [item for item in libdoc_root.iterdir() if item.is_dir()]
    except OSError:
        return "library_root_unavailable"
    vendor_dirs = [item for item in vendors if not vendor or item.name.casefold() == vendor]
    library_dirs = [
        child for vendor_dir in vendor_dirs
        for child in vendor_dir.iterdir()
        if child.is_dir() and child.name.casefold() == name
    ]
    if not library_dirs:
        return "documentation_package_absent"
    requested = str(ref.get("version") or "*")
    if requested not in ("", "*"):
        if not any((library_dir / requested).is_dir() for library_dir in library_dirs):
            return "exact_version_missing"
    else:
        if not any(any(child.is_dir() for child in library_dir.iterdir()) for library_dir in library_dirs):
            return "wildcard_unresolved"
    return "documentation_package_absent"


def _generate_docs(workspace, library_path=None, output=None):
    """Write and return a documentation bundle for *workspace*.

    ``workspace`` may be the sync root or its ``project-view`` directory.
    ``library_path`` defaults to the standard CODESYS installation directory.
    """
    workspace = Path(workspace).resolve()
    if workspace.is_dir() and workspace.name.casefold() == "project-view":
        sync_root = workspace.parent
        project_view = workspace
    else:
        sync_root = workspace
        project_view = workspace / "project-view" if (workspace / "project-view").is_dir() else workspace
    library_root = Path(library_path or DEFAULT_LIBRARY_PATH).expanduser().resolve()
    output_root = Path(output).expanduser().resolve() if output else sync_root / ".cts-docs"

    snapshot = build_compat_snapshot(str(project_view))
    project_symbols = []
    doc_sources = []
    doc_diagnostics = []
    doc_model_symbols = []
    for unit in snapshot.units:
        if not unit.source_path.lower().endswith(".st"):
            continue
        text = unit.text or ""
        source = DocSource.from_text("project", unit.source_path, text)
        doc_sources.append(source)
        section = _unit_section(unit)
        spans = _merge_line_comments(text, comment_spans(text))
        description = _section_description(text, section, spans)
        interface = _section_interface(section)
        symbol_id = stable_id("project", section["kind"], unit.qualified_name)
        parse_status = "complete" if unit.kind != K.UNKNOWN else "failed"
        warnings = []
        if unit.kind == K.UNKNOWN:
            warnings.append("unit kind could not be classified")
            doc_diagnostics.append(DocDiagnostic(
                "unsupported_construct", "warning",
                f"could not classify Structured Text unit: {unit.source_path}",
                symbol_id=symbol_id,
                source_ref={"id": source.id, "line": 1},
            ))
        declaration = {}
        dut = section.get("dut")
        if dut:
            declaration = {
                "attributes": list(dut.get("attributes") or []),
                "attribute_values": dict(dut.get("attribute_values") or {}),
                "base_type": dut.get("base_type") or dut.get("base"),
                "extends": dut.get("extends"),
                "members": interface,
            }
            warnings.extend(dut.get("warnings") or [])
            if dut.get("warnings"):
                parse_status = "partial"
                doc_diagnostics.append(DocDiagnostic(
                    "parse_loss", "warning",
                    "one or more declaration members could not be parsed",
                    symbol_id=symbol_id,
                ))
            if section["kind"] == "ENUM" and not declaration["base_type"]:
                warnings = ["enum base_type could not be determined"]
                parse_status = "partial"
                doc_diagnostics.append(DocDiagnostic(
                    "parse_loss", "warning",
                    f"enum {unit.qualified_name} has no preserved base_type",
                    symbol_id=symbol_id,
                ))
        behavior_status, behavior_facts, behavior_summary = extract_behavior(unit)
        doc_model_symbols.append(DocSymbol(
            id=symbol_id,
            source="project",
            kind=section["kind"],
            name=unit.qualified_name,
            qualified_name=unit.qualified_name,
            path=unit.source_path,
            line=section["line"],
            description=description,
            interface=interface,
            source_ref=_source_ref(source),
            declaration=declaration,
            owner_id=unit.owner_id,
            source_spans=[span.to_dict() for span in unit.source_spans],
            parse_status=parse_status,
            parse_warnings=warnings,
            behavior_status=behavior_status,
            behavior_facts=behavior_facts,
            behavior_summary=behavior_summary,
        ))
        project_symbols.append({
            "id": symbol_id,
            "source": "project",
            "library": None,
            "version": None,
            "kind": section["kind"],
            "name": unit.qualified_name,
            "qualified_name": unit.qualified_name,
            "path": unit.source_path,
            "line": section["line"],
            "description": description,
            "interface": interface,
            "own_members": interface,
            "inherited_members": [],
            "source_ref": _source_ref(source),
            "declaration": declaration,
            "owner_id": unit.owner_id,
            "source_spans": [span.to_dict() for span in unit.source_spans],
            "parse": {"status": parse_status, "warnings": warnings},
            "behavior": {
                "status": behavior_status,
                "facts": behavior_facts,
                "summary": behavior_summary,
            },
        })

        project_path = Path(unit.source_path)
        if not project_path.is_absolute():
            project_path = project_view / project_path
        if not project_path.is_file():
            doc_diagnostics.append(DocDiagnostic(
                "source_error", "error",
                f"project source path does not exist: {unit.source_path}",
                symbol_id=symbol_id,
                source_ref={"id": source.id, "line": 1},
            ))

    for error in snapshot.source_errors:
        doc_diagnostics.append(DocDiagnostic(
            "source_error", "error", error.message,
            source_ref={"path": error.location.path, "line": error.location.line},
        ))

    project_ids = {
        symbol.qualified_name.casefold(): symbol.id for symbol in doc_model_symbols
    }
    doc_relations = []
    for symbol in doc_model_symbols:
        if symbol.source != "project":
            continue
        extends = (symbol.declaration or {}).get("extends")
        if not extends:
            continue
        target = project_ids.get(str(extends).casefold(), f"unresolved::type:{extends}")
        doc_relations.append(DocRelation(
            "extends", symbol.id, target,
            resolution="exact" if target in project_ids.values() else "unresolved",
            confidence="high" if target in project_ids.values() else "low",
        ))
    unresolved_call_records = []
    try:
        execution = ExecutionGraph(snapshot)
    except Exception as exc:
        execution = None
        doc_diagnostics.append(DocDiagnostic(
            "execution_graph_error", "warning", f"could not build execution graph: {exc}"
        ))
    if execution is not None:
        units_by_name = {
            unit.qualified_name.casefold(): unit for unit in snapshot.units
        }
        for caller, callee, offsets in execution.call_edges():
            caller_id = project_ids.get(caller)
            if not caller_id:
                continue
            callee_id = project_ids.get(callee, f"unresolved::call:{callee}")
            site = None
            if offsets:
                unit = units_by_name.get(caller)
                if unit is not None:
                    line, column = line_col_of(unit.text, offsets[0])
                    site = {"line": line, "column": column}
                    source_id = next(
                        (source.id for source in doc_sources if source.path == unit.source_path),
                        None,
                    )
                    if source_id:
                        site["source_id"] = source_id
            doc_relations.append(DocRelation("calls", caller_id, callee_id, site=site))
        for caller, name, offsets in execution.unresolved_call_sites():
            caller_id = project_ids.get(caller)
            if not caller_id:
                continue
            site = None
            if offsets:
                unit = units_by_name.get(caller)
                if unit is not None:
                    line, column = line_col_of(unit.text, offsets[0])
                    site = {"line": line, "column": column}
                    source_id = next(
                        (source.id for source in doc_sources if source.path == unit.source_path),
                        None,
                    )
                    if source_id:
                        site["source_id"] = source_id
            doc_relations.append(DocRelation(
                "calls", caller_id, f"unresolved::call:{name}", site=site,
                resolution="unresolved", confidence="low",
            ))
            unresolved_call_records.append((caller_id, name))
        for unit_name, tasks in sorted(execution._tasks_by_unit.items()):
            target_id = project_ids.get(unit_name)
            if not target_id:
                continue
            for task in sorted(tasks):
                doc_relations.append(DocRelation(
                    "reachable_from_task", f"external::task:{task}", target_id,
                ))

    source_ids_by_path = {source.path: source.id for source in doc_sources}
    try:
        global_access = GlobalAccessIndex(snapshot)
        for access in global_access.all_accesses():
            caller_id = project_ids.get(access.unit.qualified_name.casefold())
            if not caller_id:
                continue
            source_id = source_ids_by_path.get(access.unit.source_path)
            site = {"line": access.line, "column": access.column}
            if source_id:
                site["source_id"] = source_id
            if execution is not None:
                tasks = sorted(execution.tasks_for(access.unit.qualified_name))
                if tasks:
                    site["tasks"] = tasks
            relation_kind = "writes_global" if access.write else "reads_global"
            target = f"external::global:{access.global_unit.qualified_name}.{access.member['name']}"
            doc_relations.append(DocRelation(
                relation_kind,
                caller_id,
                target,
                site=site,
                resolution="exact",
                confidence=access.confidence,
            ))
    except Exception as exc:
        doc_diagnostics.append(DocDiagnostic(
            "global_access_error", "warning", f"could not build global access index: {exc}"
        ))

    references, gap = explicit_library_references(project_view)
    documented = []
    missing = []
    for ref in references:
        libdoc = find_libdoc(library_root, ref["name"], ref["vendor"], ref["version"])
        requested_version = str(ref.get("version") or "*")
        if libdoc is not None and requested_version not in ("", "*") and str(libdoc.get("version")) != requested_version:
            # find_libdoc intentionally supports wildcard/fallback lookup for
            # other consumers. Documentation must not present another version
            # as the exact contract used by the project.
            libdoc = None
        if libdoc is None:
            missing_ref = dict(ref)
            missing_ref["reason"] = _missing_library_reason(library_root, ref)
            missing.append(missing_ref)
            doc_diagnostics.append(DocDiagnostic(
                "missing_external_docs", "warning",
                f"LibDoc unavailable for {ref['name']} {ref.get('version') or '*'}: {missing_ref['reason']}",
            ))
            continue
        documented.append({"ref": ref, "libdoc": libdoc, "symbols": library_symbols(libdoc)})

    library_rows = []
    library_ids = {}
    library_candidates = {}
    for entry in documented:
        libdoc = entry["libdoc"]
        for sym in entry["symbols"]:
            ref = entry["ref"]
            location = str(sym.get("location") or "")
            source_ref = None
            if location:
                html_path = Path(libdoc["path"]) / location
                try:
                    html_text = html_path.read_text(encoding="utf-8-sig", errors="replace")
                except OSError:
                    html_text = ""
                if html_text:
                    source = DocSource.from_text(
                        "library",
                        f"{ref['vendor']}/{ref['name']}/{libdoc['version']}/{location}",
                        html_text,
                    )
                    doc_sources.append(source)
                    source_ref = _source_ref(source)
            symbol_id = stable_id(
                "library",
                sym.get("kind") or "POU",
                sym.get("name"),
                namespace=ref.get("namespace") or ref.get("name"),
                version=libdoc.get("version"),
            )
            library_key = (
                str(ref.get("name") or "").casefold(),
                str(libdoc.get("version") or "").casefold(),
                str(sym.get("name") or "").casefold(),
                str(sym.get("kind") or "POU").casefold(),
            )
            library_ids[library_key] = symbol_id
            symbol_name = str(sym.get("name") or "").casefold()
            candidate_keys = {symbol_name}
            # LibDoc pages usually expose the symbol without its namespace,
            # while ST calls may use either ``Namespace.Symbol`` or the
            # library name as qualifier.
            for namespace in (ref.get("namespace"), ref.get("name")):
                qualifier = str(namespace or "").strip().casefold()
                if qualifier:
                    candidate_keys.add(qualifier + "." + symbol_name)
            for candidate_key in candidate_keys:
                library_candidates.setdefault(candidate_key, []).append(symbol_id)
            interface = [
                {c: str(row.get(c, "")) for c in INTERFACE_COLUMNS}
                for row in sym.get("interface") or []
            ]
            doc_model_symbols.append(DocSymbol(
                id=symbol_id,
                source="library",
                kind=sym.get("kind") or "POU",
                name=sym.get("name") or "",
                qualified_name=sym.get("name") or "",
                path=location,
                description=str(sym.get("description") or ""),
                interface=interface,
                source_ref=source_ref,
                declaration={"signature": str(sym.get("signature") or "")},
                library=ref.get("name"),
                version=libdoc.get("version"),
                vendor=ref.get("vendor"),
                namespace=ref.get("namespace"),
            ))
            library_rows.append(
                {
                    "id": symbol_id,
                    "source": "library",
                    "library": ref["name"],
                    "version": libdoc["version"],
                    "kind": sym["kind"],
                    "name": sym["name"],
                    "qualified_name": sym["name"],
                    "path": sym.get("location", ""),
                    "line": None,
                    "description": sym["description"],
                    "interface": interface,
                    "own_members": interface,
                    "inherited_members": [],
                    "source_ref": source_ref,
                    "declaration": {"signature": str(sym.get("signature") or "")},
                    "parse": {"status": "complete", "warnings": []},
                    "behavior": {"status": "not_extracted"},
                }
            )

    # Materialize inherited declaration members after all project symbols are
    # known. Unresolved/cyclic inheritance stays represented by its relation.
    project_rows_by_name = {
        str(row.get("name") or "").casefold(): row
        for row in project_symbols
    }
    inherited_cache = {}

    def inherited_for(row, visiting=()):
        row_id = row.get("id")
        if row_id in inherited_cache:
            return inherited_cache[row_id]
        if row_id in visiting:
            return []
        base_name = str((row.get("declaration") or {}).get("extends") or "").casefold()
        base = project_rows_by_name.get(base_name)
        if base is None:
            inherited_cache[row_id] = []
            return []
        members = [dict(member) for member in (base.get("own_members") or [])]
        members.extend(inherited_for(base, visiting + (row_id,)))
        for member in members:
            member.setdefault("inherited_from", base.get("name"))
        inherited_cache[row_id] = members
        return members

    for row in project_symbols:
        row["inherited_members"] = inherited_for(row)

    # Build reverse navigation for cards from the canonical one-way relations.
    model_by_id = {symbol.id: symbol for symbol in doc_model_symbols}
    card_meta = {symbol.id: {"callers": [], "callees": [], "tasks": [], "globals": []}
                 for symbol in doc_model_symbols}
    for relation in doc_relations:
        if relation.kind == "calls":
            if relation.from_id in card_meta:
                card_meta[relation.from_id]["callees"].append(relation.to_id)
            if relation.to_id in card_meta:
                card_meta[relation.to_id]["callers"].append(relation.from_id)
        elif relation.kind in ("reads_global", "writes_global") and relation.from_id in card_meta:
            card_meta[relation.from_id]["globals"].append(
                f"{relation.kind}:{relation.to_id}"
            )
        elif relation.kind == "reachable_from_task" and relation.to_id in card_meta:
            card_meta[relation.to_id]["tasks"].append(
                relation.from_id.removeprefix("external::task:")
            )
    for values in card_meta.values():
        for key in values:
            values[key] = sorted(set(values[key]))

    cards_by_id = {}
    for symbol in doc_model_symbols:
        if symbol.source != "project":
            continue
        card = f"project/{_card_name(symbol.id, symbol.name)}"
        symbol.card = card
        cards_by_id[symbol.id] = card
    for row in project_symbols:
        row["card"] = cards_by_id.get(row.get("id"))
        row.update(card_meta.get(row.get("id"), {}))
        source = next(
            (item for item in doc_sources
             if item.id == (row.get("source_ref") or {}).get("id")),
            None,
        )
        row["source_sha256"] = source.sha256 if source else None
    for row in library_rows:
        library_slug = f"{_slug(row.get('library'))}-{_slug(row.get('version'))}"
        row["card"] = f"libraries/{library_slug}/{_card_name(row.get('id'), row.get('name'))}"
        model = model_by_id.get(row.get("id"))
        if model is not None:
            model.card = row["card"]

    for caller_id, name in unresolved_call_records:
        candidates = sorted(set(library_candidates.get(name.casefold(), [])))
        if not candidates and "." in name:
            # A qualified call may use a namespace spelling not present in the
            # manager metadata; use the final symbol only if globally unique.
            candidates = sorted(set(library_candidates.get(name.rsplit(".", 1)[-1].casefold(), [])))
        if len(candidates) == 1:
            for relation in doc_relations:
                if relation.from_id == caller_id and relation.to_id == f"unresolved::call:{name}":
                    relation.to_id = candidates[0]
                    relation.resolution = "exact"
                    relation.confidence = "high"
            continue
        for relation in doc_relations:
            if relation.from_id == caller_id and relation.to_id == f"unresolved::call:{name}":
                relation.candidates = candidates
                relation.confidence = "low" if not candidates else "medium"
        doc_diagnostics.append(DocDiagnostic(
            "unresolved_relation", "warning",
            f"could not resolve call {name!r}"
            + (f"; candidates: {', '.join(candidates)}" if candidates else ""),
            symbol_id=caller_id,
        ))

    # The cards were initially emitted before relations were known.  Rewrite
    # project cards now that their navigation metadata is complete.
    (output_root / "project").mkdir(parents=True, exist_ok=True)
    for symbol in project_symbols:
        card = symbol.get("card")
        if card:
            (output_root / card).write_text(
                "\n".join(_symbol_card(symbol, "../index.md")) + "\n",
                encoding="utf-8",
            )

    libdoc_root = None
    if (library_root / "LibDoc").is_dir():
        libdoc_root = library_root / "LibDoc"
    elif library_root.name.casefold() == "libdoc":
        libdoc_root = library_root
    not_referenced = {}
    if libdoc_root is not None:
        try:
            referenced_names = {ref["name"].casefold() for ref in references}
            for vendor_dir in sorted(libdoc_root.iterdir()):
                if not vendor_dir.is_dir():
                    continue
                for library_dir in sorted(vendor_dir.iterdir()):
                    if not library_dir.is_dir():
                        continue
                    if library_dir.name.casefold() in referenced_names:
                        continue
                    versions = {child.name for child in library_dir.iterdir() if child.is_dir()}
                    # The same library name can live under more than one vendor
                    # directory; union the versions instead of keeping whichever
                    # vendor happened to be walked first.
                    not_referenced.setdefault(library_dir.name, set()).update(versions)
        except OSError:
            not_referenced = {}
    not_referenced = {name: sorted(versions) for name, versions in not_referenced.items()}

    bundle = DocBundle(
        sources=doc_sources,
        symbols=doc_model_symbols,
        relations=doc_relations,
        diagnostics=doc_diagnostics,
    )
    validation_diagnostics = bundle.validate()
    all_diagnostics = [diagnostic.to_dict() for diagnostic in validation_diagnostics]
    input_fingerprint = hashlib.sha256(
        "\n".join(
            f"{source.path}\0{source.sha256}" for source in sorted(doc_sources, key=lambda item: item.path)
        ).encode("utf-8")
    ).hexdigest()
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Keep manifest counts derived from the exact record collections that are
    # serialized below.  This prevents a future renderer-side filter from
    # silently making the manifest disagree with JSONL.
    artifact_symbols = project_symbols + library_rows
    artifact_diagnostics = all_diagnostics
    artifact_relations = doc_relations
    manifest = {
        "format": "cts-docs/v3",
        "schema_version": "3",
        "generator_version": "docgen-project-snapshot-2",
        "generated_at": generated_at,
        "project_view": str(project_view),
        "libraries": str(library_root),
        "library_path_exists": library_root.is_dir(),
        "input_fingerprint": input_fingerprint,
        "counts": {
            "project_pous": sum(item.get("source") == "project" for item in artifact_symbols),
            "library_pous": sum(item.get("source") == "library" for item in artifact_symbols),
            "libraries_referenced": len(references),
            "libraries_documented": len(documented),
            "libraries_missing": len(missing),
            "libraries_not_referenced": len(not_referenced),
            "diagnostics": len(artifact_diagnostics),
            "diagnostic_errors": sum(item["severity"] == "error" for item in artifact_diagnostics),
            "diagnostic_warnings": sum(item["severity"] == "warning" for item in artifact_diagnostics),
            "relations": len(artifact_relations),
        },
        "libraries_missing": [
            {
                "name": ref["name"],
                "version": ref["version"],
                "vendor": ref["vendor"],
                "placeholder": ref["placeholder"],
                "reason": ref.get("reason", "documentation_package_absent"),
            }
            for ref in missing
        ],
        "gaps": [gap] if gap else [],
        "diagnostics": "diagnostics.jsonl",
        "sources": "sources.jsonl",
        "relations": "relations.jsonl",
    }

    output_root.mkdir(parents=True, exist_ok=True)
    try:
        (output_root / "bundle.md").unlink(missing_ok=True)
    except OSError:
        pass

    project_dir = output_root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    for symbol in project_symbols:
        card = symbol.get("card")
        if not card:
            continue
        (output_root / card).write_text(
            "\n".join(_symbol_card(symbol, "../index.md")) + "\n", encoding="utf-8"
        )

    lines = ["# Project POUs", "", f"Generated from `{project_view}`.", ""]
    if not project_symbols:
        lines.extend(["_No POUs found under the project view._", ""])
    else:
        lines.extend(["| Kind | Name | Source | Card |", "|---|---|---|---|"])
        for symbol in project_symbols:
            card = symbol.get("card") or ""
            lines.append(
                f"| {symbol['kind']} | {symbol['name']} | `{symbol['path']}` | "
                f"[{card.rsplit('/', 1)[-1]}]({card}) |"
            )
    (output_root / "project.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    libraries_dir = output_root / "libraries"
    libraries_dir.mkdir(parents=True, exist_ok=True)
    for row in library_rows:
        card_path = output_root / row["card"]
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text(
            "\n".join(_symbol_card(row, "../../index.md")) + "\n",
            encoding="utf-8",
        )
    for entry in documented:
        ref = entry["ref"]
        libdoc = entry["libdoc"]
        file_name = f"{_slug(ref['name'])}-{_slug(libdoc['version'])}.md"
        lines = [
            f"# {ref['name']} {libdoc['version']}",
            "",
            f"- Vendor: `{ref['vendor'] or 'unknown'}`",
            f"- Namespace: `{ref['namespace'] or '-'}`",
            f"- Placeholder: `{ref['placeholder'] or '-'}`",
            f"- Kind: `{'system library' if ref['system'] else 'application library'}`",
            f"- LibDoc: `{libdoc['path']}`",
            "",
        ]
        if not entry["symbols"]:
            lines.extend(["_No documented POUs in this LibDoc tree._", ""])
        for sym in entry["symbols"]:
            rows = [
                {c: str(row.get(c, "")) for c in INTERFACE_COLUMNS}
                for row in sym.get("interface") or []
            ]
            lines.extend(
                [
                    f"## {sym['kind'] or 'POU'} {sym['name']}",
                    "",
                ]
            )
            signature = str(sym.get("signature") or "")
            if signature:
                lines.extend(["```iecst", signature, "```", ""])
            lines.extend([str(sym.get("description") or "") or "_undocumented_", ""])
            lines.extend(_interface_table(rows))
            lines.append("")
        (libraries_dir / file_name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = [
        "# CODESYS documentation index",
        "",
        "Generation timestamp: see `manifest.json` (`generated_at`).",
        "",
        f"- Project view: `{project_view}`",
        f"- Library root: `{library_root}`",
        "",
        "## Machine-readable bundle",
        "",
        "- [Project symbol index](project.md)",
        "- [Project symbol cards](project/)",
        "- [Symbols](symbols.jsonl)",
        "- [Sources](sources.jsonl)",
        "- [Relations](relations.jsonl)",
        "- [Diagnostics](diagnostics.jsonl)",
        "- [Manifest](manifest.json)",
        "",
        "## Project symbols",
        "",
    ]
    if project_symbols:
        for symbol in project_symbols:
            card = symbol.get("card") or "project.md"
            lines.append(
                f"- [{symbol['kind']} {symbol['name']}]({card}) — `{symbol['path']}`"
            )
    else:
        lines.append("_None._")
    lines.extend(
        [
        "",
        "## Counts",
        "",
        f"- Project POUs: {manifest['counts']['project_pous']}",
        f"- Libraries referenced: {manifest['counts']['libraries_referenced']}",
        f"- Libraries documented: {manifest['counts']['libraries_documented']}",
        f"- Library POUs: {manifest['counts']['library_pous']}",
        "",
        "## Libraries",
        "",
        "| Library | Version | Vendor | Namespace | System | POUs | Document |",
        "|---|---|---|---|---|---:|---|",
        ]
    )
    for entry in documented:
        ref = entry["ref"]
        file_name = f"{_slug(ref['name'])}-{_slug(entry['libdoc']['version'])}.md"
        lines.append(
            f"| {ref['name']} | {entry['libdoc']['version']} | {ref['vendor'] or 'unknown'} "
            f"| {ref['namespace'] or '-'} | {'yes' if ref['system'] else 'no'} "
            f"| {len(entry['symbols'])} | [libraries/{file_name}](libraries/{file_name}) |"
        )
    lines.extend(
        [
            "",
            "## Missing LibDoc",
            "",
            "These libraries are referenced by the project but have no documentation installed on",
            "this machine. Install the library documentation or ask the user to resolve the",
            "reference — the generator does not substitute another version.",
            "",
            "| Library | Version | Vendor | Placeholder | Reason |",
            "|---|---|---|---|---|",
        ]
    )
    if missing:
        for ref in missing:
            lines.append(
                f"| {ref['name']} | {ref['version']} | {ref['vendor'] or '-'} "
                f"| {ref['placeholder'] or '-'} | {ref.get('reason', '-')} |"
            )
    else:
        lines.append("_None._")
    lines.extend(
        [
            "",
            "## Not referenced",
            "",
            "See [libraries/not-referenced.md](libraries/not-referenced.md) for installed",
            "libraries that are not referenced by this project.",
        ]
    )
    if gap:
        lines.extend(["", "## Gaps", "", f"- {gap}"])
    (output_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    not_referenced_lines = [
        "# Installed libraries not referenced by the project", "",
        "These libraries were found in the configured LibDoc root but were not exported.", "",
        "| Library | Versions |", "|---|---|",
    ]
    if not_referenced:
        for name, versions in not_referenced.items():
            not_referenced_lines.append(f"| {name} | {', '.join(versions)} |")
    else:
        not_referenced_lines.append("_None._")
    (libraries_dir / "not-referenced.md").write_text(
        "\n".join(not_referenced_lines) + "\n", encoding="utf-8"
    )

    with (output_root / "symbols.jsonl").open("w", encoding="utf-8") as stream:
        for row in artifact_symbols:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    with (output_root / "sources.jsonl").open("w", encoding="utf-8") as stream:
        for source in sorted(doc_sources, key=lambda item: item.path):
            stream.write(json_line(source.to_dict()) + "\n")

    with (output_root / "diagnostics.jsonl").open("w", encoding="utf-8") as stream:
        for diagnostic in all_diagnostics:
            stream.write(json_line(diagnostic) + "\n")

    with (output_root / "relations.jsonl").open("w", encoding="utf-8") as stream:
        for relation in sorted(
            doc_relations,
            key=lambda item: (item.kind, item.from_id, item.to_id),
        ):
            stream.write(json_line(relation.to_dict()) + "\n")

    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return {"ok": True, "output": str(output_root), "manifest": manifest}


def validate_bundle(bundle_or_output):
    """Validate an in-memory ``DocBundle`` or an emitted bundle directory."""
    if isinstance(bundle_or_output, DocBundle):
        return [diagnostic.to_dict() for diagnostic in bundle_or_output.validate()]
    root = Path(bundle_or_output).expanduser().resolve()
    try:
        def read_jsonl(name):
            path = root / name
            with path.open(encoding="utf-8") as stream:
                return [json.loads(line) for line in stream if line.strip()]

        sources = [DocSource(**row) for row in read_jsonl("sources.jsonl")]
        symbols = [DocSymbol(
            id=row["id"], source=row.get("source", ""), kind=row.get("kind", ""),
            name=row.get("name", ""), qualified_name=row.get("qualified_name", row.get("name", "")),
            path=row.get("path", ""), source_ref=row.get("source_ref"),
        ) for row in read_jsonl("symbols.jsonl")]
        relations = [DocRelation(
            row["kind"], row["from"], row["to"], row.get("site"),
            row.get("resolution", "exact"), row.get("confidence", "high"),
            row.get("candidates") or [],
        ) for row in read_jsonl("relations.jsonl")]
        diagnostics = [DocDiagnostic(
            row["code"], row["severity"], row["message"],
            row.get("symbol_id"), row.get("source_ref"),
        ) for row in read_jsonl("diagnostics.jsonl")]
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return [{"code": "bundle_unreadable", "severity": "error", "message": str(exc)}]
    return [diagnostic.to_dict() for diagnostic in DocBundle(
        sources=sources, symbols=symbols, relations=relations, diagnostics=diagnostics,
    ).validate()]


def generate_docs(workspace, library_path=None, output=None):
    """Build a bundle in staging and publish it as one output directory."""
    _project_view, output_root = _resolve_doc_paths(workspace, output)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(
        prefix=f".{output_root.name}.staging-",
        dir=str(output_root.parent),
    ))
    backup = None
    try:
        result = _generate_docs(workspace, library_path=library_path, output=staging)
        if output_root.exists():
            backup = output_root.parent / (
                f".{output_root.name}.previous-{uuid.uuid4().hex[:12]}"
            )
            output_root.replace(backup)
        try:
            staging.replace(output_root)
        except PermissionError:
            # Some Windows mounts allow creating files/directories but deny
            # directory rename (even when the destination does not exist).
            # The bundle has already been fully generated and validated in
            # staging, so copy it as a compatibility fallback.  Keep the
            # replace path as the normal atomic publication mechanism.
            shutil.copytree(staging, output_root, dirs_exist_ok=True)
        except Exception:
            if backup is not None and not output_root.exists():
                backup.replace(output_root)
            raise
        staging = None
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        result["output"] = str(output_root)
        return result
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _resolve_doc_paths(workspace, output=None):
    workspace = Path(workspace).resolve()
    if workspace.is_dir() and workspace.name.casefold() == "project-view":
        sync_root = workspace.parent
        project_view = workspace
    else:
        sync_root = workspace
        project_view = workspace / "project-view" if (workspace / "project-view").is_dir() else workspace
    output_root = Path(output).expanduser().resolve() if output else sync_root / ".cts-docs"
    return project_view, output_root


def check_docs(workspace, output=None):
    """Check whether the generated project sources still match the bundle.

    Return codes are intentionally stable for scripting: 0=fresh,
    1=stale, 2=unreadable or malformed bundle.
    """
    project_view, output_root = _resolve_doc_paths(workspace, output)
    manifest_path = output_root / "manifest.json"
    sources_path = output_root / "sources.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_rows = [
            json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    except (OSError, ValueError, TypeError) as exc:
        return {"state": "unreadable", "exit_code": 2, "message": str(exc)}

    snapshot = build_compat_snapshot(str(project_view))
    current = []
    for unit in snapshot.units:
        if unit.source_path.lower().endswith(".st"):
            current.append(DocSource.from_text("project", unit.source_path, unit.text or ""))
    library_root = Path(manifest.get("libraries") or DEFAULT_LIBRARY_PATH).expanduser().resolve()
    references, _gap = explicit_library_references(project_view)
    for ref in references:
        libdoc = find_libdoc(library_root, ref["name"], ref["vendor"], ref["version"])
        requested_version = str(ref.get("version") or "*")
        if (
            libdoc is not None
            and requested_version not in ("", "*")
            and str(libdoc.get("version")) != requested_version
        ):
            # Keep freshness semantics identical to generation: an exact
            # project reference must not be satisfied by another LibDoc
            # version returned by the lookup fallback.
            libdoc = None
        if libdoc is None:
            continue
        for symbol in library_symbols(libdoc):
            location = str(symbol.get("location") or "")
            if not location:
                continue
            try:
                html_text = (Path(libdoc["path"]) / location).read_text(
                    encoding="utf-8-sig", errors="replace"
                )
            except OSError:
                continue
            current.append(DocSource.from_text(
                "library",
                f"{ref['vendor']}/{ref['name']}/{libdoc['version']}/{location}",
                html_text,
            ))
    current.sort(key=lambda item: item.path)
    fingerprint = hashlib.sha256(
        "\n".join(f"{item.path}\0{item.sha256}" for item in current).encode("utf-8")
    ).hexdigest()
    recorded = sorted(
        ((str(row.get("path") or ""), str(row.get("sha256") or "")) for row in source_rows),
        key=lambda item: item[0],
    )
    actual = [(item.path, item.sha256) for item in current]
    fresh = manifest.get("input_fingerprint") == fingerprint and recorded == actual
    return {
        "state": "fresh" if fresh else "stale",
        "exit_code": 0 if fresh else 1,
        "output": str(output_root),
        "expected_fingerprint": manifest.get("input_fingerprint"),
        "actual_fingerprint": fingerprint,
        "source_count": len(current),
    }


__all__ = ["DEFAULT_LIBRARY_PATH", "check_docs", "generate_docs"]
