using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Agent;

namespace Cts.Docs
{
    // The page `cts diagram view` writes: one HTML file that holds the viewer,
    // mermaid and every call, class and FSM drawing of the project, so it
    // opens offline and travels as one file.  The viewer only lays the
    // drawings out; cts decides what each one shows (CallDiagram,
    // ClassDiagram, FsmSvg).
    internal static class DiagramView
    {
        //: The depths the viewer offers; the middle one opens.
        static readonly int[] CallDepths = { 2, 3, 5 }, ClassDepths = { 1, 2 };
        static readonly string[] ClassKinds = { "FUNCTION_BLOCK", "INTERFACE", "STRUCT", "UNION", "PROGRAM" };
        static readonly string[] CallerKinds = { "PROGRAM", "FUNCTION_BLOCK", "FUNCTION" };

        // *template* (the viewer) with *mermaid* (mermaid.min.js) and *model* put in.
        internal static string Page(string template, string mermaid, Dictionary<string, object> model)
        {
            // "<" escaped: no string in the data can close the script it sits in.
            var data = Json.Serialize(model).Replace("<", "\\u003c");
            return template.Replace("/*cts:mermaid*/", mermaid).Replace("/*cts:data*/null", data);
        }

        // What the page shows of the project *project*: its classes and the
        // objects that call, each drawn at each depth, and its machines.
        internal static Dictionary<string, object> Model(string project, List<DocSymbol> symbols, Dictionary<string, List<string>> tasks, List<KeyValuePair<string, string>> machines)
        {
            var diagrams = new Dictionary<string, object>(StringComparer.Ordinal);
            diagrams["classes||0"] = ClassDiagram.Render(symbols, null, 1)["mermaid"];
            var classes = new List<object>();
            foreach (var symbol in Unique(symbols.Where(symbol => ClassKinds.Contains(symbol.Kind))))
            {
                var relations = 0;
                foreach (var depth in ClassDepths)
                {
                    var drawing = ClassDiagram.Render(symbols, symbol.Name, depth);
                    if (depth == ClassDepths[0]) relations = (int)drawing["relations"];
                    diagrams["classes|" + symbol.Name + "|" + depth] = drawing["mermaid"];
                }
                classes.Add(new Dictionary<string, object> { ["name"] = symbol.Name, ["kind"] = symbol.Kind, ["relations"] = relations });
            }
            var roots = new List<object>();
            foreach (var depth in CallDepths) diagrams["calls||" + depth] = CallDiagram.Render(symbols, tasks, null, depth)["mermaid"];
            foreach (var task in tasks.Keys.OrderBy(task => task, StringComparer.OrdinalIgnoreCase))
            {
                roots.Add(new Dictionary<string, object> { ["name"] = task, ["kind"] = "TASK", ["calls"] = tasks[task].Count });
                foreach (var depth in CallDepths) diagrams["calls|" + task + "|" + depth] = CallDiagram.Render(symbols, tasks, task, depth)["mermaid"];
            }
            foreach (var symbol in Unique(symbols.Where(symbol => CallerKinds.Contains(symbol.Kind) && symbol.Calls.Count > 0 && !tasks.ContainsKey(symbol.Name))))
            {
                roots.Add(new Dictionary<string, object> { ["name"] = symbol.Name, ["kind"] = symbol.Kind, ["calls"] = symbol.Calls.Count });
                foreach (var depth in CallDepths) diagrams["calls|" + symbol.Name + "|" + depth] = CallDiagram.Render(symbols, tasks, symbol.Name, depth)["mermaid"];
            }
            return new Dictionary<string, object>
            {
                ["project"] = project,
                ["made"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                ["depths"] = new Dictionary<string, object> { ["calls"] = CallDepths.Cast<object>().ToList(), ["classes"] = ClassDepths.Cast<object>().ToList() },
                ["classes"] = classes,
                ["roots"] = roots,
                ["fsm"] = machines.Select(machine => (object)new Dictionary<string, object> { ["name"] = machine.Key, ["svg"] = machine.Value }).ToList(),
                ["diagrams"] = diagrams,
            };
        }

        static IEnumerable<DocSymbol> Unique(IEnumerable<DocSymbol> symbols) => symbols.Where(symbol => !symbol.Excluded)
            .GroupBy(symbol => symbol.Name, StringComparer.OrdinalIgnoreCase).Select(group => group.First()).OrderBy(symbol => symbol.Name, StringComparer.OrdinalIgnoreCase);

        // mermaid.min.js of the install, in an assets folder above this cts.exe
        // (products/codesys-agent/assets beside dist); null when there is none.
        internal static string Mermaid()
        {
            for (var folder = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory); folder != null; folder = folder.Parent)
            {
                var candidate = Path.Combine(folder.FullName, "assets", "mermaid.min.js");
                if (File.Exists(candidate)) return candidate;
            }
            return null;
        }
    }
}
