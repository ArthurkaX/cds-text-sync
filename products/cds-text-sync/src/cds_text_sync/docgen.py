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
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from cds_text_sync.engine.libdoc import find_libdoc, library_symbols
from cds_text_sync.engine.library_refs import explicit_library_references
from cts_shared.st.blanking import comment_spans
from cts_shared.st.declarations import parse_dut, parse_var_blocks

DEFAULT_LIBRARY_PATH = Path(r"C:\ProgramData\CODESYS")

POU_HEADER_RE = re.compile(
    r"^[ \t]*(FUNCTION_BLOCK|FUNCTION|PROGRAM|INTERFACE|METHOD|PROPERTY|ACTION|TYPE)"
    r"[ \t]+([A-Za-z_]\w*)",
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
        section = {
            "kind": kind,
            "name": name,
            "start": match.start(),
            "text": section_text,
            "line": text[: match.start()].count("\n") + 1,
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
        elif line.startswith("//"):
            line = line[2:]
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
    comment attached.
    """
    dut = section.get("dut")
    if dut:
        rows = []
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
                    "comment": "",
                }
            )
        return rows
    try:
        blocks = parse_var_blocks(section["text"])
    except Exception:
        return []
    rows = []
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
                    "comment": _member_comment(section["text"], member.get("line")),
                }
            )
    return rows


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


def _slug(value):
    """Filesystem-safe fragment: keep ``[A-Za-z0-9._-]``, underscore the rest."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value or ""))


def generate_docs(workspace, library_path=None, output=None):
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

    project_symbols = []
    st_paths = []
    for dirpath, _dirnames, filenames in os.walk(str(project_view)):
        for filename in filenames:
            if filename.lower().endswith(".st"):
                st_paths.append(Path(dirpath) / filename)
    st_paths.sort(key=lambda path: str(path).casefold())
    for path in st_paths:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = raw.lstrip("\ufeff")
        rel = str(path.relative_to(project_view)).replace("\\", "/")
        spans = _merge_line_comments(text, comment_spans(text))
        for section in _pou_sections(text, path.stem):
            project_symbols.append(
                {
                    "source": "project",
                    "library": None,
                    "version": None,
                    "kind": section["kind"],
                    "name": section["name"],
                    "path": rel,
                    "line": section["line"],
                    "description": _section_description(text, section, spans),
                    "interface": _section_interface(section),
                }
            )

    references, gap = explicit_library_references(project_view)
    documented = []
    missing = []
    for ref in references:
        libdoc = find_libdoc(library_root, ref["name"], ref["vendor"], ref["version"])
        if libdoc is None:
            missing.append(ref)
            continue
        documented.append({"ref": ref, "libdoc": libdoc, "symbols": library_symbols(libdoc)})

    library_rows = []
    for entry in documented:
        libdoc = entry["libdoc"]
        for sym in entry["symbols"]:
            library_rows.append(
                {
                    "source": "library",
                    "library": entry["ref"]["name"],
                    "version": libdoc["version"],
                    "kind": sym["kind"],
                    "name": sym["name"],
                    "path": sym.get("location", ""),
                    "line": None,
                    "description": sym["description"],
                    "interface": [
                        {c: str(row.get(c, "")) for c in INTERFACE_COLUMNS}
                        for row in sym.get("interface") or []
                    ],
                }
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

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "format": "cts-docs/v2",
        "generated_at": generated_at,
        "project_view": str(project_view),
        "libraries": str(library_root),
        "library_path_exists": library_root.is_dir(),
        "counts": {
            "project_pous": len(project_symbols),
            "library_pous": len(library_rows),
            "libraries_referenced": len(references),
            "libraries_documented": len(documented),
            "libraries_missing": len(missing),
            "libraries_not_referenced": len(not_referenced),
        },
        "libraries_missing": [
            {
                "name": ref["name"],
                "version": ref["version"],
                "vendor": ref["vendor"],
                "placeholder": ref["placeholder"],
            }
            for ref in missing
        ],
        "gaps": [gap] if gap else [],
    }

    output_root.mkdir(parents=True, exist_ok=True)
    try:
        (output_root / "bundle.md").unlink(missing_ok=True)
    except OSError:
        pass

    lines = ["# Project POUs", "", f"Generated from `{project_view}`.", ""]
    if not project_symbols:
        lines.extend(["_No POUs found under the project view._", ""])
    for symbol in project_symbols:
        lines.extend(
            [
                f"## {symbol['kind']} {symbol['name']}",
                "",
                f"`{symbol['path']}` (line {symbol['line']})",
                "",
                symbol["description"] or "_undocumented_",
                "",
            ]
        )
        lines.extend(_interface_table(symbol["interface"]))
        lines.append("")
    (output_root / "project.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    libraries_dir = output_root / "libraries"
    libraries_dir.mkdir(parents=True, exist_ok=True)
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
        f"Generated: `{generated_at}`",
        "",
        f"- Project view: `{project_view}`",
        f"- Library root: `{library_root}`",
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
            "| Library | Version | Vendor | Placeholder |",
            "|---|---|---|---|",
        ]
    )
    if missing:
        for ref in missing:
            lines.append(
                f"| {ref['name']} | {ref['version']} | {ref['vendor'] or '-'} "
                f"| {ref['placeholder'] or '-'} |"
            )
    else:
        lines.append("_None._")
    lines.extend(
        [
            "",
            "## Not referenced",
            "",
            "Libraries installed on this machine but not referenced by this project. Their contents",
            "are **not** exported here. To use one, ask the user to add it to the Library Manager",
            "first — do not assume it is available.",
            "",
            "| Library | Versions |",
            "|---|---|",
        ]
    )
    if not_referenced:
        for name, versions in not_referenced.items():
            lines.append(f"| {name} | {', '.join(versions)} |")
    else:
        lines.append("_None._")
    if gap:
        lines.extend(["", "## Gaps", "", f"- {gap}"])
    (output_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (output_root / "symbols.jsonl").open("w", encoding="utf-8") as stream:
        for row in project_symbols + library_rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return {"ok": True, "output": str(output_root), "manifest": manifest}


__all__ = ["DEFAULT_LIBRARY_PATH", "generate_docs"]