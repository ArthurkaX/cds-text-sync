"""Tests for the canonical documentation model."""

from cds_text_sync.docs.model import (
    DocBundle,
    DocDiagnostic,
    DocRelation,
    DocSource,
    DocSymbol,
    stable_id,
)


def test_stable_id_ignores_project_path_and_distinguishes_library_version():
    assert stable_id("project", "PROGRAM", "Main") == stable_id(
        "project", "program", "main"
    )
    assert stable_id("library", "FB", "TON", namespace="Std", version="1") != stable_id(
        "library", "FB", "TON", namespace="Std", version="2"
    )


def test_bundle_validation_detects_dangling_source_and_relation_refs():
    source = DocSource.from_text("project", "Main.st", "PROGRAM Main")
    symbol = DocSymbol(
        id="project::program::main",
        source="project",
        kind="PROGRAM",
        name="Main",
        qualified_name="Main",
        path="Main.st",
        source_ref={"id": source.id, "line": 1},
    )
    bundle = DocBundle(
        sources=[source],
        symbols=[symbol],
        relations=[DocRelation("calls", symbol.id, "unresolved::call:Missing")],
    )

    assert bundle.validate() == []

    bundle.symbols[0].source_ref = {"id": "source:missing", "line": 1}
    bundle.relations.append(DocRelation("calls", symbol.id, "project::function::missing"))
    codes = {diagnostic.code for diagnostic in bundle.validate()}
    assert {"dangling_source_ref", "dangling_relation"} <= codes


def test_relation_serializes_resolution_candidates():
    relation = DocRelation(
        "calls", "project::program::main", "unresolved::call:FB_Demo",
        resolution="unresolved", confidence="medium",
        candidates=["library::fb::one", "library::fb::two"],
    )

    assert relation.to_dict()["candidates"] == [
        "library::fb::one", "library::fb::two"
    ]


def test_bundle_validation_checks_source_and_candidate_uniqueness():
    source = DocSource.from_text("project", "Main.st", "PROGRAM Main")
    symbol = DocSymbol(
        id="project::program::main", source="project", kind="PROGRAM",
        name="Main", qualified_name="Main", path="Main.st",
    )
    bundle = DocBundle(
        sources=[source, source], symbols=[symbol],
        relations=[DocRelation(
            "calls", symbol.id, "unresolved::call:Missing",
            candidates=["library::fb::missing"],
        )],
    )

    codes = {diagnostic.code for diagnostic in bundle.validate()}
    assert {"duplicate_source_id", "dangling_relation_candidate"} <= codes


def test_bundle_rejects_complete_symbol_with_parse_loss_diagnostic():
    symbol = DocSymbol(
        id="project::enum::state", source="project", kind="ENUM",
        name="State", qualified_name="State", path="State.st",
        parse_status="complete",
    )
    bundle = DocBundle(
        symbols=[symbol],
        diagnostics=[DocDiagnostic(
            "parse_loss", "warning", "enum base type missing", symbol_id=symbol.id
        )],
    )

    assert any(
        diagnostic.code == "parse_status_conflict"
        for diagnostic in bundle.validate()
    )
