"""Characterization (golden) test for the ``docgen`` bundle.

``_generate_docs`` is a single ~700-line function that we intend to split into
stages (symbol collection, references/libraries, inheritance, cards/navigation,
manifest, writing).  Before that refactor this test freezes the *current*
output of one deliberately rich project-view byte for byte, so any behaviour
change shows up as a focused failure instead of a silent drift.

The fixture is generated in ``tmp_path`` by code (no binary blobs) and drives
as many branches of ``_generate_docs`` as are reachable without a CODESYS
installation: project symbols of every kind, unresolved and cyclic ``EXTENDS``,
resolved and unresolved calls, a task root, qualified and bare global
read/write traffic, an installed-and-documented library, three kinds of
missing LibDoc, an installed-but-unreferenced library, and two snapshot-level
diagnostics (an unclassifiable ``.st`` unit and an unparseable ``.xml``).

Update the golden after an intentional change::

    UPDATE_DOCGEN_GOLDEN=1 .venv/bin/python -m pytest \\
        products/cds-text-sync/tests/test_docgen_golden.py -q

Known current behaviour (pinned, not a bug report) and known gaps are noted on
the individual tests at the bottom of this module.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

import pytest

from cds_text_sync import docgen

GOLDEN = Path(__file__).parent / "golden" / "docgen" / "bundle.json"

_GENERATED_AT_RE = re.compile(r'("generated_at":\s*)"[^"]*"')

# Diagnostics the fixture is expected to produce at generation time; every one
# of them is deliberate, and no *other* code may appear.
_EXPECTED_DIAGNOSTIC_CODES = {
    "missing_external_docs",
    "source_error",
    "unsupported_construct",
    "unresolved_relation",
}

# Diagnostics that signal a broken bundle rather than a documented project
# limitation.  ``validate_bundle`` must never report one of these.
_INTEGRITY_CODES = {
    "bundle_unreadable",
    "dangling_relation",
    "dangling_relation_candidate",
    "dangling_source_ref",
    "duplicate_source_id",
    "duplicate_symbol_id",
    "parse_status_conflict",
}


# --------------------------------------------------------------------------
# Fixture sources
# --------------------------------------------------------------------------

_POUS = {
    "FB_Base.st": """\
(*
Base block shared by every motor-like device.
It owns the enable/status contract.
*)
FUNCTION_BLOCK FB_Base
VAR_INPUT
    xEnable : BOOL;              // master enable
END_VAR
VAR_OUTPUT
    xActive : BOOL := FALSE;     // mirror of xEnable
END_VAR
VAR
    nRuntime : UDINT;            // seconds spent active
END_VAR
IMPLEMENTATION
xActive := xEnable;
END_FUNCTION_BLOCK
""",
    "FB_Motor.st": """\
(*
Concrete drive block, derived from FB_Base.
*)
FUNCTION_BLOCK FB_Motor EXTENDS FB_Base
VAR_INPUT
    nSpeed : INT := 0;           // target speed in rpm
    bReverse : BOOL;             // direction flag
END_VAR
VAR_OUTPUT
    bMoving : BOOL;              // TRUE while the drive turns
END_VAR
VAR
    tRamp : TON;                 // ramp timer
