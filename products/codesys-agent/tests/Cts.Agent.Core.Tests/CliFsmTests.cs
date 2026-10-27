using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        const string Machine = "CASE state OF\n0:\n    IF xStart THEN\n        state := 10;\n    END_IF\n10:\n    state := 0;\nEND_CASE\n";

        static object FsmTexts() => new Dictionary<string, object> { { "objects", new object[]
        {
            new Dictionary<string, object> { { "guid", "g-prg" }, { "name", "PRG_Main" }, { "parent", "" }, { "declaration", "PROGRAM PRG_Main\nVAR\n    state : INT;\nEND_VAR\n" }, { "implementation", Machine } },
            new Dictionary<string, object> { { "guid", "g-fb" }, { "name", "FB_Valve" }, { "parent", "" }, { "implementation", "x := 1;" } },
        } } };

        [Fact]
        public void Fsm_lists_the_machines_in_the_IDE_text_and_the_window_reads_their_layout()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, _) => { Assert.Equal("objects.texts", method); return FsmTexts(); });
            var (code, output, _) = Run(host, "fsm");
            Assert.Equal(0, code);
            Assert.Contains("ok fsm objects=2 with_fsm=1 machines=1", output);
            Assert.Contains("PRG_Main: state (2 states, 2 transitions in source order, starts in 0, INT's default 0)", output);
            var (_, json, _) = Run(host, "fsm", "--layout", "--json");
            var objects = FsmMap.Parse(json);
            Assert.Equal("PRG_Main", Assert.Single(objects).Label);
            Assert.Equal(2, Assert.Single(objects[0].Machines).Layout.Steps.Count);
        }

        [Fact]
        public void Fsm_on_one_object_shows_each_transition_and_the_mermaid_diagram()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, _) => FsmTexts());
            var (code, output, _) = Run(host, "fsm", "PRG_Main", "--mermaid");
            Assert.Equal(0, code);
            Assert.Contains("  0 -> 10 when xStart  line 3", output);
            Assert.Contains("INT's default 0), lines count from the implementation's first line", output);
            Assert.Contains("stateDiagram-v2", output);
            Assert.Contains("  read it online: cts read PRG_Main.state", output);
            var (missing, _, error) = Run(host, "fsm", "Nothing");
            Assert.Equal(1, missing);
            Assert.Contains("no text object is named Nothing", error);
        }

        [Fact]
        public void Fsm_disk_reads_the_sync_folder_without_the_IDE_and_counts_lines_of_the_file()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-fsm-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "Application"));
            try
            {
                File.WriteAllText(Path.Combine(folder, "project-view", "Application", "PRG_Main.st"),
                    "PROGRAM PRG_Main\nVAR\n    state : INT;\n    xStart : BOOL;\nEND_VAR\n// --- implementation ---\n" + Machine + "END_PROGRAM\n");
                var (code, output, _) = Run(new FakeHost(), "fsm", "--disk", "--sync-folder", folder, "--json");
                Assert.True(code == 0, output);
                Assert.Contains("\"file\": \"Application/PRG_Main.st\"", output);
                // The IF of the first transition: line 3 of the implementation, line 9 of the file.
                Assert.True(output.Contains("\"line\": 9,"), output);
                // The window's drawing as a file, its lines the file's too.
                var drawings = Path.Combine(folder, "drawings");
                (code, output, _) = Run(new FakeHost(), "fsm", "--disk", "--sync-folder", folder, "--svg", drawings);
                Assert.True(code == 0, output);
                Assert.Contains("drawn in PRG_Main.state.svg", output);
                var svg = XDocument.Load(Path.Combine(drawings, "PRG_Main.state.svg"));
                Assert.Equal("PRG_Main: state", svg.Root.Elements().First().Value);
                // A hover names the line and shows the code behind a step or a transition.
                var hovers = svg.Descendants().Where(element => element.Name.LocalName == "title").Select(element => element.Value).ToList();
                Assert.Contains(hovers, hover => hover.StartsWith("0 → 10 when xStart, line 9\n\n") && hover.Contains("state := 10;"));
                Assert.Contains(hovers, hover => hover.StartsWith("10, line 12\n\n") && hover.Contains("state := 0;"));
            }
            finally { Directory.Delete(folder, true); }
        }
    }
}
