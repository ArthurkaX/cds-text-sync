"""Tests for the compact documentation generator (``cts-docs/v3``).

The generator must never emit raw source text, must document only the
libraries the project actually references, and must report an unresolved
reference instead of quietly substituting another version.
"""

import json

import pytest

from cds_text_sync import docgen


FB_SENSOR_ST = """\
FUNCTION_BLOCK FB_Sensor
(*
    Standard sensor service block.
    - Debounces a raw discrete sensor signal
*)
VAR_INPUT
\ti_xRaw      : BOOL;          // Raw sensor signal
\ti_tDebounce : TIME := T#3MS; // Debounce filter time
END_VAR
VAR_OUTPUT
\tQ : BOOL;                    // Debounced state
END_VAR

IF i_xRaw THEN
\tQ := TRUE;
END_IF
"""

METHOD_ST = """\
(*
Add new record in logfile
*)

// LOG-file path: /var/log/plc.log

METHOD LogADD : BOOL
VAR_INPUT
\tMessage : STRING := 'something happened';
END_VAR

Log(Message);
"""

GVL_ST = """\
{attribute 'qualified_only'}
VAR_GLOBAL
\ttDebounce : TIME := T#3MS;  // Shared debounce time
END_VAR
"""

ENUM_ST = """\
TYPE E_PartRoute :
(
\tROUTE_LEFT := 1,
\tROUTE_RIGHT := 2
) UINT;
END_TYPE
"""


def _library_manager_xml(entries):
    """Render a Library Manager sync-node carrying *entries*."""
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


