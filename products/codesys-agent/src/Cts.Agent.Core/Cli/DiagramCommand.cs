using System.Collections.Generic;
using System.Linq;
using Cts.Analysis;
using Cts.Docs;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts diagram classes|calls`: mermaid diagrams of the sync folder's
    // project, offline, from what `cts docs` reads: the class structure
    // around a block, and who calls whom from a task down.
    internal static class DiagramCommand
    {
        const int ClassDepth = 1;
        const int CallDepth = 3;
        //: Mermaid's defaults, maxTextSize and maxEdges: a larger diagram is not drawn.
        const int MermaidLimit = 50000;
        const int MermaidEdges = 500;

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
                    + "With NAME the classes up to --depth relations away from it (default " + ClassDepth + "); without it every class that has a relation. "
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
                    + "callees lie deeper says how many (+N). Only the project's own objects are drawn. Needs no IDE.",
                Options = new[]
                {
                    CliOption.Text("--from", "from", "TASK|NAME", "Start at this task or object"),
                    CliOption.Int("--depth", "depth", "Calls down from the start (default " + CallDepth + ")"),
                    Workspace,
                },
                LocalExecute = (options, host, work) => Draw(options, work, "calls"), Build = Build,
            },
        };

        static IDictionary<string, object> Draw(CliOptions options, string work, string kind)
        {
            AnalyzeWorkspace workspace;
            try
            {
                workspace = AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work);
            }
            catch (AnalyzeException error)
            {
                throw Failure(kind, error.Message);
            }
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
            var edges = data.ContainsKey("relations") ? Int(data, "relations") : Int(data, "calls");
            if (mermaid.Length > MermaidLimit || edges > MermaidEdges)
                answer.Detail("[WARN] " + mermaid.Length + " characters, " + edges + " lines: mermaid draws " + MermaidLimit + " characters and " + MermaidEdges + " lines by default; "
                    + (Equals(data["diagram"], "classes") ? "name a class, or lower --depth" : "start --from one task or object, or lower --depth"));
            return answer;
        }

        static CliFailure Failure(string kind, string message) => new CliFailure("diagram-" + kind, "refused", message, "cts diagram " + kind + " --help", 1);
    }
}
