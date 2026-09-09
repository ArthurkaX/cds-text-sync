"""Generate a compact, LLM-friendly documentation bundle.

The project view and the installed CODESYS library tree are deliberately kept
as separate sources.  This makes it possible to refresh project documentation
without accidentally treating system libraries as project code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIBRARY_PATH = Path(r"C:\ProgramData\CODESYS")
SOURCE_EXTENSIONS = {".st", ".library", ".compiled-library", ".xml", ".csv"}
PROJECT_DOC_EXTENSIONS = {".st", ".csv"}
LIBRARY_DOC_EXTENSIONS = SOURCE_EXTENSIONS | {".html", ".htm", ".md", ".json", ".txt"}
LIBRARY_SUBDIRECTORIES = ("LibDoc", "Managed Libraries")
DECLARATION_RE = re.compile(
    r"^\s*<?\s*(FUNCTION_BLOCK|FUNCTION|PROGRAM|INTERFACE|STRUCT|TYPE|ENUM|ALIAS)\s+([A-Za-z_]\w*)",
    re.IGNORECASE | re.MULTILINE,
)


def _decode_source(raw):
    """Decode text sources without dumping binary library containers as noise."""
    if raw.startswith(b"PK") or b"\x00" in raw[:4096]:
        return "[binary library artifact; textual documentation unavailable]", False
    return raw.decode("utf-8", "replace"), True


def _files(root, extensions=SOURCE_EXTENSIONS):
    root = Path(root)
    if not root.exists():
        return []
    result = []
    for current, _dirs, names in os.walk(str(root)):
        for name in names:
            path = Path(current) / name
            if name.casefold() == "browsercache" or path.suffix.lower() in extensions:
                result.append(path)
    return sorted(result, key=lambda path: str(path).casefold())


def _library_roots(root):
    """Limit the default CODESYS tree to locations that contain documentation."""
    root = Path(root)
    if root.name.casefold() in {name.casefold() for name in LIBRARY_SUBDIRECTORIES}:
        return [root]
    children = [root / name for name in LIBRARY_SUBDIRECTORIES]
    existing = [path for path in children if path.is_dir()]
    return existing or [root]


def _library_extensions(root):
    """Select compact documentation files for the standard installation tree."""
    name = root.name.casefold()
    if name == "managed libraries":
        return {".md"}
    if name == "libdoc":
        return set()
    return LIBRARY_DOC_EXTENSIONS


def _source_entry(path, root, source, raw=None, text_available=True):
    raw = raw if raw is not None else source.encode("utf-8", "replace")
    digest = hashlib.sha256(raw).hexdigest()
    parse_source = source.lstrip("\ufeff")
    declarations = [
        {"kind": kind.upper(), "name": name, "line": parse_source[: match.start()].count("\n") + 1}
        for match in DECLARATION_RE.finditer(parse_source)
        for kind, name in [match.groups()]
    ]
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": digest,
        "bytes": len(raw),
        "declarations": declarations,
        "text": source,
        "text_available": text_available,
    }


def _markdown_language(path):
    """Return a useful fenced-code language for a source suffix."""
    suffix = Path(path).suffix.lower()
    return {".st": "iecst", ".xml": "xml", ".csv": "csv"}.get(suffix, "text")


def _bundle_markdown(sources):
    """Render source entries as one deterministic, LLM-friendly document."""
    lines = [
        "# CODESYS source bundle",
        "",
        "This file is generated. Use the source/path headings to cite a file.",
        "",
    ]
    for row in sources:
        lines.extend(
            [
                "## {0}: `{1}`".format(row["source"], row["path"]),
                "",
                "SHA-256: `{0}`  ".format(row["sha256"]),
                "Declarations: {0}".format(
                    ", ".join(
                        "{0} {1}".format(item["kind"], item["name"])
                        for item in row["declarations"]
                    )
                    or "none"
                ),
                "",
                "```{0}".format(_markdown_language(row["path"])),
                row["text"].rstrip("\n"),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


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
    output_root.mkdir(parents=True, exist_ok=True)

    sources = []
    groups = [("project", project_view, PROJECT_DOC_EXTENSIONS)]
    groups.extend(("library", root, _library_extensions(root)) for root in _library_roots(library_root))
    for source_kind, root, extensions in groups:
        for path in _files(root, extensions):
            try:
                raw = path.read_bytes()
                text, text_available = _decode_source(raw)
            except OSError:
                continue
            entry = _source_entry(path, root, text, raw=raw, text_available=text_available)
            entry["source"] = source_kind
            sources.append(entry)

    sources.sort(key=lambda item: (item["source"], item["path"].casefold()))
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "format": "cts-docs/v1",
        "generated_at": generated_at,
        "project_view": str(project_view),
        "libraries": str(library_root),
        "library_path_exists": library_root.is_dir(),
        "counts": {
            "files": len(sources),
            "project_files": sum(row["source"] == "project" for row in sources),
            "library_files": sum(row["source"] == "library" for row in sources),
            "declarations": sum(len(row["declarations"]) for row in sources),
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with (output_root / "symbols.jsonl").open("w", encoding="utf-8") as stream:
        for row in sources:
            metadata = dict(row)
            metadata.pop("text", None)
            stream.write(json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n")

    lines = [
        "# CODESYS documentation bundle", "", f"Generated: `{generated_at}`", "",
        "## Sources", "", f"- Project view: `{project_view}`", f"- Libraries: `{library_root}`", "",
        "## Inventory", "", f"- Files: {manifest['counts']['files']}",
        f"- Project files: {manifest['counts']['project_files']}",
        f"- Library files: {manifest['counts']['library_files']}",
        f"- Declarations: {manifest['counts']['declarations']}", "",
        "## Files", "", "| Source | Path | Declarations | SHA-256 |", "|---|---|---:|---|",
    ]
    for row in sources:
        lines.append(f"| {row['source']} | `{row['path']}` | {len(row['declarations'])} | `{row['sha256'][:16]}` |")
    (output_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output_root / "bundle.md").write_text(_bundle_markdown(sources), encoding="utf-8")
    return {"ok": True, "output": str(output_root), "manifest": manifest}


__all__ = ["DEFAULT_LIBRARY_PATH", "generate_docs"]
