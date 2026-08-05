"""
project.py - Building a ProjectSnapshot from ``project-view/``.

``cts analyze`` reads nothing but the exported ``project-view/`` tree. The
snapshot is the single source of truth handed to every rule via the context.

A unit is not a file: a unit is one analysable object. In the default
project-view layout each object is one file (a POU, a GVL, a DUT, a method
file ``Owner.Method.st``, an action file ``Owner.Action.st``), so v1 maps one
file to one unit. The Unit model already carries ``source_spans`` so a later
range-based split (methods inlined into a parent POU projection) can be added
without changing the rule API.

An unclassifiable ``.st`` file stays in the snapshot as a ``kind=UNKNOWN``
unit. It is not dropped: a text rule can still look at it, and a rule that
needed its declaration emits a Diagnostic instead of silently ignoring it.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from cds_static_analyzer.file_directives import directive_info
from cds_static_analyzer.model import Diagnostic, Location, line_col_of
from cds_static_analyzer.st import kinds as K

# The two implementation markers the engine family understands.
_IMPLEMENTATION_KEYWORD = "IMPLEMENTATION"
_COMMENT_MARKER = "// --- implementation ---"

_VISU_ROOT_TYPE = "{6198ad31-4b98-445c-927f-3258a0e82fe3}"
_TEXTLIST_FILENAME = "GlobalTextList.xml"

# Best-effort root tag extraction for XML that failed to parse (the parser
# cannot tell us the root element any more). The first char must be a name
# start so ``<?xml``, comments and DOCTYPE declarations are skipped.
_ROOT_TAG_RE = re.compile(r"<([A-Za-z_][\w.:-]*)((?:\s[^<>]*?)?)>")


def _local_tag(tag):
    """Strip an XML namespace prefix from a tag."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _infer_broken_xml_kind(relpath, text):
    """Best-effort analysis kind of an XML document that failed to parse.

    The root element is read from the raw text since the parser failed;
    when it cannot be determined the plain file family (``xml``) is
    reported instead.
    """
    if relpath.endswith(_TEXTLIST_FILENAME):
        return K.TEXTLIST
    match = _ROOT_TAG_RE.search(text or "")
    if match is None:
        return "xml"
    local = _local_tag(match.group(1))
    if local == "Visualization":
        return K.VISUALIZATION
    if local == "Single" and _VISU_ROOT_TYPE.lower() in (match.group(2) or "").lower():
        return K.VISUALIZATION
    if local == "TaskConfiguration":
        return K.TASK_CONFIG
    if local == "TextList":
        return K.TEXTLIST
    return "xml"


class SourceSpan:
    """A byte range in the unit's own text, with computed line/column.

    Line/column are display-only; identity never relies on them.
    """

    def __init__(self, start_offset, end_offset, text, role=""):
        self.role = role  # "declaration" | "implementation" | "whole"
        self.start_offset = start_offset
        self.end_offset = end_offset
        line, col = line_col_of(text, start_offset)
        end_line, end_col = line_col_of(text, end_offset)
        self.line = line
        self.column = col
        self.end_line = end_line
        self.end_column = end_col

    def to_dict(self):
        return {
            "role": self.role,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


def unit_id(relpath, qualified_name):
    """Stable identity: relative path + qualified name."""
    return f"{relpath}#{qualified_name}"


class Unit:
    """One analysable object of the project."""

    def __init__(
        self,
        id,
        kind,
        qualified_name,
        source_path,
        text,
        declaration=None,
        implementation=None,
        source_spans=None,
        owner_id=None,
        owner_name=None,
    ):
        self.id = id
        self.kind = kind
        self.qualified_name = qualified_name
        self.source_path = source_path
        self.text = text
        self.declaration = declaration
        self.implementation = implementation
        self.source_spans = source_spans or []
        self.owner_id = owner_id
        self.owner_name = owner_name

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "qualified_name": self.qualified_name,
            "source_path": self.source_path,
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "spans": [s.to_dict() for s in self.source_spans],
        }

    def __repr__(self):
        return f"<Unit {self.id} {self.kind}>"


@dataclass(frozen=True)
class FileDirectives:
    """Directives parsed once for one source file in a project snapshot."""

    rules: frozenset[str] = frozenset()
    issues: tuple = ()


def _relpath(root, full_path):
    return os.path.relpath(full_path, root).replace(os.sep, "/")


