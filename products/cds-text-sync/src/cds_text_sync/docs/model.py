"""Canonical documentation records shared by JSON and Markdown renderers.

The model deliberately contains facts and references only.  It does not know
how a source file was parsed and it never stores an implementation body.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


def stable_id(source, kind, qualified_name, *, namespace=None, version=None):
    """Return a deterministic logical symbol id.

    Source paths are intentionally excluded for project symbols: moving a
    source file must not silently rename the logical symbol.  Library version
    remains part of identity because two installed versions are different
    contracts.
    """
    parts = [str(source or "project"), str(namespace or ""), str(version or ""),
             str(kind or "unknown"), str(qualified_name or "")]
    slug = "::".join(part.casefold() for part in parts if part != "")
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:12]
    return f"{str(source or 'project').casefold()}::{str(kind or 'unknown').casefold()}::{digest}"


@dataclass(frozen=True)
class DocSource:
    id: str
    kind: str
    path: str
    sha256: str
    size: int

    @classmethod
    def from_text(cls, kind, path, text):
        payload = (text or "").encode("utf-8")
        path = str(path).replace("\\", "/")
        return cls(
            id=f"source:{str(kind).casefold()}:{path}",
            kind=str(kind),
            path=path,
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )

    def to_dict(self):
        return {
            "id": self.id, "kind": self.kind, "path": self.path,
            "sha256": self.sha256, "size": self.size,
        }


@dataclass
class DocDiagnostic:
    code: str
    severity: str
    message: str
    symbol_id: str | None = None
    source_ref: dict | None = None

    def to_dict(self):
        result = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.symbol_id:
            result["symbol_id"] = self.symbol_id
        if self.source_ref:
            result["source_ref"] = self.source_ref
        return result


@dataclass
class DocRelation:
    kind: str
    from_id: str
    to_id: str
    site: dict | None = None
    resolution: str = "exact"
    confidence: str = "high"
    candidates: list[str] = field(default_factory=list)

    def to_dict(self):
        result = {
            "kind": self.kind, "from": self.from_id, "to": self.to_id,
            "resolution": self.resolution, "confidence": self.confidence,
        }
        if self.site:
            result["site"] = self.site
        if self.candidates:
            result["candidates"] = list(self.candidates)
        return result


@dataclass
class DocSymbol:
    id: str
    source: str
    kind: str
    name: str
    qualified_name: str
    path: str
    library: str | None = None
    version: str | None = None
    vendor: str | None = None
    namespace: str | None = None
    owner_id: str | None = None
    source_spans: list = field(default_factory=list)
    line: int | None = None
    description: str = ""
    interface: list = field(default_factory=list)
    source_ref: dict | None = None
    declaration: dict = field(default_factory=dict)
    parse_status: str = "complete"
    parse_warnings: list = field(default_factory=list)
    behavior_status: str = "not_extracted"
    behavior_facts: list = field(default_factory=list)
    behavior_summary: str = ""
    card: str | None = None

    def to_dict(self):
        result = {
            "id": self.id,
            "source": self.source,
            "kind": self.kind,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "path": self.path,
            "library": self.library,
            "version": self.version,
            "vendor": self.vendor,
            "namespace": self.namespace,
            "owner_id": self.owner_id,
            "source_spans": self.source_spans,
            "line": self.line,
            "description": self.description,
            "interface": self.interface,
            "declaration": self.declaration,
            "parse": {"status": self.parse_status, "warnings": self.parse_warnings},
            "behavior": {
                "status": self.behavior_status,
                "facts": self.behavior_facts,
                "summary": self.behavior_summary,
            },
        }
        if self.source_ref:
            result["source_ref"] = self.source_ref
        if self.card:
            result["card"] = self.card
        return result


@dataclass
class DocBundle:
    sources: list[DocSource] = field(default_factory=list)
    symbols: list[DocSymbol] = field(default_factory=list)
    relations: list[DocRelation] = field(default_factory=list)
    diagnostics: list[DocDiagnostic] = field(default_factory=list)

    def validate(self):
        """Return diagnostics for broken internal references."""
        errors = list(self.diagnostics)
        source_ids = {source.id for source in self.sources}
        symbol_ids = {symbol.id for symbol in self.symbols}
        if len(source_ids) != len(self.sources):
            errors.append(DocDiagnostic("duplicate_source_id", "error", "source IDs are not unique"))
        if len(symbol_ids) != len(self.symbols):
            errors.append(DocDiagnostic("duplicate_symbol_id", "error", "symbol IDs are not unique"))
        parse_loss_symbols = {
            diagnostic.symbol_id
            for diagnostic in self.diagnostics
            if diagnostic.code == "parse_loss" and diagnostic.symbol_id
        }
        for symbol in self.symbols:
            if symbol.parse_status == "complete" and symbol.id in parse_loss_symbols:
                errors.append(DocDiagnostic(
                    "parse_status_conflict", "error",
                    "parse.status=complete is incompatible with parse_loss diagnostics",
                    symbol_id=symbol.id,
                ))
        for symbol in self.symbols:
            if symbol.source_ref and symbol.source_ref.get("id") not in source_ids:
                errors.append(DocDiagnostic(
                    "dangling_source_ref", "error",
                    f"source reference does not exist: {symbol.source_ref.get('id')}",
                    symbol_id=symbol.id,
                ))
        for relation in self.relations:
            for endpoint in (relation.from_id, relation.to_id):
                if endpoint not in symbol_ids and not endpoint.startswith(("external::", "unresolved::")):
                    errors.append(DocDiagnostic(
                        "dangling_relation", "error",
                        f"relation endpoint does not exist: {endpoint}",
                    ))
            for candidate in relation.candidates:
                if candidate not in symbol_ids and not candidate.startswith(("external::", "unresolved::")):
                    errors.append(DocDiagnostic(
                        "dangling_relation_candidate", "error",
                        f"relation candidate does not exist: {candidate}",
                    ))
        return errors


def json_line(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "DocBundle", "DocDiagnostic", "DocRelation", "DocSource", "DocSymbol",
    "json_line", "stable_id",
]
