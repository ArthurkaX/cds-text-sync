using System;
using System.IO;
using System.Linq;
using Cts.Docs;
using Xunit;

namespace Cts.Agent.Tests
{
    public class CliDocsTests : IDisposable
    {
        readonly string folder = Path.Combine(Path.GetTempPath(), "cts-docs-" + Path.GetRandomFileName());
        readonly string view;
        readonly string libraries;

        const string TonPage = "<html><body><div class=\"section\">"
            + "<h1><code class=\"docutils literal\"><span class=\"pre\">TON</span></code> (FB)<a class=\"headerlink\" href=\"#ton-fb\">¶</a></h1>"
            + "<p>FUNCTION_BLOCK TON</p><p>Implements a timer with a turn-on delay</p>"
            + "<div class=\"highlight\"><pre><span class=\"n\">TONInst</span>(IN := x, PT := T#5s);\n</pre></div>"
            + "<dl class=\"docutils\"><dt>InOut:</dt><dd><table><thead><tr><th>Scope</th><th>Name</th><th>Type</th><th>Comment</th></tr></thead><tbody>"
            + "<tr><td rowspan=\"2\">Input</td><td><code>IN</code></td><td>BOOL</td><td><div class=\"line\">Rising edge: starts</div><div class=\"line\">Falling edge: resets</div></td></tr>"
            + "<tr><td><code>PT</code></td><td>TIME</td><td>Delay &amp; more</td></tr>"
            + "<tr><td>Output</td><td><code>Q</code></td><td>BOOL</td><td>Done</td></tr>"
            + "</tbody></table></dd></dl></div></body></html>";

        const string GvlPage = "<html><body><div class=\"section\"><h1>Gc (GVL)</h1>"
            + "<p>Constants of the library</p>"
            + "<dl><dt>InOut:</dt><dd><table><thead><tr><th>Scope</th><th>Name</th><th>Type</th><th>Initial</th><th>Comment</th></tr></thead><tbody><tr><td>Constant</td><td>MAX</td><td>INT</td><td>16#FF</td><td>The limit</td></tr></tbody></table></dd></dl>"
            + "</div></body></html>";

        public CliDocsTests()
        {
            view = Path.Combine(folder, "sync", "project-view");
            libraries = Path.Combine(folder, "codesys");
            Directory.CreateDirectory(Path.Combine(view, "App", "Task Configuration"));
            Directory.CreateDirectory(libraries);
        }

        public void Dispose()
        {
            if (Directory.Exists(folder)) Directory.Delete(folder, true);
        }

        void Source(string path, string text) => File.WriteAllText(Path.Combine(view, path), text.Replace("\r\n", "\n"));

