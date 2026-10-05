# -*- coding: utf-8 -*-
"""Library references as a real CODESYS project writes them.

The fixture is the Library Manager export of our own reference project
(``cts-reference-project``), so the shapes here are the ones CODESYS actually
emits, not the ones reconstructed from a description:

* a concrete item (``51a11660-...``) carries **no** ``Resolution`` and no
  ``DefaultResolution`` - the whole ``name, version (vendor)`` string sits in
  its ``Name`` field;
* the ``PlaceholderRedirectionTable`` is a ``Dictionary`` of ``Entry``
  elements, each with a ``Key``/``Value`` pair of nested ``Single`` elements,
  not a flat list of ``Single Name="<key>"`` rows.
"""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _PROJECT_ROOT / "products" / "cds-text-sync" / "src"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cds_text_sync import docgen  # noqa: E402
from cds_text_sync.engine import library_refs  # noqa: E402

FIXTURE = (
    Path(__file__).parent / "fixtures" / "library_manager" / "cts-reference-project.xml"
)

# The full GUID, read off the real export; the earlier prefix match existed
# only because the tail was unknown.
CONCRETE_GUID = "51a11660-6c0d-4598-8c08-419c5845ea1f"


@pytest.fixture
def references():
    view = FIXTURE.parent / "project-view"
    view.mkdir(exist_ok=True)
    (view / "Library Manager.xml").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    result, gap = library_refs.explicit_library_references(view)
    assert gap is None
    return result


def _by_name(references):
    return {ref["name"]: ref for ref in references}


def test_the_fixture_is_the_real_export():
    text = FIXTURE.read_text(encoding="utf-8")
    assert CONCRETE_GUID in text
    assert "PlaceholderRedirectionTable" in text
    assert "<Entry>" in text


def test_every_reference_of_the_reference_project_is_read(references):
    """All of them, with the kind and the exact name each one carries."""
    by_kind = {}
    for ref in references:
        by_kind.setdefault(ref["kind"], set()).add(ref["name"])

    assert by_kind["placeholder"] == {
        "IoStandard",
        "3SLicense",
        "CAA Device Diagnosis",
        # The resolution names the library "Breakpoint Logging Functions"; the
        # project refers to it by its placeholder.
        "Breakpoint Logging Functions",
    }
    assert by_kind["concrete"] == {"PSVRetain", "PSVLeds"}
    assert by_kind["redirected"] == {"Standard"}


def test_a_concrete_item_splits_its_name_field(references):
    """``Name`` holds the whole resolution, not a bare library name."""
    retain = _by_name(references)["PSVRetain"]

    assert retain["kind"] == "concrete"
    assert (retain["version"], retain["vendor"]) == ("*", "PSV Electro")
    assert retain["namespace"] == "PSVRetain"
    assert retain["system"] is True


def test_a_placeholder_keeps_its_placeholder_name(references):
    by_name = _by_name(references)

    assert by_name["IoStandard"]["placeholder"] == "IoStandard"
    assert (by_name["IoStandard"]["version"], by_name["IoStandard"]["vendor"]) == (
        "3.5.16.0",
        "System",
    )
    logging = by_name["Breakpoint Logging Functions"]
    assert logging["placeholder"] == "BreakpointLogging"
    assert logging["version"] == "*"
    assert logging["vendor"] == "3S - Smart Software Solutions GmbH"


def test_the_redirection_table_is_read_from_its_entry_pairs(references):
    """``Standard`` is reached only through the table, which holds Entry rows."""
    standard = _by_name(references)["Standard"]

    assert standard["kind"] == "redirected"
    assert (standard["version"], standard["vendor"]) == ("3.5.22.0", "System")
    assert standard["placeholder"] == "Standard"
    assert standard["system"] is True


def test_docgen_reports_all_seven_and_never_lists_standard_as_unreferenced(tmp_path):
    """End to end on the real export, with no LibDoc installed.

    Every library is missing its LibDoc here - that is what a machine without
    CODESYS looks like - but all seven must be *named* correctly, and ``Standard``
    must not fall through to "not referenced".
    """
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Library Manager.xml").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    manifest = docgen.generate_docs(workspace, library_path=libraries)["manifest"]
    counts = manifest["counts"]

    assert counts["libraries_referenced"] == 7
    assert counts["libraries_documented"] == 0
    assert counts["libraries_missing"] == 7
    assert counts["libraries_not_referenced"] == 0

    missing = {row["name"]: row for row in manifest["libraries_missing"]}
    assert set(missing) == {
        "IoStandard",
        "3SLicense",
        "CAA Device Diagnosis",
        "Breakpoint Logging Functions",
        "PSVRetain",
        "PSVLeds",
        "Standard",
    }
    assert missing["PSVRetain"]["kind"] == "concrete"
    assert missing["PSVRetain"]["vendor"] == "PSV Electro"
    assert missing["Standard"]["kind"] == "redirected"
    assert missing["Standard"]["version"] == "3.5.22.0"

    not_referenced = (
        workspace / ".cts-docs" / "libraries" / "not-referenced.md"
    ).read_text(encoding="utf-8")
    assert "Standard" not in not_referenced
    assert "PSVRetain" not in not_referenced