POU_PAGE_HTML = """\
<html><body>
<h1>FB_Demo (FB)<a class="headerlink" href="#">¶</a></h1>
<p>FUNCTION_BLOCK FB_Demo</p>
<p>Demo block used by the tests.</p>
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


def _make_libdoc(root, vendor, name, version, locale="en"):
    """Create a minimal but realistic LibDoc tree for one library."""
    locale_dir = root / "LibDoc" / vendor / name / version / locale
    locale_dir.mkdir(parents=True)
    (locale_dir / "fb_demo.html").write_text(POU_PAGE_HTML, encoding="utf-8")
    manifest = {
        "library": {"company": vendor, "title": name, "version": version},
        "inventory": {
            "std:doc": {
                "fb_demo": {"location": "fb_demo.html", "name": "FB_Demo (FB)"},
                "index": {"location": "index.html", "name": "Index"},
            }
        },
    }
    (locale_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return locale_dir


def _read_output(workspace):
    output = workspace / ".cts-docs"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    symbols = [
        json.loads(line)
        for line in (output / "symbols.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return output, manifest, symbols


def test_project_pous_carry_description_and_interface_without_source(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "FB_Sensor.st").write_text(FB_SENSOR_ST, encoding="utf-8")
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    result = docgen.generate_docs(workspace, library_path=libraries)
    output, manifest, symbols = _read_output(workspace)

    assert result["ok"] is True
    assert result["output"] == str(output)
    assert manifest["format"] == "cts-docs/v3"
    assert manifest["input_fingerprint"]
    assert manifest["sources"] == "sources.jsonl"
    assert manifest["diagnostics"] == "diagnostics.jsonl"
    assert manifest["relations"] == "relations.jsonl"
    assert manifest["counts"]["project_pous"] == 1

    symbol = symbols[0]
    assert symbol["source"] == "project"
    assert (symbol["kind"], symbol["name"]) == ("FUNCTION_BLOCK", "FB_Sensor")
    assert symbol["path"] == "FB_Sensor.st"
    assert symbol["id"].startswith("project::function_block::")
    assert symbol["source_ref"]["id"].startswith("source:project:")
    assert symbol["card"].startswith("project/")
    assert symbol["behavior"]["status"] == "partial"
    assert "Standard sensor service block." in symbol["description"]
    assert "Debounces a raw discrete sensor signal" in symbol["description"]
    rows = {row["name"]: row for row in symbol["interface"]}
    assert rows["i_xRaw"]["scope"] == "VAR_INPUT"
    assert rows["i_xRaw"]["comment"] == "Raw sensor signal"
    assert rows["i_tDebounce"]["initial"] == "T#3MS"
    assert rows["Q"]["scope"] == "VAR_OUTPUT"

    # The implementation body must not travel into any artifact.
    project_md = (output / "project.md").read_text(encoding="utf-8")
    index_md = (output / "index.md").read_text(encoding="utf-8")
    assert "[Project symbol index](project.md)" in index_md
    assert (output / symbol["card"]).is_file()
    card_text = (output / symbol["card"]).read_text(encoding="utf-8")
    assert symbol["name"] in card_text
    assert "[Back to index](../index.md)" in card_text
    assert "Q := TRUE;" not in project_md
    assert "END_VAR" not in project_md
    assert not (output / "bundle.md").exists()
    assert "Q := TRUE;" not in (output / "symbols.jsonl").read_text(encoding="utf-8")
    sources = [
        json.loads(line)
        for line in (output / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert sources[0]["path"] == "FB_Sensor.st"
    assert len(sources[0]["sha256"]) == 64


def test_methods_gvls_and_duts_are_documented(tmp_path):
    project = tmp_path / "project-view"
    project.mkdir()
    (project / "FB_Logger.LogADD.st").write_text(METHOD_ST, encoding="utf-8")
    (project / "GVL_Sensors.st").write_text(GVL_ST, encoding="utf-8")
    (project / "E_PartRoute.st").write_text(ENUM_ST, encoding="utf-8")
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project, library_path=libraries)
    _output, manifest, symbols = _read_output(tmp_path)
    by_name = {symbol["name"]: symbol for symbol in symbols}

    assert manifest["counts"]["project_pous"] == 3

    # A method file names the POU after its `Parent.Method.st` stem, and both
    # comment blocks above the header belong to it - not just the nearest one.
    method = by_name["FB_Logger.LogADD"]
    assert method["kind"] == "METHOD"
    assert "Add new record in logfile" in method["description"]
    assert "LOG-file path: /var/log/plc.log" in method["description"]

    # A GVL has no header at all; it is named after the file.
    gvl = by_name["GVL_Sensors"]
    assert gvl["kind"] == "GVL"
    assert gvl["interface"][0]["scope"] == "VAR_GLOBAL"
    assert gvl["interface"][0]["comment"] == "Shared debounce time"

    # A TYPE is re-typed through parse_dut and its fields become FIELD rows.
    enum = by_name["E_PartRoute"]
    assert enum["kind"] == "ENUM"
    assert [row["name"] for row in enum["interface"]] == ["ROUTE_LEFT", "ROUTE_RIGHT"]
    assert enum["interface"][0]["scope"] == "FIELD"


def test_referenced_library_is_documented_with_rowspan_scopes(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Library Manager.xml").write_text(
        _library_manager_xml(
            [
                {
                    "resolution": "Demo, 1.2.3.4 (Acme)",
                    "placeholder": "Demo",
                    "namespace": "DEMO",
                    "system": "True",
                }
            ]
        ),
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    _make_libdoc(libraries, "Acme", "Demo", "1.2.3.4")

    docgen.generate_docs(workspace, library_path=libraries)
    output, manifest, symbols = _read_output(workspace)

    assert manifest["counts"]["libraries_referenced"] == 1
    assert manifest["counts"]["libraries_documented"] == 1
    assert manifest["counts"]["library_pous"] == 1
    assert manifest["libraries_missing"] == []

    symbol = symbols[0]
    assert symbol["source"] == "library"
    assert (symbol["library"], symbol["version"]) == ("Demo", "1.2.3.4")
    assert symbol["name"] == "FB_Demo"
    assert symbol["kind"] == "FB"
    assert symbol["description"].startswith("Demo block used by the tests.")

    # The Scope cell spans two rows in the HTML; without carry-forward the
    # second parameter would silently land in the wrong scope.
    scopes = [(row["name"], row["scope"]) for row in symbol["interface"]]
    assert scopes == [("xEnable", "Input"), ("tTimeout", "Input"), ("xDone", "Output")]

    library_md = (output / "libraries" / "Demo-1.2.3.4.md").read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_Demo" in library_md
    assert "system library" in library_md


def test_project_call_resolves_to_exact_library_symbol(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\nFB_Demo();\n", encoding="utf-8"
    )
    (project / "Library Manager.xml").write_text(
        _library_manager_xml(
            [{
                "resolution": "Demo, 1.2.3.4 (Acme)",
                "placeholder": "Demo",
                "namespace": "DEMO",
                "system": "True",
            }]
        ),
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    _make_libdoc(libraries, "Acme", "Demo", "1.2.3.4")

    docgen.generate_docs(workspace, library_path=libraries)
    output, manifest, _symbols = _read_output(workspace)
    relations = [
        json.loads(line)
        for line in (output / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    calls = [relation for relation in relations if relation["kind"] == "calls"]
    assert len(calls) == 1
    assert calls[0]["from"].startswith("project::program::")
    assert calls[0]["to"].startswith("library::fb::")
    assert calls[0]["resolution"] == "exact"
    assert manifest["counts"]["diagnostic_errors"] == 0


def test_integration_project_task_exact_and_missing_libdoc(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\nFB_Demo();\nEND_PROGRAM\n",
        encoding="utf-8",
    )
    (project / "Task Configuration.xml").write_text(
        "<Single><List Name=\"PouList\"><Single>"
        "<Single Name=\"Name\">Main</Single>"
        "</Single></List></Single>",
        encoding="utf-8",
    )
    (project / "Library Manager.xml").write_text(
        _library_manager_xml([
            {
                "resolution": "Demo, 1.2.3.4 (Acme)",
                "placeholder": "Demo",
                "namespace": "DEMO",
                "system": "True",
            },
            {
                "resolution": "Missing, 9.9.9.9 (Acme)",
                "placeholder": "Missing",
                "namespace": "MISSING",
                "system": "True",
            },
        ]),
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    _make_libdoc(libraries, "Acme", "Demo", "1.2.3.4")

    docgen.generate_docs(workspace, library_path=libraries)
    output, manifest, symbols = _read_output(workspace)
    relations = [
        json.loads(line)
        for line in (output / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    main = next(row for row in symbols if row["name"] == "Main")
    assert manifest["counts"]["project_pous"] == 1
    assert manifest["libraries_missing"][0]["name"] == "Missing"
    assert any(
        relation["kind"] == "reachable_from_task"
        and relation["to"] == main["id"]
        and relation["from"] == "external::task:Task Configuration"
        for relation in relations
    )
    calls = [relation for relation in relations if relation["kind"] == "calls"]
    assert calls[0]["resolution"] == "exact"
    assert calls[0]["to"].startswith("library::fb::")


def test_qualified_namespace_call_resolves_to_exact_library_symbol(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\nDEMO.FB_Demo();\n", encoding="utf-8"
    )
    (project / "Library Manager.xml").write_text(
        _library_manager_xml([{
            "resolution": "Demo, 1.2.3.4 (Acme)",
            "placeholder": "Demo",
            "namespace": "DEMO",
            "system": "True",
        }]),
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    _make_libdoc(libraries, "Acme", "Demo", "1.2.3.4")

    docgen.generate_docs(workspace, library_path=libraries)
    output, _manifest, _symbols = _read_output(workspace)
    relations = [
        json.loads(line)
        for line in (output / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    calls = [relation for relation in relations if relation["kind"] == "calls"]
    assert len(calls) == 1
    assert calls[0]["resolution"] == "exact"
    assert calls[0]["confidence"] == "high"
    assert calls[0]["to"].startswith("library::fb::")


def test_unresolved_reference_is_reported_not_substituted(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Library Manager.xml").write_text(
        _library_manager_xml(
            [
                {
                    "resolution": "VisuElems, 4.9.1.0 (System)",
                    "placeholder": "System_VisuElems",
                    "namespace": "VisuElems",
                    "system": "True",
                }
            ]
        ),
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    # An unrelated library is installed; it must not be used as a stand-in and
    # must not be exported either - it is merely listed as not referenced.
    _make_libdoc(libraries, "Acme", "Demo", "1.2.3.4")

    docgen.generate_docs(workspace, library_path=libraries)
    output, manifest, symbols = _read_output(workspace)

    assert manifest["counts"]["libraries_referenced"] == 1
    assert manifest["counts"]["libraries_documented"] == 0
    assert manifest["libraries_missing"] == [
        {
            "name": "VisuElems",
            "version": "4.9.1.0",
            "vendor": "System",
            "placeholder": "System_VisuElems",
            "reason": "documentation_package_absent",
        }
    ]
    assert symbols == []
    assert not list(
        (output / "libraries").glob("*.md")
    ) or list((output / "libraries").glob("*.md")) == [
        output / "libraries" / "not-referenced.md"
    ]

    index = (output / "index.md").read_text(encoding="utf-8")
    assert "## Missing LibDoc" in index
    assert "VisuElems" in index
    assert "libraries/not-referenced.md" in index
    not_referenced = (output / "libraries" / "not-referenced.md").read_text(encoding="utf-8")
    # The installed-but-unreferenced library is named, never expanded.
    assert manifest["counts"]["libraries_not_referenced"] == 1
    assert "Demo" in not_referenced
    assert "FB_Demo" not in not_referenced


def test_missing_default_library_path_is_recorded(tmp_path, monkeypatch):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "E_PartRoute.st").write_text(ENUM_ST, encoding="utf-8")
    missing = tmp_path / "missing-libraries"
    monkeypatch.setattr(docgen, "DEFAULT_LIBRARY_PATH", missing)

    result = docgen.generate_docs(project_view)
    _output, manifest, _symbols = _read_output(tmp_path)

    assert result["ok"] is True
    assert manifest["project_view"] == str(project_view)
    assert manifest["library_path_exists"] is False
    assert manifest["counts"]["project_pous"] == 1
    assert manifest["counts"]["library_pous"] == 0
    # No Library Manager at all is a gap worth reporting, not silence.
    assert manifest["gaps"]


def test_stale_bundle_is_removed_on_regeneration(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "FB_Sensor.st").write_text(FB_SENSOR_ST, encoding="utf-8")
    output = tmp_path / ".cts-docs"
    output.mkdir()
    (output / "bundle.md").write_text("stale v1 source dump", encoding="utf-8")
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)

    assert not (output / "bundle.md").exists()


def test_check_docs_distinguishes_fresh_and_stale_sources(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    source = project_view / "FB_Sensor.st"
    source.write_text(FB_SENSOR_ST, encoding="utf-8")
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)
    fresh = docgen.check_docs(project_view)
    assert fresh["state"] == "fresh"
    assert fresh["exit_code"] == 0

    source.write_text(FB_SENSOR_ST + "\n// changed\n", encoding="utf-8")
    stale = docgen.check_docs(project_view)
    assert stale["state"] == "stale"
    assert stale["exit_code"] == 1


def test_check_docs_detects_changed_library_doc(tmp_path):
    workspace = tmp_path / "sync"
    project = workspace / "project-view"
    project.mkdir(parents=True)
    (project / "Library Manager.xml").write_text(
        _library_manager_xml([{
            "resolution": "Demo, 1.2.3.4 (Acme)",
            "placeholder": "Demo",
            "namespace": "DEMO",
            "system": "True",
        }]),
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    locale_dir = _make_libdoc(libraries, "Acme", "Demo", "1.2.3.4")

    docgen.generate_docs(workspace, library_path=libraries)
    assert docgen.check_docs(workspace)["state"] == "fresh"
    (locale_dir / "fb_demo.html").write_text(
        POU_PAGE_HTML.replace("Demo block", "Changed block"), encoding="utf-8"
    )

    assert docgen.check_docs(workspace)["state"] == "stale"


def test_docgen_is_deterministic_except_generated_at(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\n", encoding="utf-8"
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)
    output = tmp_path / ".cts-docs"
    first = {
        path.name: path.read_text(encoding="utf-8")
        for path in output.rglob("*") if path.is_file()
    }
    first_manifest = json.loads(first["manifest.json"])
    first_manifest.pop("generated_at")
    first["manifest.json"] = json.dumps(first_manifest, indent=2) + "\n"

    docgen.generate_docs(project_view, library_path=libraries)
    second = {
        path.name: path.read_text(encoding="utf-8")
        for path in output.rglob("*") if path.is_file()
    }
    second_manifest = json.loads(second["manifest.json"])
    second_manifest.pop("generated_at")
    second["manifest.json"] = json.dumps(second_manifest, indent=2) + "\n"

    assert first == second


def test_failed_generation_keeps_previous_bundle(tmp_path, monkeypatch):
    output = tmp_path / ".cts-docs"
    output.mkdir()
    marker = output / "manifest.json"
    marker.write_text('{"format": "old"}\n', encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic generation failure")

    monkeypatch.setattr(docgen, "_generate_docs", fail)
    with pytest.raises(RuntimeError, match="synthetic generation failure"):
        docgen.generate_docs(tmp_path, output=output)

    assert json.loads(marker.read_text(encoding="utf-8"))["format"] == "old"


def test_docgen_exports_project_call_relations_without_source_body(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\nCallMe();\n", encoding="utf-8"
    )
    (project_view / "CallMe.st").write_text(
        "FUNCTION CallMe : BOOL\nIMPLEMENTATION\nCallMe := TRUE;\n", encoding="utf-8"
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)
    output = tmp_path / ".cts-docs"
    relations = [
        json.loads(line)
        for line in (output / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    calls = [relation for relation in relations if relation["kind"] == "calls"]
    assert len(calls) == 1
    assert calls[0]["from"].startswith("project::program::")
    assert calls[0]["to"].startswith("project::function::")
    assert calls[0]["site"]["line"] == 3
    assert "CallMe := TRUE;" not in (output / "symbols.jsonl").read_text(encoding="utf-8")


def test_docgen_exports_global_read_write_relations(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "Globals.st").write_text(
        "VAR_GLOBAL\nShared : INT;\nEND_VAR\n", encoding="utf-8"
    )
    (project_view / "Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\nGlobals.Shared := 1;\n"
        "IF Globals.Shared > 0 THEN\nEND_IF;\n", encoding="utf-8"
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)
    output = tmp_path / ".cts-docs"
    relations = [
        json.loads(line)
        for line in (output / "relations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    global_relations = [
        relation for relation in relations
        if relation["kind"] in ("reads_global", "writes_global")
    ]

    assert [relation["kind"] for relation in global_relations] == [
        "reads_global", "writes_global"
    ]
    assert all(relation["to"] == "external::global:Globals.Shared" for relation in global_relations)
    assert all(relation["site"]["source_id"].startswith("source:project:") for relation in global_relations)


def test_docgen_jsonl_and_markdown_are_deterministic(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    # Create files in reverse logical order to exercise the snapshot sort.
    (project_view / "Z_Main.st").write_text(
        "PROGRAM Main\nIMPLEMENTATION\n", encoding="utf-8"
    )
    (project_view / "A_Helper.st").write_text(
        "FUNCTION Helper : BOOL\nIMPLEMENTATION\nHelper := TRUE;\n", encoding="utf-8"
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    first = tmp_path / "docs-one"
    second = tmp_path / "docs-two"
    docgen.generate_docs(project_view, library_path=libraries, output=first)
    docgen.generate_docs(project_view, library_path=libraries, output=second)

    for name in (
        "symbols.jsonl", "sources.jsonl", "relations.jsonl", "diagnostics.jsonl",
        "project.md", "index.md",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    first_manifest.pop("generated_at")
    second_manifest.pop("generated_at")
    assert first_manifest == second_manifest


def test_docgen_keeps_multiple_top_level_pous_in_one_source_file(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "Combined.st").write_text(
        "PROGRAM First\nIMPLEMENTATION\nEND_PROGRAM\n\n"
        "PROGRAM Second\nIMPLEMENTATION\nEND_PROGRAM\n",
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)
    output, manifest, symbols = _read_output(tmp_path)

    project_rows = [row for row in symbols if row["source"] == "project"]
    assert {row["name"] for row in project_rows} == {"First", "Second"}
    assert manifest["counts"]["project_pous"] == 2
    assert len((output / "project.md").read_text(encoding="utf-8").splitlines()) > 5


def test_docgen_materializes_inherited_dut_members(tmp_path):
    project_view = tmp_path / "project-view"
    project_view.mkdir()
    (project_view / "Base.st").write_text(
        "TYPE Base : STRUCT\n    xBase : INT;\nEND_STRUCT END_TYPE\n",
        encoding="utf-8",
    )
    (project_view / "Child.st").write_text(
        "TYPE Child EXTENDS Base : STRUCT\n    xChild : BOOL;\nEND_STRUCT END_TYPE\n",
        encoding="utf-8",
    )
    libraries = tmp_path / "codesys"
    libraries.mkdir()

    docgen.generate_docs(project_view, library_path=libraries)
    _output, _manifest, symbols = _read_output(tmp_path)

    child = next(row for row in symbols if row["name"] == "Child")
    assert [member["name"] for member in child["own_members"]] == ["xChild"]
    assert [member["name"] for member in child["inherited_members"]] == ["xBase"]
    assert child["inherited_members"][0]["inherited_from"] == "Base"
