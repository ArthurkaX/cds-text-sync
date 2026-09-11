"""Tests for the compact documentation generator (``cts-docs/v2``).

The generator must never emit raw source text, must document only the
libraries the project actually references, and must report an unresolved
reference instead of quietly substituting another version.
"""

import json

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
    assert manifest["format"] == "cts-docs/v2"
    assert manifest["counts"]["project_pous"] == 1

    symbol = symbols[0]
    assert symbol["source"] == "project"
    assert (symbol["kind"], symbol["name"]) == ("FUNCTION_BLOCK", "FB_Sensor")
    assert symbol["path"] == "FB_Sensor.st"
    assert "Standard sensor service block." in symbol["description"]
    assert "Debounces a raw discrete sensor signal" in symbol["description"]
    rows = {row["name"]: row for row in symbol["interface"]}
    assert rows["i_xRaw"]["scope"] == "VAR_INPUT"
    assert rows["i_xRaw"]["comment"] == "Raw sensor signal"
    assert rows["i_tDebounce"]["initial"] == "T#3MS"
    assert rows["Q"]["scope"] == "VAR_OUTPUT"

    # The implementation body must not travel into any artifact.
    project_md = (output / "project.md").read_text(encoding="utf-8")
    assert "Q := TRUE;" not in project_md
    assert "END_VAR" not in project_md
    assert not (output / "bundle.md").exists()


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
        }
    ]
    assert symbols == []
    assert not (output / "libraries").exists() or not list(
        (output / "libraries").glob("*.md")
    )

    index = (output / "index.md").read_text(encoding="utf-8")
    assert "## Missing LibDoc" in index
    assert "VisuElems" in index
    # The installed-but-unreferenced library is named, never expanded.
    assert manifest["counts"]["libraries_not_referenced"] == 1
    assert "Demo" in index.split("## Not referenced", 1)[1]
    assert "FB_Demo" not in index


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
