using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Analysis;
using Cts.Docs;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts diagram classes|calls|view`: mermaid diagrams of the sync
    // folder's project, offline, from what `cts docs` reads: the class
    // structure around a block, who calls whom from a task down, and a page
    // that browses them all with the state machines.
    internal static class DiagramCommand
    {
        const int ClassDepth = 1;
        const int CallDepth = 3;
        //: Mermaid's defaults, maxTextSize and maxEdges: a larger diagram is not drawn.
        const int MermaidLimit = 50000;
        const int MermaidEdges = 500;

        static readonly Regex Unsafe = new Regex(@"[^A-Za-z0-9_.\-]+");
        static readonly Regex Arrow = new Regex(@" (?:<\|--|<\|\.\.|\*--|-->) ");
        static readonly CliOption Workspace = CliOption.Text("--workspace", "workspace", "DIR", "The sync folder or its project-view (default: the one around the current folder)");

        internal static IEnumerable<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "diagram", Sub = "classes", Arguments = "[NAME]", ArgumentLimit = 1,
                ArgumentHelp = "The function block, interface, structure or program in the middle",
                Summary = "Draw the function blocks, interfaces and structures as a mermaid classDiagram (offline)",
                Description = "A mermaid classDiagram of the sync folder's project: what a function block extends and implements, the blocks and "
                    + "structures it holds (composition, the member's name on the line) and the ones it only refers to (a POINTER, REFERENCE, "
                    + "VAR_IN_OUT or interface variable: association). A class lists its inputs, outputs, methods and properties, not its internals. "
                    + "With NAME the classes up to --depth relations away from it (default " + ClassDepth + "), a line only between classes a step apart; "
                    + "without it every class that has a relation. More than eight classes tied to one class alone and the same way print as one list. "
                    + "Library types are not drawn. Needs no IDE; paste the text into a mermaid block of a document or a pull request.",
                Options = new[] { CliOption.Int("--depth", "depth", "Relations away from NAME (default " + ClassDepth + ")"), Workspace },
                LocalExecute = (options, host, work) => Draw(options, work, "classes"), Build = Build,
            },
            new CliCommand
            {
                Name = "diagram", Sub = "calls",
                Summary = "Draw who calls whom from the tasks down as a mermaid flowchart (offline)",
                Description = "A mermaid flowchart of the sync folder's project: each task calls its programs, each program the function blocks, "
                    + "functions, methods and actions its code calls, --depth calls down (default " + CallDepth + "). --from starts at one task or "
                    + "object instead of every task; with no task configuration in the folder, every program no one calls is a start. A node whose "
                    + "callees lie deeper says how many (+N); more than eight objects of one kind a node calls that call nothing drawn are one node "
                    + "listing them. Only the project's own objects are drawn. Needs no IDE.",
                Options = new[]
                {
                    CliOption.Text("--from", "from", "TASK|NAME", "Start at this task or object"),
                    CliOption.Int("--depth", "depth", "Calls down from the start (default " + CallDepth + ")"),
                    Workspace,
                },
                LocalExecute = (options, host, work) => Draw(options, work, "calls"), Build = Build,
            },
            new CliCommand
            {
                Name = "diagram", Sub = "view",
                Summary = "Write every diagram of the project into one HTML page and open it (offline)",
                Description = "One HTML file that browses the sync folder's project: the calls from each task and object, the classes around each "
                    + "function block, structure and interface, and each state machine as the FSM window draws it, at the depths the other "
                    + "diagram commands take. Pick on the left, drag to move, the wheel zooms, a click on a node goes to it. The page holds mermaid "
                    + "and every drawing, so it opens without a network and travels as one file. Written to --out (default: cts-diagrams in the "
                    + "temporary folder) and opened in the default browser unless --no-open. Needs no IDE.",
                Options = new[]
                {
                    CliOption.Text("--out", "out", "FILE", "Write the page here"),
                    CliOption.Switch("--no-open", "no_open", "Only write the page"),
                    Workspace,
                },
                LocalExecute = (options, host, work) => View(options, work), Build = BuildView,
            },
        };

        static IDictionary<string, object> View(CliOptions options, string work)
        {
            var workspace = Resolve(options, work, "view");
            var mermaid = DiagramView.Mermaid();
            if (mermaid == null) throw Failure("view", "assets/mermaid.min.js is not in the install above " + AppDomain.CurrentDomain.BaseDirectory + ": reinstall cts");
            var project = Path.GetFileName(workspace.Root.TrimEnd('\\', '/'));
            var model = DiagramView.Model(project, ProjectDocs.Build(Snapshot.Read(workspace.View), name => name), ProjectDocs.TaskRoots(workspace.View), FsmCommand.Drawings(workspace.View));
            var file = Path.GetFullPath(options.Text("out") ?? Path.Combine(Path.GetTempPath(), "cts-diagrams", Unsafe.Replace(project, "_") + ".html"));
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            File.WriteAllText(file, DiagramView.Page(Template(), File.ReadAllText(mermaid), model), new UTF8Encoding(false));
            var opened = false;
            if (!options.Params.ContainsKey("no_open"))
            {
                // The shell starts the browser: a child of cts would hold the pipe the quick window reads cts' answer from.
                try { Process.Start(new ProcessStartInfo(file) { UseShellExecute = true }); opened = true; }
                catch (Exception error) when (error is System.ComponentModel.Win32Exception || error is InvalidOperationException) { }
            }
            return new Dictionary<string, object>
            {
                ["diagram"] = "view", ["file"] = file, ["opened"] = opened, ["project_view"] = workspace.View,
                ["classes"] = ((List<object>)model["classes"]).Count, ["roots"] = ((List<object>)model["roots"]).Count,
                ["machines"] = ((List<object>)model["fsm"]).Count, ["kb"] = new FileInfo(file).Length / 1024,
            };
        }

        static Answer BuildView(IDictionary<string, object> data)
        {
            var answer = new Answer();
            foreach (var key in new[] { "classes", "roots", "machines", "kb", "file" }) answer.Add(key, data[key]);
            if (!Equals(data["opened"], true)) answer.Detail("open " + Text(data, "file") + " in a browser");
            return answer;
        }

        static string Template()
        {
            using (var stream = typeof(DiagramCommand).Assembly.GetManifestResourceStream("Cts.Docs.DiagramView.html"))
            using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
        }

        static AnalyzeWorkspace Resolve(CliOptions options, string work, string kind)
        {
            try
            {
                return AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work);
            }
            catch (AnalyzeException error)
            {
                throw Failure(kind, error.Message);
            }
        }

        static IDictionary<string, object> Draw(CliOptions options, string work, string kind)
        {
            var workspace = Resolve(options, work, kind);
            var symbols = ProjectDocs.Build(Snapshot.Read(workspace.View), name => name);
            Dictionary<string, object> data;
            if (kind == "classes")
            {
                var name = options.Arguments.FirstOrDefault();
                data = ClassDiagram.Render(symbols, name, options.Number("depth", ClassDepth));
                if (data == null) throw Failure(kind, "no function block, interface, structure or program is named " + name);
            }
            else
            {
                var from = options.Text("from");
                data = CallDiagram.Render(symbols, ProjectDocs.TaskRoots(workspace.View), from, options.Number("depth", CallDepth));
                if (data == null) throw Failure(kind, "no task or object is named " + from);
            }
            data["diagram"] = kind;
            data["project_view"] = workspace.View;
            return data;
        }

        static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer();
            foreach (var key in new[] { "classes", "relations", "left_out", "tasks", "objects", "calls", "cut" })
                if (data.ContainsKey(key)) answer.Add(key, data[key]);
            var mermaid = Text(data, "mermaid");
            answer.Whole();
            if (mermaid.Length == 0)
                return answer.Detail(Equals(data["diagram"], "classes") ? "no class extends or implements another: name one (cts diagram classes NAME) to see what it holds and who holds it"
                    : "nothing to start from: no task configuration and no program in the folder; --from names an object");
            answer.Detail(mermaid);
            // The lines drawn, a list of forty standing for forty.
            var edges = mermaid.Split('\n').Count(line => Arrow.IsMatch(line));
            if (mermaid.Length > MermaidLimit || edges > MermaidEdges)
                answer.Detail("[WARN] " + mermaid.Length + " characters, " + edges + " lines: mermaid draws " + MermaidLimit + " characters and " + MermaidEdges + " lines by default; "
                    + (Equals(data["diagram"], "classes") ? "name a class, or lower --depth" : "start --from one task or object, or lower --depth"));
            return answer;
        }

        static CliFailure Failure(string kind, string message) => new CliFailure("diagram-" + kind, "refused", message, "cts diagram " + kind + " --help", 1);
    }
}