        void LibDocTree(string vendor, string name, string version, params (string title, string location, string html)[] pages)
        {
            var locale = Path.Combine(libraries, "LibDoc", vendor, name, version, "en");
            Directory.CreateDirectory(locale);
            var inventory = string.Join(",", pages.Select(page => "\"" + page.location + "\": {\"name\": \"" + page.title + "\", \"location\": \"" + page.location + "\"}"));
            File.WriteAllText(Path.Combine(locale, "manifest.json"), "{\"inventory\": {\"std:doc\": {" + inventory + ", \"index\": {\"name\": \"Contents\", \"location\": \"index.html\"}}}}");
            foreach (var page in pages)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Path.Combine(locale, page.location)));
                File.WriteAllText(Path.Combine(locale, page.location), page.html);
            }
        }

        void Project()
        {
            File.Copy(Path.Combine(AppContext.BaseDirectory, "Golden", "Docs", "Library Manager.xml"), Path.Combine(view, "App", "Library Manager.xml"));
            File.WriteAllText(Path.Combine(view, "App", "Task Configuration", "MainTask.xml"),
                "<Single><List Name=\"PouList\"><Single><Single Name=\"Name\" Type=\"string\">MAIN</Single></Single></List></Single>");
            Source("App/MAIN.st", @"// The plant's entry point.
PROGRAM MAIN
VAR
    fbDrive : FB_Drive;
END_VAR
// --- implementation ---
fbDrive(xEnable := GVL_Plant.xRun);
fbDrive.M_Reset();
GVL_Plant.nCycles := GVL_Plant.nCycles + 1;
");
            Source("App/FB_Base.st", @"(*
Base of every drive.
*)
FUNCTION_BLOCK FB_Base
VAR_INPUT
    xEnable : BOOL; // switch the drive on
END_VAR
VAR
    nCount : INT := 3;
END_VAR
// --- implementation ---
nCount := nCount + 1;
END_FUNCTION_BLOCK

// Clears the counter.
METHOD M_Clear : BOOL
// --- implementation ---
nCount := 0;
END_METHOD
");
            Source("App/FB_Drive.st", @"FUNCTION_BLOCK FB_Drive EXTENDS FB_Base IMPLEMENTS I_Drive
// A drive with a start delay.
VAR
    tonStart : TON;
END_VAR
// --- implementation ---
tonStart(IN := xEnable, PT := T#1S);
END_FUNCTION_BLOCK

PROPERTY P_Ready : BOOL
GET
// --- implementation ---
P_Ready := tonStart.Q;
END_GET
END_PROPERTY

METHOD M_Reset : BOOL
// --- implementation ---
M_Clear();
END_METHOD

ACTION A_Stop:
tonStart(IN := FALSE);
END_ACTION
");
            Source("App/I_Drive.st", "INTERFACE I_Drive\nEND_INTERFACE\n");
            Source("App/MAIN_Old.st", "(* cds-text-sync: ExcludeFromBuild *)\n// The former entry point.\nPROGRAM MAIN_Old\n// --- implementation ---\nEND_PROGRAM\n");
            Source("App/FB_Loop.st", "FUNCTION_BLOCK FB_Loop EXTENDS FB_Loop2\nVAR\n    a : INT;\nEND_VAR\nEND_FUNCTION_BLOCK\n");
            Source("App/FB_Loop2.st", "FUNCTION_BLOCK FB_Loop2 EXTENDS FB_Loop\nVAR\n    b : INT;\nEND_VAR\nEND_FUNCTION_BLOCK\n");
            Source("App/GVL_Plant.st", "VAR_GLOBAL\n    xRun : BOOL; // the line runs\n    nCycles : UDINT;\nEND_VAR\n");
            Source("App/ST_Point.st", "TYPE ST_Point :\nSTRUCT\n    x : REAL; // metres\n    y : REAL := 1.5;\nEND_STRUCT\nEND_TYPE\n");
            Directory.CreateDirectory(Path.Combine(view, ".hidden"));
            Source(".hidden/Ignored.st", "PROGRAM Ignored\nEND_PROGRAM\n");
        }

        [Fact]
        public void Docs_write_one_card_per_object_with_its_interface_members_and_relations()
        {
            Project();
            LibDocTree("System", "Standard", "3.5.22.0", ("TON (FB)", "x/TON.html", TonPage), ("Gc (GVL)", "x/Gc.html", GvlPage));

            var (code, output, _) = CliTests.RunLocal("docs", "--workspace", Path.Combine(folder, "sync"), "--libraries", libraries);

            Assert.True(code == 0, output);
            var bundle = Path.Combine(folder, "sync", ".cts-docs");
            Assert.Contains("ok docs out=" + bundle + " objects=9 libraries=7 documented=1 missing=6", output);
            Assert.Contains("6 referenced libraries have no LibDoc of that version on this machine", output);

            var drive = File.ReadAllText(Path.Combine(bundle, "project", "FB_Drive.md"));
            Assert.StartsWith("# FUNCTION_BLOCK FB_Drive\n\n`App/FB_Drive.st` line 1\n\nA drive with a start delay.\n\n- EXTENDS [FB_Base](FB_Base.md)\n- IMPLEMENTS [I_Drive](I_Drive.md)\n", drive);
            Assert.Contains("| VAR | tonStart | TON |  |  |", drive);
            Assert.Contains("| VAR_INPUT | xEnable | BOOL | [FB_Base](FB_Base.md) |", drive);
            Assert.Contains("| METHOD | M_Clear |  | [FB_Base](FB_Base.md) |", drive);
            Assert.Contains("- Calls: `TON (Standard 3.5.22.0)`", drive);
            Assert.Contains("- Called by: `MAIN`", drive);
            Assert.Contains("- Tasks: `MainTask`", drive);
            Assert.Contains("## PROPERTY P_Ready\n\nline 10\n\n| Scope | Name | Type | Initial | Comment |\n|---|---|---|---|---|\n| Return |  | BOOL |  |  |", drive);
            Assert.Contains("## METHOD M_Reset", drive);
            Assert.Contains("- Calls: `FB_Base.M_Clear`", drive);
            Assert.Contains("## ACTION A_Stop", drive);
            Assert.True(drive.IndexOf("## PROPERTY", StringComparison.Ordinal) < drive.IndexOf("## METHOD", StringComparison.Ordinal));

            var bas = File.ReadAllText(Path.Combine(bundle, "project", "FB_Base.md"));
            Assert.Contains("\nBase of every drive.\n", bas);
            Assert.Contains("| VAR_INPUT | xEnable | BOOL |  | switch the drive on |", bas);
            Assert.Contains("| VAR | nCount | INT | 3 |  |", bas);
            Assert.Contains("## METHOD M_Clear\n\nline 16\n\nClears the counter.", bas);
            Assert.Contains("- Called by: `FB_Drive.M_Reset`", bas);

            var main = File.ReadAllText(Path.Combine(bundle, "project", "MAIN.md"));
            Assert.Contains("The plant's entry point.", main);
            Assert.Contains("- Calls: `FB_Drive`, `FB_Drive.M_Reset`", main);
            Assert.Contains("- Reads: `GVL_Plant.nCycles`, `GVL_Plant.xRun`", main);
            Assert.Contains("- Writes: `GVL_Plant.nCycles`", main);

            // The object property is said as such; the pragma line is no description.
            Assert.StartsWith("# PROGRAM MAIN_Old\n\n`App/MAIN_Old.st` line 3\n\nExcluded from build: CODESYS does not compile it.\n\nThe former entry point.\n",
                File.ReadAllText(Path.Combine(bundle, "project", "MAIN_Old.md")));

            var gvl = File.ReadAllText(Path.Combine(bundle, "project", "GVL_Plant.md"));
            Assert.Contains("| VAR_GLOBAL | xRun | BOOL |  | the line runs |", gvl);
            Assert.Contains("- Read by: `MAIN`", gvl);
            Assert.Contains("- Written by: `MAIN`", gvl);
            Assert.Contains("| FIELD | y | REAL | 1.5 |  |", File.ReadAllText(Path.Combine(bundle, "project", "ST_Point.md")));

            // A base cycle ends the walk instead of looping forever.
            var loop = File.ReadAllText(Path.Combine(bundle, "project", "FB_Loop.md"));
            Assert.Contains("| VAR | b | INT | [FB_Loop2](FB_Loop2.md) |", loop);
            Assert.DoesNotContain("| VAR | a | INT | [FB_Loop", loop);
            Assert.False(File.Exists(Path.Combine(bundle, "project", "Ignored.md")));

            var index = File.ReadAllText(Path.Combine(bundle, "index.md"));
            Assert.Contains("| FUNCTION_BLOCK | [FB_Drive](project/FB_Drive.md) | `App/FB_Drive.st` |", index);
            Assert.Contains("| [Standard](libraries/Standard-3.5.22.0.md) | 3.5.22.0 | System |  | yes | 2 |", index);
            Assert.Contains("| PSVRetain | * | PSV Electro |  | documentation_package_absent |", index);

            var rows = File.ReadAllLines(Path.Combine(bundle, "symbols.jsonl")).Select(line => (System.Collections.Generic.IDictionary<string, object>)Json.Parse(line)).ToList();
            var reset = rows.Single(row => Equals(row["name"], "FB_Drive.M_Reset"));
            Assert.Equal("FB_Drive", reset["owner"]);
            Assert.Equal("project/FB_Drive.md", reset["card"]);
            Assert.False(reset.ContainsKey("description"));
            Assert.False(reset.ContainsKey("excluded_from_build"));
            Assert.Equal(true, rows.Single(row => Equals(row["name"], "MAIN_Old"))["excluded_from_build"]);
            var ton = rows.Single(row => Equals(row["source"], "library") && Equals(row["name"], "TON"));
            Assert.Equal("FUNCTION_BLOCK TON", ton["signature"]);
            Assert.Equal("libraries/Standard-3.5.22.0.md", ton["card"]);

            var manifest = (System.Collections.Generic.IDictionary<string, object>)Json.Parse(File.ReadAllText(Path.Combine(bundle, "manifest.json")));
            Assert.Equal("cts-docs/v4", manifest["format"]);
            Assert.Equal(6, ((System.Collections.IList)manifest["missing"]).Count);
        }

        [Fact]
        public void A_library_page_carries_signature_description_example_and_the_rowspan_table()
        {
            Project();
            LibDocTree("System", "Standard", "3.5.22.0", ("TON (FB)", "x/TON.html", TonPage), ("Gc (GVL)", "x/Gc.html", GvlPage));
            CliTests.RunLocal("docs", "--workspace", Path.Combine(folder, "sync"), "--libraries", libraries);

            var page = File.ReadAllText(Path.Combine(folder, "sync", ".cts-docs", "libraries", "Standard-3.5.22.0.md"));
            Assert.StartsWith("# Standard 3.5.22.0\n\n- Vendor: `System`\n- Reference: redirected `Standard`\n- System library\n", page);
            Assert.Contains("## FUNCTION_BLOCK TON\n\n```st\nFUNCTION_BLOCK TON\n```\n\nImplements a timer with a turn-on delay\n\n```st\nTONInst(IN := x, PT := T#5s);\n```\n", page);
            Assert.Contains("| Input | IN | BOOL |  | Rising edge: starts Falling edge: resets |", page);
            Assert.Contains("| Input | PT | TIME |  | Delay & more |", page);
            Assert.Contains("| Output | Q | BOOL |  | Done |", page);
            // A GVL page opens with its description, not a declaration.
            Assert.Contains("## GVL Gc\n\nConstants of the library\n", page);
            Assert.Contains("| Constant | MAX | INT | 16#FF | The limit |", page);
        }

        [Fact]
        public void Show_prints_one_symbol_by_its_bare_or_library_name_and_names_near_ones()
        {
            Project();
            LibDocTree("System", "Standard", "3.5.22.0", ("TON (FB)", "x/TON.html", TonPage), ("Gc (GVL)", "x/Gc.html", GvlPage));
            var workspace = Path.Combine(folder, "sync");

            var (code, output, _) = CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries, "--show", "Standard.TON");
            Assert.Equal(0, code);
            Assert.StartsWith("ok docs show=Standard.TON found=1\n# Standard 3.5.22.0\n## FUNCTION_BLOCK TON\n", output);
            Assert.Contains("| Output | Q | BOOL |  | Done |", output);
            Assert.False(Directory.Exists(Path.Combine(workspace, ".cts-docs")));
            Assert.StartsWith("ok docs show=standard found=2\n", CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries, "--show", "standard").output);

            (code, output, _) = CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries, "--show", "TO");
            Assert.Equal(1, code);
            Assert.Contains("no referenced library documents TO; names that hold it: TON.", output);
        }

        // A type of a library a referenced one depends on has no page; the
        // repository's browsercache says which installed library holds it.
        [Fact]
        public void Show_names_the_installed_library_that_holds_a_name_no_page_documents()
        {
            Project();
            void Cache(string version, string nodes)
            {
                var directory = Path.Combine(libraries, "Managed Libraries", "System", "SysTypes2 Interfaces", version);
                Directory.CreateDirectory(directory);
                File.WriteAllText(Path.Combine(directory, "browsercache"), "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<Library Name=\"SysTypes2 Interfaces, " + version + " (System)\">" + nodes + "</Library>");
            }
            Cache("3.5.4.0", "<Node Name=\"RTS_IEC_HANDLE\" /><Node Name=\"FB_Timer\"><Node Name=\"Execute\" /></Node>");
            Cache("3.5.10.0", "<Node Name=\"RTS_IEC_HANDLE\" />");
            var workspace = Path.Combine(folder, "sync");

            var (code, output, _) = CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries, "--show", "RTS_IEC_HANDLE");

            Assert.Equal(1, code);
            Assert.Contains("\nRTS_IEC_HANDLE is in SysTypes2 Interfaces, 3.5.10.0 (System), installed on this PC. Next: cts lib add \"SysTypes2 Interfaces, * (System)\" if the project does not reference it yet, then cts docs --show RTS_IEC_HANDLE", output);
            Assert.DoesNotContain(" is in ", CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries, "--show", "Execute").output);
        }

        // CODESYS writes pages only for a library in reStructuredText, and
        // only once a Library Manager shows it: its projectinfo says which.
        [Fact]
        public void A_library_with_no_pages_says_whether_its_comments_are_plain_text_or_its_pages_not_written_yet()
        {
            Project();
            void Installed(string vendor, string name, string version, params string[] strings)
            {
                var directory = Path.Combine(libraries, "Managed Libraries", vendor, name, version);
                Directory.CreateDirectory(directory);
                File.WriteAllBytes(Path.Combine(directory, "projectinfo"), strings.SelectMany(text => new byte[] { 7, 0 }.Concat(System.Text.Encoding.Unicode.GetBytes(text))).ToArray());
            }
            Installed("PSV Electro", "PSVRetain", "1.0.0.0", "Properties", "Company", "PSV Electro");
            Installed("System", "IoStandard", "3.5.16.0", "Properties", "DocFormat", "reStructuredText");
            Directory.CreateDirectory(Path.Combine(libraries, "LibDoc", "System", "IoStandard", "3.5.16.0", "Default"));
            var workspace = Path.Combine(folder, "sync");

            var (code, output, _) = CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries, "--show", "PSV_Retain");

            Assert.Equal(1, code);
            Assert.Contains("\nno pages for PSVRetain, *: its comments are plain text: CODESYS writes documentation pages only for a library whose Project Information sets DocFormat = reStructuredText", output);
            Assert.Contains("\nno pages for IoStandard, 3.5.16.0: it is documented in reStructuredText, but CODESYS has not written its pages yet", output);
            CliTests.RunLocal("docs", "--workspace", workspace, "--libraries", libraries);
            var index = File.ReadAllText(Path.Combine(workspace, ".cts-docs", "index.md"));
            Assert.Contains("| PSVRetain | * | PSV Electro |  | plain_text_library |", index);
            Assert.Contains("| IoStandard | 3.5.16.0 | System | IoStandard | libdoc_not_generated |", index);
        }

        [Fact]
        public void Missing_libdoc_says_why_and_another_version_never_stands_in()
        {
            Project();
            var none = CliTests.RunLocal("docs", "--workspace", Path.Combine(folder, "sync"), "--libraries", Path.Combine(folder, "nowhere"));
            Assert.Equal(0, none.code);
            Assert.Contains("| Standard | 3.5.22.0 | System | Standard | library_root_unavailable |", File.ReadAllText(Path.Combine(folder, "sync", ".cts-docs", "index.md")));

            LibDocTree("System", "Standard", "3.5.18.0", ("TON (FB)", "x/TON.html", TonPage));
            LibDocTree("System", "Unused", "1.0.0.0", ("TON (FB)", "x/TON.html", TonPage));
            LibDocTree("PSV Electro", "PSVRetain", "1.2.0.0", ("TON (FB)", "x/TON.html", TonPage));
            LibDocTree("PSV Electro", "PSVRetain", "1.10.0.0", ("TON (FB)", "x/TON.html", TonPage));
            Directory.CreateDirectory(Path.Combine(libraries, "LibDoc", "System", "IoStandard", "3.5.16.0"));
            var (code, output, _) = CliTests.RunLocal("docs", "--workspace", Path.Combine(folder, "sync"), "--libraries", libraries);
            Assert.True(code == 0, output);
            var bundle = Path.Combine(folder, "sync", ".cts-docs");
            var index = File.ReadAllText(Path.Combine(bundle, "index.md"));
            Assert.Contains("| Standard | 3.5.22.0 | System | Standard | exact_version_missing |", index);
            Assert.Contains("| IoStandard | 3.5.16.0 | System | IoStandard | documentation_package_absent |", index);
            // "*" takes the highest installed version, numerically.
            Assert.Contains("| [PSVRetain](libraries/PSVRetain-1.10.0.0.md) | 1.10.0.0 |", index);
            Assert.DoesNotContain("Standard-3.5.18.0", index);
            Assert.Equal("# Installed libraries the project does not reference\n\n| Library | Versions |\n|---|---|\n| Unused | 1.0.0.0 |\n",
                File.ReadAllText(Path.Combine(bundle, "libraries", "not-referenced.md")));
        }

        [Fact]
        public void Check_tells_a_fresh_bundle_from_a_stale_one()
        {
            Project();
            LibDocTree("System", "Standard", "3.5.22.0", ("TON (FB)", "x/TON.html", TonPage));
            var sync = Path.Combine(folder, "sync");
            var out_ = Path.Combine(folder, "bundle");

            var missing = CliTests.RunLocal("docs", "--workspace", sync, "--out", out_, "--check");
            Assert.Equal(2, missing.code);
            Assert.Contains("state=unreadable", missing.output);

            Assert.Equal(0, CliTests.RunLocal("docs", "--workspace", view, "--libraries", libraries, "--out", out_).code);
            var fresh = CliTests.RunLocal("docs", "--workspace", sync, "--out", out_, "--check");
            Assert.True(fresh.code == 0, fresh.output);
            Assert.Contains("ok docs state=fresh", fresh.output);

            Source("App/GVL_Plant.st", "VAR_GLOBAL\n    xRun : BOOL;\nEND_VAR\n");
            var stale = CliTests.RunLocal("docs", "--workspace", sync, "--out", out_, "--check");
            Assert.Equal(1, stale.code);
            Assert.Contains("state=stale", stale.output);

            Assert.Equal(0, CliTests.RunLocal("docs", "--workspace", sync, "--libraries", libraries, "--out", out_).code);
            Assert.Equal(0, CliTests.RunLocal("docs", "--workspace", sync, "--out", out_, "--check").code);
            File.AppendAllText(Path.Combine(libraries, "LibDoc", "System", "Standard", "3.5.22.0", "en", "x", "TON.html"), " ");
            Assert.Equal(1, CliTests.RunLocal("docs", "--workspace", sync, "--out", out_, "--check").code);
            // The staging and backup folders are gone after each write.
            Assert.Equal(new[] { "bundle", "codesys", "sync" }, Directory.GetDirectories(folder).Select(Path.GetFileName).OrderBy(name => name).ToArray());
        }

        [Fact]
        public void Placeholders_resolving_to_one_library_version_share_one_page()
        {
            string Placeholder(string name) => "<Single Type=\"{4723ebe7-5bfc-43c6-be6b-5097002ef6b4}\" Method=\"IArchivable\">"
                + "<Single Name=\"DefaultResolution\" Type=\"string\">" + name + ", * (System)</Single>"
                + "<Single Name=\"PlaceholderName\" Type=\"string\">" + name + "</Single>"
                + "<Single Name=\"Namespace\" Type=\"string\">" + name + "</Single>"
                + "<Single Name=\"SystemLibrary\" Type=\"bool\">True</Single></Single>";
            string Redirect(string name) => "<Entry><Key><Single Type=\"string\">" + name + "</Single></Key>"
                + "<Value><Single Type=\"string\">NotImplementedByDevice, 3.5.17.0 (System)</Single></Value></Entry>";
            File.WriteAllText(Path.Combine(view, "App", "Library Manager.xml"),
                "<Single><Single Name=\"MetaObject\"><Single Name=\"TypeGuid\" Type=\"System.Guid\">adb5cb65-8e1d-4a00-b70a-375ea27582f3</Single></Single>"
                + "<Single Name=\"Object\" Type=\"{adb5cb65-8e1d-4a00-b70a-375ea27582f3}\"><List Name=\"Items\">" + Placeholder("CmpLog") + Placeholder("CmpApp") + "</List>"
                + "<Dictionary Name=\"PlaceholderRedirectionTable\">" + Redirect("CmpLog") + Redirect("CmpApp") + "</Dictionary></Single></Single>");
            LibDocTree("System", "NotImplementedByDevice", "3.5.17.0", ("TON (FB)", "x/TON.html", TonPage));

            var (code, output, _) = CliTests.RunLocal("docs", "--workspace", Path.Combine(folder, "sync"), "--libraries", libraries);

            Assert.True(code == 0, output);
            Assert.True(output.Contains("libraries=2 documented=2 missing=0"), output);
            var bundle = Path.Combine(folder, "sync", ".cts-docs");
            var index = File.ReadAllText(Path.Combine(bundle, "index.md"));
            Assert.Single(index.Split('\n'), line => line.StartsWith("| [NotImplementedByDevice]", StringComparison.Ordinal));
            Assert.Contains("| CmpLog, CmpApp | yes | 1 |", index);
            var page = File.ReadAllText(Path.Combine(bundle, "libraries", "NotImplementedByDevice-3.5.17.0.md"));
            Assert.Contains("- Namespace: `CmpLog`, `CmpApp`\n- Reference: redirected `CmpLog`, redirected `CmpApp`\n", page);
            Assert.Single(File.ReadAllLines(Path.Combine(bundle, "symbols.jsonl")), line => line.Contains("\"name\":\"TON\""));
        }

        [Fact]
        public void A_redirection_table_points_only_its_own_managers_placeholders()
        {
            string Manager(string items, string table) => "<Single><Single Name=\"MetaObject\"><Single Name=\"TypeGuid\" Type=\"System.Guid\">adb5cb65-8e1d-4a00-b70a-375ea27582f3</Single></Single>"
                + "<Single Name=\"Object\" Type=\"{adb5cb65-8e1d-4a00-b70a-375ea27582f3}\"><List Name=\"Items\">" + items + "</List>"
                + "<Dictionary Name=\"PlaceholderRedirectionTable\">" + table + "</Dictionary></Single></Single>";
            const string CmpLog = "<Single Type=\"{4723ebe7-5bfc-43c6-be6b-5097002ef6b4}\" Method=\"IArchivable\">"
                + "<Single Name=\"DefaultResolution\" Type=\"string\">CmpLog, * (System)</Single><Single Name=\"PlaceholderName\" Type=\"string\">CmpLog</Single>"
                + "<Single Name=\"Namespace\" Type=\"string\">CmpLog</Single></Single>";
            const string Missing = "<Entry><Key><Single Type=\"string\">CmpLog</Single></Key><Value><Single Type=\"string\">NotImplementedByDevice, 3.5.17.0 (System)</Single></Value></Entry>";
            var root = Path.Combine(Path.GetTempPath(), "cts-libs-" + Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(Path.Combine(root, "A"));
                Directory.CreateDirectory(Path.Combine(root, "B"));
                File.WriteAllText(Path.Combine(root, "A", "Library Manager.xml"), Manager(CmpLog, ""));
                File.WriteAllText(Path.Combine(root, "B", "Library Manager.xml"), Manager(CmpLog, Missing));

                var references = LibraryReferences.Read(root, out _);

                Assert.Equal(new[] { "CmpLog placeholder", "NotImplementedByDevice redirected" }, references.Select(r => r.Name + " " + r.Kind));
            }
            finally
            {
                Directory.Delete(root, true);
            }
        }

        [Fact]
        public void The_library_manager_export_names_every_reference_with_its_kind()
        {
            var references = LibraryReferences.Read(Path.Combine(AppContext.BaseDirectory, "Golden", "Docs"), out var gap);

            Assert.Null(gap);
            Assert.Equal(new[] { "Breakpoint Logging Functions", "CAA Device Diagnosis", "IoStandard", "3SLicense" }.OrderBy(name => name),
                references.Where(r => r.Kind == "placeholder").Select(r => r.Name).OrderBy(name => name));
            Assert.Equal(new[] { "PSVLeds", "PSVRetain" }, references.Where(r => r.Kind == "concrete").Select(r => r.Name).OrderBy(name => name));
            var retain = references.Single(r => r.Name == "PSVRetain");
            Assert.Equal(("*", "PSV Electro", "PSVRetain", true), (retain.Version, retain.Vendor, retain.Namespace, retain.System));
            var logging = references.Single(r => r.Name == "Breakpoint Logging Functions");
            Assert.Equal(("BreakpointLogging", "*", "3S - Smart Software Solutions GmbH"), (logging.Placeholder, logging.Version, logging.Vendor));
            var standard = references.Single(r => r.Name == "Standard");
            Assert.Equal(("redirected", "3.5.22.0", "System", "Standard", true), (standard.Kind, standard.Version, standard.Vendor, standard.Placeholder, standard.System));
        }
    }
}