def _read_text(path):
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        text = fh.read()
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_st_with_offsets(text):
    """Split a .st blob into (decl, decl_span, impl, impl_span).

    Handles both the CODESYS ``IMPLEMENTATION`` keyword (project-view files)
    and the legacy ``// --- implementation ---`` marker. ``impl`` is None when
    no marker is present.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    kw_marker = "\n" + _IMPLEMENTATION_KEYWORD + "\n"
    idx = normalized.find(kw_marker)
    if idx >= 0:
        decl = normalized[:idx]
        impl_start = idx + len(kw_marker)
        raw_impl = normalized[impl_start:]
        lead = len(raw_impl) - len(raw_impl.lstrip("\n"))
        impl = raw_impl[lead:]
        decl_span = SourceSpan(0, idx, normalized, "declaration")
        impl_span = SourceSpan(
            impl_start + lead, len(normalized), normalized, "implementation"
        )
        return decl, decl_span, impl, impl_span

    comment_marker = "\n" + _COMMENT_MARKER + "\n"
    idx = normalized.find(comment_marker)
    if idx >= 0:
        decl = normalized[:idx]
        impl_start = idx + len(comment_marker)
        raw_impl = normalized[impl_start:]
        lead = len(raw_impl) - len(raw_impl.lstrip("\n"))
        impl = raw_impl[lead:]
        decl_span = SourceSpan(0, idx, normalized, "declaration")
        impl_span = SourceSpan(
            impl_start + lead, len(normalized), normalized, "implementation"
        )
        return decl, decl_span, impl, impl_span

    return normalized, SourceSpan(0, len(normalized), normalized, "whole"), None, None


def _classify_xml(relpath, text):
    """Classify a native XML file into a kind, or None if not analysable.

    Raises ``ET.ParseError`` when the document does not parse; the caller
    turns that into a structured ``SourceError`` record.
    """
    if relpath.endswith(_TEXTLIST_FILENAME):
        return K.TEXTLIST
    root = ET.fromstring(text)
    local = _local_tag(root.tag)
    if local == "TaskConfiguration":
        return K.TASK_CONFIG
    # CODESYS exports task configuration objects as its native ``Single``
    # archive format.  Individual task files contain ``PouList``; the
    # container contains ``TaskConfigurationList``.  Recognise the shape,
    # not the folder name, so this also works with renamed applications.
    if local == "Single":
        names = {
            element.attrib.get("Name")
            for element in root.iter()
            if element.attrib.get("Name")
        }
        if {"PouList", "TaskConfigurationList"} & names:
            return K.TASK_CONFIG
    if local == "Visualization":
        return K.VISUALIZATION
    if (
        local == "Single"
        and root.attrib.get("Type", "").lower() == _VISU_ROOT_TYPE.lower()
    ):
        return K.VISUALIZATION
    if local == "TextList":
        return K.TEXTLIST
    return None


class SourceError:
    """A source object that could not be read or parsed.

    ``location`` is project-view-relative; ``source_kind`` is the analysis
    kind where it can be inferred (e.g. ``visualization``) or the plain
    file family (``st``/``xml``) otherwise; ``message`` is concise and
    stable; ``unit_id`` mirrors the id the unit would have had.
    """

    def __init__(self, relpath, source_kind, message, line=None, column=None):
        self.location = Location(relpath, line=line, column=column)
        self.source_kind = source_kind
        self.message = message
        self.unit_id = unit_id(relpath, os.path.splitext(os.path.basename(relpath))[0])


class ProjectSnapshot:
    """All analysable units of one project-view tree."""

    def __init__(
        self, root, units=None, diagnostics=None, source_errors=None, file_directives=None
    ):
        self.root = root
        self.units = units or []
        self.diagnostics = diagnostics or []
        self.source_errors = source_errors or []
        self.file_directives = file_directives or {}
        self._by_id = {}
        self._by_name = {}
        for u in self.units:
            self._by_id[u.id] = u
            self._by_name.setdefault(u.qualified_name.lower(), []).append(u)

    def find_unit(self, id):
        return self._by_id.get(id)

    def units_by_name(self, qualified_name):
        return self._by_name.get((qualified_name or "").lower(), [])

    def units_owned_by(self, owner_name):
        key = (owner_name or "").lower()
        return [u for u in self.units if (u.owner_name or "").lower() == key]

    def to_dict(self):
        return {
            "units": [u.to_dict() for u in self.units],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "source_errors": [
                {
                    "location": e.location.to_dict(),
                    "source_kind": e.source_kind,
                    "message": e.message,
                }
                for e in self.source_errors
            ],
            "file_directives": {
                path: {"rules": sorted(value.rules), "issues": list(value.issues)}
                for path, value in sorted(self.file_directives.items())
            },
        }


def build_snapshot(project_view):
    """Build a ProjectSnapshot from a project-view directory.

    Never raises for a single unreadable or unparsable file: unreadable
    files land in ``snapshot.diagnostics`` (and a structured ``SourceError``
    record), unparsable XML becomes a ``SourceError`` record, and
    unclassifiable ``.st`` files become ``kind=UNKNOWN`` units. The run
    continues (policy-controlled completeness); rules that needed the
    missing model report a Diagnostic. Unknown but parseable XML is not an
    error: only a document the parser could not read counts as a gap.
    """
    root = os.path.abspath(project_view)
    units = []
    diagnostics = []
    source_errors = []
    file_directives = {}
    by_owner_stem = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in sorted(filenames):
            full_path = os.path.join(dirpath, filename)
            rel = _relpath(root, full_path)
            lower = filename.lower()
            if not lower.endswith((".st", ".xml")):
                continue
            try:
                text = _read_text(full_path)
            except OSError as exc:
                family = "st" if lower.endswith(".st") else "xml"
                source_errors.append(
                    SourceError(rel, family, f"cannot read {rel}: {exc}")
                )
                diagnostics.append(
                    Diagnostic(
                        "project-read",
                        f"cannot read {rel}: {exc}",
                        location=Location(rel),
                    )
                )
                continue

            if lower.endswith(".st"):
                rules, issues = directive_info(text)
                file_directives[rel] = FileDirectives(rules, issues)
                unit = _build_st_unit(rel, text)
            else:
                try:
                    unit = _build_xml_unit(rel, text)
                except ET.ParseError as exc:
                    source_errors.append(_xml_parse_error(rel, text, exc))
                    continue

            if unit is None:
                continue
            units.append(unit)
            if unit.owner_name:
                by_owner_stem.setdefault(unit.owner_name.lower(), []).append(unit)

    # Resolve owner ids in a post-pass (case-insensitive: IEC identifiers).
    by_qual = {}
    for u in units:
        by_qual.setdefault(u.qualified_name.lower(), u)
    for u in units:
        if u.owner_name:
            owner = by_qual.get(u.owner_name.lower())
            if owner is not None:
                u.owner_id = owner.id

    units.sort(key=lambda u: u.id)
    return ProjectSnapshot(root, units, diagnostics, source_errors, file_directives)


def _xml_parse_error(rel, text, exc):
    """Build a SourceError for an XML document that failed to parse."""
    line, column = getattr(exc, "position", (None, None)) or (None, None)
    return SourceError(
        rel,
        _infer_broken_xml_kind(rel, text),
        f"cannot parse {rel}: {exc}",
        line=line,
        column=column,
    )


def _build_st_unit(rel, text):
    # Keep offsets, spans, and rule locations in the same normalized text
    # coordinate system even when callers bypass build_snapshot in tests.
    text = (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    decl, decl_span, impl, impl_span = _split_st_with_offsets(text)
    kind = K.classify_st_decl(decl)

    base = os.path.basename(rel)
    stem = os.path.splitext(base)[0]
    # CODESYS exports property accessors without a PROPERTY header.  The
    # declaration projection is only ``VAR\nEND_VAR`` and the accessor kind
    # is carried by the filename (``Owner.Property.Get.st`` / ``Set.st``).
    # Treat these as valid property units instead of unknown/unparsed ST.
    if kind == K.UNKNOWN:
        suffix = stem.rsplit(".", 1)[-1].casefold() if "." in stem else ""
        if suffix == "get":
            kind = K.PROPERTY_GET
        elif suffix == "set":
            kind = K.PROPERTY_SET
    owner_name = None
    qualified = stem
    if "." in stem:
        owner_name = stem.rsplit(".", 1)[0]
    if kind in (K.METHOD, K.ACTION, K.PROPERTY_GET, K.PROPERTY_SET) and not owner_name:
        owner_name = stem
    # GVL/DUT objects are their own owners.

    spans = [s for s in (decl_span, impl_span) if s is not None]
    return Unit(
        id=unit_id(rel, qualified),
        kind=kind,
        qualified_name=qualified,
        source_path=rel,
        text=text,
        declaration=decl,
        implementation=impl,
        source_spans=spans,
        owner_name=owner_name,
    )


def _build_xml_unit(rel, text):
    """Build a Unit from a native XML file, or None if not analysable.

    Raises ``ET.ParseError`` when the document does not parse: the caller
    decides whether that is a model gap (snapshot build records a
    ``SourceError``) or a test/selftest failure.
    """
    kind = _classify_xml(rel, text)
    if kind is None:
        return None
    stem = os.path.splitext(os.path.basename(rel))[0]
    return Unit(
        id=unit_id(rel, stem),
        kind=kind,
        qualified_name=stem,
        source_path=rel,
        text=text,
        declaration=None,
        implementation=None,
        source_spans=[SourceSpan(0, len(text), text, "whole")],
    )