END_VAR
IMPLEMENTATION
bMoving := nSpeed > 0 AND xEnable;
tRamp(IN := bMoving, PT := T#5S);
IF tRamp.Q THEN
    nRuntime := nRuntime + 1;
END_IF
END_FUNCTION_BLOCK
""",
    "FB_Motor.Run.st": """\
(*
Run one control step.
*)

// Callers pass the number of ramp steps.
METHOD Run : BOOL
VAR_INPUT
    nSteps : INT := 1;
END_VAR
VAR
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 1 TO nSteps DO
    bMoving := TRUE;
END_FOR
Run := bMoving;
END_METHOD
""",
    "Prg_Main.st": """\
(*
Top-level cyclic program.
*)
PROGRAM Prg_Main
VAR
    fbDrive : FB_Motor;          // the one motor instance
    nAccumulator : DINT;         // rolling counter
END_VAR
IMPLEMENTATION
fbDrive();
fbDrive.Run(nSteps := 2);
nAccumulator := F_Add(nAccumulator, 1);
GVL_HMI.g_bRunning := TRUE;
IF GVL_HMI.g_nMode > 0 THEN
    nAccumulator := nAccumulator + g_nMode;
END_IF
FB_Demo();
MysteryCall();
END_PROGRAM
""",
    "F_Add.st": """\
(*
Add two integers. Exists to exercise the return-type row.
*)
FUNCTION F_Add : INT
VAR_INPUT
    a : INT;                     // first addend
    b : INT;                     // second addend
END_VAR
IMPLEMENTATION
F_Add := a + b;
END_FUNCTION
""",
    "GVL_HMI.st": """\
{attribute 'qualified_only'}
VAR_GLOBAL
    g_bRunning : BOOL := FALSE;  // drive is running
    g_nMode : INT := 0;          // operator mode
    g_sBanner : STRING(40) := 'ready';
END_VAR
""",
    "GVL_Persist.st": """\
VAR_GLOBAL PERSISTENT
    g_nBootCount : UDINT;        // survives a warm start
END_VAR
""",
}

_TYPES = {
    "ST_Pos.st": """\
TYPE ST_Pos :
STRUCT
    x : INT;                     // horizontal coordinate
    y : INT;                     // vertical coordinate
END_STRUCT
END_TYPE
""",
    "ST_PosEx.st": """\
TYPE ST_PosEx EXTENDS ST_Pos :
STRUCT
    z : INT;                     // depth coordinate
END_STRUCT
END_TYPE
""",
    "ST_PosEx2.st": """\
TYPE ST_PosEx2 EXTENDS ST_PosEx :
STRUCT
    scale : REAL := 1.0;         // unit scale
END_STRUCT
END_TYPE
""",
    # A cycle: ST_CycA derives from ST_CycB and vice versa.  ``inherited_for``
    # must terminate instead of recursing forever.
    "ST_CycA.st": """\
TYPE ST_CycA EXTENDS ST_CycB :
STRUCT
    a : INT;
END_STRUCT
END_TYPE
""",
    "ST_CycB.st": """\
TYPE ST_CycB EXTENDS ST_CycA :
STRUCT
    b : INT;
END_STRUCT
END_TYPE
""",
    # The base type does not exist in the project: the relation stays
    # unresolved instead of being dropped.
    "ST_Orphan.st": """\
TYPE ST_Orphan EXTENDS ST_NotInstalled :
STRUCT
    tag : STRING(8);
END_STRUCT
END_TYPE
""",
    "E_Mode.st": """\
TYPE E_Mode :
(
    IDLE := 0,                   // no work
    RUN := 1,                    // normal operation
    FAULT := 2                   // latched fault
) UINT;
END_TYPE
""",
}

_MISC = {
    # No POU header and no VAR_GLOBAL: the unit cannot be classified, which
    # must surface as an ``unsupported_construct`` warning.
    "Mystery.st": "xNeverDeclared := 1;\n",
    # Truncated XML: a snapshot-level ``source_error``.
    "Broken.xml": '<Single><List Name="Items"><Single>\n',
}

_LIBRARY_MANAGER = [
    {
        "resolution": "Demo, 1.2.3.4 (Acme)",
        "placeholder": "Demo",
        "namespace": "DEMO",
        "system": "True",
    },
    # Same library, an exact version that is not installed.
    {
        "resolution": "Demo, 5.0.0.0 (Acme)",
        "placeholder": "Demo",
        "namespace": "DEMO",
        "system": "True",
    },
    # Not installed at all.
    {
        "resolution": "MissingLib, 9.9.9.9 (Acme)",
        "placeholder": "MissingLib",
        "namespace": "MISSINGLIB",
        "system": "False",
    },
    # Installed directory exists but carries no version subdirectory.
    {
        "resolution": "WildLib, * (Acme)",
        "placeholder": "WildLib",
        "namespace": "WILDLIB",
        "system": "False",
    },
]

_POU_PAGE_HTML = """\
<html><body>
<h1>FB_Demo (FB)<a class="headerlink" href="#">¶</a></h1>
<p>FUNCTION_BLOCK FB_Demo</p>
<p>Demo block used by the golden fixture.</p>
<dl class="docutils">
<dt>InOut:</dt>
<dd>
<table>
<thead><tr><th>Scope</th><th>Name</th><th>Type</th><th>Initial</th><th>Comment</th></tr></thead>
<tbody>
<tr><td rowspan="2">Input</td><td>xEnable</td><td>BOOL</td><td></td><td>enable</td></tr>
<tr><td>tTimeout</td><td>TIME</td><td>T#1S</td><td>timeout</td></tr>
<tr><td>Output</td><td>xDone</td><td>BOOL</td><td></td><td>done</td></tr>
</tbody>
</table>
</dd>
</dl>
</body></html>
"""


def _library_manager_xml(entries):
    items = "\n".join(
        """
          <Single Type="{{4723ebe7-5bfc-43c6-be6b-5097002ef6b4}}" Method="IArchivable">
            <Single Name="DefaultResolution" Type="string">{resolution}</Single>
            <Single Name="PlaceholderName" Type="string">{placeholder}</Single>
            <Single Name="Namespace" Type="string">{namespace}</Single>
            <Single Name="SystemLibrary" Type="bool">{system}</Single>
          </Single>""".format(**entry)
        for entry in entries
    )
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<Single Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}" Method="IArchivable">\n'
        '  <Single Name="Object" Type="{adb5cb65-8e1d-4a00-b70a-375ea27582f3}"'
        ' Method="IArchivable">\n'
        '    <List Name="Items" Type="System.Collections.ArrayList">'
        + items
        + "\n    </List>\n  </Single>\n</Single>\n"
    )


def _write_libdoc(root, vendor, name, version, locale="en"):
    locale_dir = root / "LibDoc" / vendor / name / version / locale
    locale_dir.mkdir(parents=True)
    (locale_dir / "fb_demo.html").write_text(_POU_PAGE_HTML, encoding="utf-8")
    manifest = {
        "library": {"company": vendor, "title": name, "version": version},
        "inventory": {
            "std:doc": {
                "fb_demo": {"location": "fb_demo.html", "name": "FB_Demo (FB)"},
                "index": {"location": "index.html", "name": "Index"},
            }
        },
    }
    (locale_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return locale_dir


def _build_fixture(workspace):
    """Create the project-view and the LibDoc tree; return ``(project, libs)``."""
    project = workspace / "project-view"
    for subdir in ("POUs", "Types", "Misc"):
        (project / subdir).mkdir(parents=True)
    for group, files in (("POUs", _POUS), ("Types", _TYPES), ("Misc", _MISC)):
        for name, text in files.items():
            (project / group / name).write_text(text, encoding="utf-8")
    (project / "Task Configuration.xml").write_text(
        "<Single><List Name=\"PouList\"><Single>"
        "<Single Name=\"Name\">Prg_Main</Single>"
        "</Single></List></Single>",
        encoding="utf-8",
    )
    (project / "Library Manager.xml").write_text(
        _library_manager_xml(_LIBRARY_MANAGER), encoding="utf-8"
    )

    libraries = workspace / "libraries"
    _write_libdoc(libraries, "Acme", "Demo", "1.2.3.4")
    # Installed but unreferenced, and carrying two versions so the manifest
    # version union is exercised.
    _write_libdoc(libraries, "Acme", "Unused", "2.0.0")
    _write_libdoc(libraries, "Acme", "Unused", "2.1.0")
    # Referenced with a wildcard version but no version directory: this makes
    # ``_missing_library_reason`` report ``wildcard_unresolved``.
    (libraries / "LibDoc" / "Acme" / "WildLib").mkdir(parents=True)
    return project, libraries


# --------------------------------------------------------------------------
# Collection / normalisation
# --------------------------------------------------------------------------


def _normalize(path, text, workspace, libraries):
    """Replace machine-specific content so the golden is portable.

    ``manifest.json`` carries the absolute project-view and library paths as
    JSON strings, where Windows would additionally escape every backslash, so
    it is normalised structurally.  The markdown files embed the same paths as
    plain text and are normalised by substitution.
    """
    if path.name == "manifest.json":
        data = json.loads(text)
        data["generated_at"] = "<GENERATED_AT>"
        data["project_view"] = "<PROJECT_VIEW>"
        data["libraries"] = "<LIBRARY_ROOT>"
        return json.dumps(data, indent=2) + "\n"
    text = text.replace(str(workspace / ".cts-docs"), "<OUTPUT>")
    text = text.replace(str(workspace / "project-view"), "<PROJECT_VIEW>")
    text = text.replace(str(libraries), "<LIBRARY_ROOT>")
    return _GENERATED_AT_RE.sub(r'\1"<GENERATED_AT>"', text)


def _collect(workspace, libraries):
    """Generate the bundle and return ``{relative_path: normalized_text}``."""
    docgen.generate_docs(workspace, library_path=libraries)
    output = workspace / ".cts-docs"
    collected = {}
    for path in sorted(output.rglob("*")):
        if path.is_file():
            rel = path.relative_to(output).as_posix()
            collected[rel] = _normalize(
                path, path.read_text(encoding="utf-8"), workspace, libraries
            )
    return collected


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["files"]


def _first_difference(actual, expected):
    """Return a readable message for the first file that differs."""
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing files: " + ", ".join(missing))
        if extra:
            parts.append("unexpected files: " + ", ".join(extra))
        return "; ".join(parts)
    for name in sorted(expected):
        if actual[name] != expected[name]:
            diff = "\n".join(
                difflib.unified_diff(
                    expected[name].splitlines(),
                    actual[name].splitlines(),
                    fromfile="golden/" + name,
                    tofile="actual/" + name,
                    lineterm="",
                )
            )
            return f"first differing file: {name}\n{diff}"
    return "no difference"


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_docgen_bundle_matches_golden(tmp_path):
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)

    actual = _collect(workspace, libraries)

    if os.environ.get("UPDATE_DOCGEN_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps({"files": actual}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pytest.skip("golden updated")

    expected = _load_golden()
    assert actual == expected, _first_difference(actual, expected)

    # The bundle is a fixed set of artifacts: if a new one appears the golden
    # above already fails, but pin the shape explicitly for the report.
    assert set(actual) >= {
        "manifest.json",
        "index.md",
        "project.md",
        "symbols.jsonl",
        "sources.jsonl",
        "relations.jsonl",
        "diagnostics.jsonl",
        "libraries/not-referenced.md",
    }


def test_docgen_bundle_is_independent_of_the_workspace_path(tmp_path):
    """Two identical workspaces at different absolute paths emit the same bundle.

    This is the normalisation guard: an absolute path leaking into an artifact
    would make the bundles differ after ``_normalize``.
    """
    first = tmp_path / "one" / "sync"
    first.mkdir(parents=True)
    _p1, libs1 = _build_fixture(first)
    bundled_first = _collect(first, libs1)

    second = tmp_path / "two" / "sync"
    second.mkdir(parents=True)
    _p2, libs2 = _build_fixture(second)
    bundled_second = _collect(second, libs2)

    assert bundled_first == bundled_second, _first_difference(bundled_second, bundled_first)


def test_docgen_bundle_is_idempotent_on_regeneration(tmp_path):
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)

    first = _collect(workspace, libraries)
    second = _collect(workspace, libraries)

    assert first == second, _first_difference(second, first)


def test_check_docs_reports_fresh_then_stale(tmp_path):
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)
    docgen.generate_docs(workspace, library_path=libraries)

    fresh = docgen.check_docs(workspace)
    assert fresh["state"] == "fresh"
    assert fresh["exit_code"] == 0

    source = workspace / "project-view" / "POUs" / "Prg_Main.st"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n// touched\n", encoding="utf-8"
    )
    stale = docgen.check_docs(workspace)
    assert stale["state"] == "stale"
    assert stale["exit_code"] == 1


def test_validate_bundle_reports_only_the_expected_diagnostics(tmp_path):
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)
    docgen.generate_docs(workspace, library_path=libraries)

    diagnostics = docgen.validate_bundle(str(workspace / ".cts-docs"))
    codes = {diagnostic["code"] for diagnostic in diagnostics}

    assert codes == _EXPECTED_DIAGNOSTIC_CODES
    assert not (codes & _INTEGRITY_CODES)


def test_fixture_reaches_the_intended_branches(tmp_path):
    """Guard the fixture's branch coverage; a shrink here weakens the golden."""
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)
    manifest = docgen.generate_docs(workspace, library_path=libraries)["manifest"]
    counts = manifest["counts"]

    assert counts["project_pous"] == 15
    assert counts["library_pous"] == 1
    assert counts["libraries_referenced"] == 4
    assert counts["libraries_documented"] == 1
    assert counts["libraries_missing"] == 3
    assert counts["libraries_not_referenced"] == 1
    assert counts["diagnostic_errors"] == 1
    assert counts["diagnostic_warnings"] == 5

    reasons = {row["name"]: row["reason"] for row in manifest["libraries_missing"]}
    assert reasons == {
        "Demo": "exact_version_missing",
        "MissingLib": "documentation_package_absent",
        "WildLib": "wildcard_unresolved",
    }

    output = workspace / ".cts-docs"
    symbols = [
        json.loads(line)
        for line in (output / "symbols.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_name = {row["name"]: row for row in symbols}
    # Unresolved and cyclic EXTENDS both leave the relation, and the cyclic
    # case still terminates with a materialised inherited list.
    assert [m["name"] for m in by_name["ST_PosEx2"]["inherited_members"]] == ["z", "x", "y"]
    assert sorted(m["name"] for m in by_name["ST_CycA"]["inherited_members"]) == ["a", "b"]

    relations = [
        json.loads(line)
        for line in (output / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    kinds = {relation["kind"] for relation in relations}
    assert {"calls", "extends", "reachable_from_task", "reads_global", "writes_global"} <= kinds
    assert any(
        relation["resolution"] == "unresolved" and relation["kind"] == "extends"
        for relation in relations
    )
    assert any(
        relation["resolution"] == "unresolved" and relation["kind"] == "calls"
        for relation in relations
    )


# --------------------------------------------------------------------------
# Known current behaviour (pinned, not fixed here)
# --------------------------------------------------------------------------


def test_known_behaviour_bundle_is_written_inside_the_sync_folder(tmp_path):
    """Known current behaviour: the default bundle lands in ``<sync>/.cts-docs``.

    ``cts docs`` therefore writes a generated directory *inside* the folder the
    sync daemon watches.  That is pinned here so a future fix (moving the
    default outside the watched tree) is a deliberate, visible change; it is
    not fixed as part of the docgen characterization work.
    """
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)

    docgen.generate_docs(workspace, library_path=libraries)
    assert (workspace / ".cts-docs" / "manifest.json").is_file()

    # An explicit ``output`` outside the sync folder keeps it out of the tree.
    outside = tmp_path / "docs"
    docgen.generate_docs(workspace, library_path=libraries, output=outside)
    assert (outside / "manifest.json").is_file()


def test_known_behaviour_placeholder_redirections_are_ignored(tmp_path):
    """Known gap: only the Library Manager export is read, never the redirect table.

    ``explicit_library_references`` reads ``DefaultResolution`` from every
    Library Manager object.  The project's ``PlaceholderRedirectionTable``
    (which can point a placeholder at another library) is not consulted, so an
    installed library that is only reachable through a redirection is reported
    under ``libraries_not_referenced`` (``Standard`` in a real project) and a
    redirected reference is resolved against its un-redirected default.

    Reproducing this needs a real CODESYS project settings export, which the
    fixture does not carry, so the behaviour is asserted only in the negative:
    a library that no Library Manager mentions is reported unreferenced.
    """
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)

    docgen.generate_docs(workspace, library_path=libraries)
    not_referenced = (
        workspace / ".cts-docs" / "libraries" / "not-referenced.md"
    ).read_text(encoding="utf-8")
    assert "| Unused | 2.0.0, 2.1.0 |" in not_referenced


def test_known_behaviour_project_extensions_are_not_parsed_for_function_blocks(tmp_path):
    """Known gap: ``EXTENDS`` is only materialised for DUT/``TYPE`` units.

    ``_unit_section`` re-parses a unit through ``parse_dut`` only for the
    ``TYPE`` kinds, so ``FUNCTION_BLOCK FB_Motor EXTENDS FB_Base`` yields no
    ``extends`` relation and no inherited members, while the same relation on a
    ``STRUCT`` does.  Pinned so the future decomposition makes the asymmetry
    deliberate.
    """
    workspace = tmp_path / "sync"
    workspace.mkdir()
    _project, libraries = _build_fixture(workspace)
    docgen.generate_docs(workspace, library_path=libraries)

    symbols = [
        json.loads(line)
        for line in (workspace / ".cts-docs" / "symbols.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    motor = next(row for row in symbols if row["name"] == "FB_Motor")
    assert motor["declaration"].get("extends") is None
    assert motor["inherited_members"] == []
