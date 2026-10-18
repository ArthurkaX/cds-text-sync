using System;
using System.Collections.Generic;
using System.IO;
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
                Assert.DoesNotContain("cts test", string.Join("\n", (IList<string>)result["next"]));
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
                var next = string.Join("\n", (IList<string>)result["next"]);
                Assert.Contains("cts test", next);
                Assert.DoesNotContain("download", next);
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
