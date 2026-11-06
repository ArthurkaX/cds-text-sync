using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ObjectCliTests
    {
        [Fact]
        public void New_writes_a_gvl_at_the_export_view_path()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                var command = CliCommands.Find(new[] { "new" });
                var options = CliOptions.Parse(new[] { "new", "gvl", "GVL_Test", "--sync-folder", root, "--text", "x : BOOL;" }, null, command);
                var result = command.LocalExecute(options, null, root);
                var path = Path.Combine(root, "project-view", "Application", "GVL_Test.st");
                Assert.Equal("Application/GVL_Test.st", result["path"]);
                Assert.Equal(path, ((System.Collections.Generic.List<string>)result["files"])[0]);
                Assert.Equal("VAR_GLOBAL\n    x : BOOL;\nEND_VAR\n", File.ReadAllText(path));
                Assert.Equal("gvl", result["kind"]);
                Assert.DoesNotContain("cts test", (string)result["hint"]);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void New_adds_a_method_to_the_owner_st_as_the_export_writes_it()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-member-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                Create(root, "pou", "FB_Test", "--kind", "function-block");
                Create(root, "method", "FB_Test.M_Run", "--text", "xDone := TRUE;");
                var text = File.ReadAllText(Path.Combine(root, "project-view", "Application", "FB_Test.st"));
                Assert.Contains("\n\nMETHOD M_Run : BOOL\n// --- implementation ---\nxDone := TRUE;\nEND_METHOD\n", text);
                Create(root, "action", "FB_Test.A_Reset", "--text", "xDone := FALSE;");
                text = File.ReadAllText(Path.Combine(root, "project-view", "Application", "FB_Test.st"));
                Assert.Contains("\n\nACTION A_Reset:\nxDone := FALSE;\nEND_ACTION\n", text);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void New_puts_a_shared_function_at_the_project_root_with_its_inputs_declared()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-root-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                var result = Create(root, "pou", "F_Lerp", "--kind", "function", "--return-type", "REAL", "--parent", ".",
                    "--text", "VAR_INPUT\n    a : REAL;\n    b : REAL;\nEND_VAR\nVAR\n    k : REAL;\nEND_VAR\nF_Lerp := a + (b - a) * k;");
                Assert.Equal("FUNCTION F_Lerp : REAL\nVAR_INPUT\n    a : REAL;\n    b : REAL;\nEND_VAR\nVAR\n    k : REAL;\nEND_VAR\n// --- implementation ---\nF_Lerp := a + (b - a) * k;\nEND_FUNCTION\n",
                    File.ReadAllText(Path.Combine(root, "project-view", "F_Lerp.st")));
                // A shared POU is tested, not downloaded.
                var hint = (string)result["hint"];
                Assert.Contains("cts test", hint);
                Assert.DoesNotContain("download", hint);
                Assert.Equal(new[] { "cts compare", "cts import" }, ((IList<string>)result["next"]).Take(2));
                var details = NewObjectCommand.Build(result).Details;
                Assert.Contains("Next: cts import", details);
                Assert.Contains(hint, details);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void New_aligns_the_declarations_it_writes()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-align-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                Create(root, "gvl", "GVL_Io", "--text", "xStart : BOOL;\nnSetpoint : INT;");
                Assert.Equal("VAR_GLOBAL\n    xStart    : BOOL;\n    nSetpoint : INT;\nEND_VAR\n", File.ReadAllText(Path.Combine(root, "project-view", "Application", "GVL_Io.st")));
                Create(root, "pou", "FB_Test", "--kind", "function-block");
                Create(root, "method", "FB_Test.M_Run", "--text", "VAR_INPUT\n    x : BOOL;\n    nCount : INT;\nEND_VAR\nM_Run := x;");
                Assert.Contains("VAR_INPUT\n    x      : BOOL;\n    nCount : INT;\nEND_VAR\n// --- implementation ---\nM_Run := x;", File.ReadAllText(Path.Combine(root, "project-view", "Application", "FB_Test.st")));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void New_splits_only_the_var_blocks_a_text_starts_with()
        {
            Assert.Equal(new KeyValuePair<string, string>("", "x := 1;"), NewObjectCommand.Split("x := 1;\n"));
            Assert.Equal(new KeyValuePair<string, string>("VAR_INPUT\n\ta : INT;\nEND_VAR", "F := a; (* VAR in a comment *)"),
                NewObjectCommand.Split("VAR_INPUT a : INT; END_VAR F := a; (* VAR in a comment *)"));
            // One line typed: laid out a declaration per line, every block.
            Assert.Equal("VAR_INPUT\n\ta, b, t : REAL;\nEND_VAR\nVAR CONSTANT\n\tk : INT := 2;\n\tm : INT;\nEND_VAR",
                NewObjectCommand.Split("VAR_INPUT a, b, t : REAL; END_VAR VAR CONSTANT k : INT := 2; m : INT; END_VAR F := a;").Key);
            // A comment or a line break is the caller's layout.
            Assert.Equal("VAR_INPUT a : INT; (* the input *) END_VAR", NewObjectCommand.Split("VAR_INPUT a : INT; (* the input *) END_VAR F := a;").Key);
        }

        [Fact]
        public void New_writes_an_interface_and_its_members_as_the_export_writes_them()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-itf-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                var result = Create(root, "interface", "I_Dev");
                Assert.Equal("6654496c-404d-479a-aad2-8551054e5f1e", result["type_guid"]);
                Assert.Contains("--implements I_Dev", (string)result["hint"]);
                Create(root, "method", "I_Dev.Read", "--return-type", "BOOL", "--text", "VAR_INPUT nAddr : INT; END_VAR");
                var property = Create(root, "property", "I_Dev.Value", "--type", "INT");
                Assert.Contains("cts new property FB.Value", (string)property["hint"]);
                // The export's text of an interface property has no accessors.
                Assert.Equal("INTERFACE I_Dev\nEND_INTERFACE\n\nMETHOD Read : BOOL\nVAR_INPUT\n\tnAddr : INT;\nEND_VAR\nEND_METHOD\n\nPROPERTY Value : INT\nEND_PROPERTY\n",
                    File.ReadAllText(Path.Combine(root, "project-view", "Application", "I_Dev.st")));
                Create(root, "interface", "I_Dev2", "--extends", "I_Dev,I_Other");
                Assert.Equal("INTERFACE I_Dev2 EXTENDS I_Dev, I_Other\nEND_INTERFACE\n", File.ReadAllText(Path.Combine(root, "project-view", "Application", "I_Dev2.st")));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void New_writes_a_function_block_that_extends_and_implements()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-fb-itf-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                var result = Create(root, "pou", "FB_Dev", "--kind", "function-block", "--extends", "FB_Base", "--implements", "I_A, I_B");
                Assert.Equal("FUNCTION_BLOCK FB_Dev EXTENDS FB_Base IMPLEMENTS I_A, I_B\nVAR\nEND_VAR\n// --- implementation ---\nEND_FUNCTION_BLOCK\n",
                    File.ReadAllText(Path.Combine(root, "project-view", "Application", "FB_Dev.st")));
                Assert.Contains("cts new method FB_Dev.", (string)result["hint"]);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void New_refuses_extends_implements_and_bodies_where_they_do_not_belong()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-new-itf-refuse-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                string Refusal(params string[] args) => Assert.Throws<CliFailure>(() => Create(root, args[0], args[1], args.Skip(2).ToArray())).Message;
                Assert.Contains("--implements is for a function block", Refusal("interface", "I_X", "--implements", "I_A"));
                Assert.Contains("--implements is for a function block", Refusal("pou", "P_X", "--kind", "program", "--implements", "I_A"));
                Assert.Contains("--extends is for a function block or an interface", Refusal("dut", "ST_X", "--kind", "struct", "--extends", "ST_A"));
                Assert.Contains("--extends is for a function block or an interface", Refusal("gvl", "GVL_X", "--extends", "GVL_A"));
                Assert.Contains("extends one function block", Refusal("pou", "FB_X", "--kind", "function-block", "--extends", "FB_A,FB_B"));
                Assert.Contains("invalid name in --implements", Refusal("pou", "FB_X", "--kind", "function-block", "--implements", "I_A;"));
                Assert.Contains("an interface has no body", Refusal("interface", "I_X", "--text", "x := 1;"));
                Create(root, "interface", "I_X");
                Assert.Contains("no GET or SET body", Refusal("property", "I_X.P", "--type", "INT", "--get-text", "P := 1;"));
                Assert.Contains("an interface has no actions", Refusal("action", "I_X.A_Run", "--text", "x := 1;"));
            }
            finally { Directory.Delete(root, true); }
        }

        static IDictionary<string, object> Create(string root, string kind, string name, params string[] extra)
        {
            var args = new List<string> { "new", kind, name, "--sync-folder", root };
            args.AddRange(extra);
            var command = CliCommands.Find(new[] { "new" });
            return command.LocalExecute(CliOptions.Parse(args, null, command), null, root);
        }

        [Fact]
        public void Read_object_resolves_a_name_and_returns_identity_and_text()
        {
            var command = CliCommands.Find(new[] { "read-object" });
            var options = CliOptions.Parse(new[] { "read-object", "MAIN" }, null, command);
            var hello = new Hello(42, new Dictionary<string, object>());
            var calls = new List<string>();
            IDictionary<string, object> Fake(string method, IDictionary<string, object> args)
            {
                calls.Add(method);
                if (method == "objects.find") return new Dictionary<string, object> { { "matches", new List<object> { new Dictionary<string, object> { { "name", "MAIN" }, { "path", "Application/MAIN" }, { "guid", "a1" }, { "type", "pou" } } } } };
                return new Dictionary<string, object> { { "name", "MAIN" }, { "declaration", "PROGRAM MAIN" }, { "implementation", "MAIN := TRUE;" } };
            }
            var data = command.Execute(new CliCall(command, options, hello, 30, Fake));
            Assert.Equal("a1", data["guid"]);
            Assert.Equal("Application/MAIN", data["path"]);
            Assert.Equal("PROGRAM MAIN", data["declaration"]);
            Assert.Equal(new[] { "objects.find", "objects.text" }, calls);
        }

        [Fact]
        public void Read_object_path_matches_whole_segments_not_the_tail_of_a_longer_name()
        {
            var command = CliCommands.Find(new[] { "read-object" });
            var options = CliOptions.Parse(new[] { "read-object", "--path", "A/MAIN" }, null, command);
            var hello = new Hello(42, new Dictionary<string, object>());
            IDictionary<string, object> Fake(string method, IDictionary<string, object> args)
            {
                if (method == "objects.find") return new Dictionary<string, object> { { "matches", new List<object> {
                    new Dictionary<string, object> { { "name", "MAIN" }, { "path", "PLC/AppA/MAIN" }, { "guid", "b2" }, { "type", "pou" } },
                    new Dictionary<string, object> { { "name", "MAIN" }, { "path", "PLC/A/MAIN" }, { "guid", "a1" }, { "type", "pou" } } } } };
                return new Dictionary<string, object> { { "name", "MAIN" }, { "declaration", "PROGRAM MAIN" } };
            }
            var data = command.Execute(new CliCall(command, options, hello, 30, Fake));
            Assert.Equal("a1", data["guid"]);
        }

        [Fact]
        public void Read_object_body_file_is_rendered_by_the_export_writer_from_its_subtree()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-read-object-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            var target = Path.Combine(root, "object.st");
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                var command = CliCommands.Find(new[] { "read-object" });
                var options = CliOptions.Parse(new[] { "read-object", "FB_Valve", "--body-file", target }, null, command);
                var hello = new Hello(42, new Dictionary<string, object> { { "project", new Dictionary<string, object> { { "sync_folder", root } } } });
                IDictionary<string, object> Fake(string method, IDictionary<string, object> args)
                {
                    if (method == "objects.find") return new Dictionary<string, object> { { "matches", new List<object> { new Dictionary<string, object> { { "name", "FB_Valve" }, { "path", "Application/FB_Valve" }, { "guid", "a1" }, { "type", "pou" } } } } };
                    if (method == "objects.text") return new Dictionary<string, object> { { "name", "FB_Valve" }, { "declaration", "FUNCTION_BLOCK FB_Valve" } };
                    if (method == "project.tree")
                    {
                        var child = new Dictionary<string, object> { { "guid", "a2" }, { "name", "M_Start" } };
                        var owner = new Dictionary<string, object> { { "guid", "a1" }, { "name", "FB_Valve" }, { "children", new List<object> { child } } };
                        return new Dictionary<string, object> { { "name", "Demo" }, { "children", new List<object> { owner } } };
                    }
                    if (method == "project.export")
                    {
                        Assert.Equal(new[] { "a1", "a2" }, ((string[])args["guids"]));
                        File.Copy(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "snapshot.xml"), (string)args["path"]);
                        return new Dictionary<string, object>();
                    }
                    throw new InvalidOperationException(method);
                }
                command.Execute(new CliCall(command, options, hello, 30, Fake));
                Assert.True(File.Exists(target));
                Assert.Contains("FUNCTION_BLOCK FB_Valve", File.ReadAllText(target));
                Assert.Contains("METHOD M_Toggle", File.ReadAllText(target));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Read_object_body_file_of_a_container_is_its_folder_object_file()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-read-object-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            var target = Path.Combine(root, "object.xml");
            try
            {
                File.WriteAllText(Path.Combine(root, "cds-text-sync.json"), "{}");
                var command = CliCommands.Find(new[] { "read-object" });
                var options = CliOptions.Parse(new[] { "read-object", "Visualization Manager", "--body-file", target }, null, command);
                var hello = new Hello(42, new Dictionary<string, object> { { "project", new Dictionary<string, object> { { "sync_folder", root } } } });
                IDictionary<string, object> Fake(string method, IDictionary<string, object> args)
                {
                    if (method == "objects.find") return new Dictionary<string, object> { { "matches", new List<object> { new Dictionary<string, object> { { "name", "Visualization Manager" }, { "path", "Application/Visualization Manager" }, { "guid", "a1" }, { "type", "native" } } } } };
                    if (method == "objects.text") return new Dictionary<string, object> { { "name", "Visualization Manager" } };
                    if (method == "project.tree") return new Dictionary<string, object> { { "name", "Demo" } };
                    if (method == "project.export")
                    {
                        File.Copy(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "snapshot.xml"), (string)args["path"]);
                        return new Dictionary<string, object>();
                    }
                    throw new InvalidOperationException(method);
                }
                var data = command.Execute(new CliCall(command, options, hello, 30, Fake));
                Assert.Equal("xml", data["body_format"]);
                Assert.Equal(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "expected", "PLC_Stabur", "Plc Logic", "Application", "Visualization Manager", ".cds-object.xml")),
                    File.ReadAllBytes(target));
            }
            finally { Directory.Delete(root, true); }
        }
    }
}
