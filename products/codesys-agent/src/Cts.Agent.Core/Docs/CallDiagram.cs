using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Docs
{
    // Who calls whom, top down from the tasks or from one object, as a
    // mermaid flowchart: a task calls its programs, a program the blocks,
    // functions, methods and actions its code calls.  Only the project's
    // own objects are drawn, and a task's program that has no text in the
    // folder (a graphical one) says so; a node whose callees lie deeper than
    // asked says how many it leaves out.  Many objects one node calls that
    // call nothing drawn are one list, not a row of boxes.
    internal static class CallDiagram
    {
        //: Leaves of one kind a node fans out to before they become one list.
        const int MostFan = 8;
        //: Names a list shows before "... N more".
        const int MostNames = 20;

        // *tasks*: each task with the programs it calls (ProjectDocs.TaskRoots).
        // From *from* (a task or an object) or, without it, from every task
        // (every program no one calls when there are none), *depth* calls
        // down; null when *from* names neither.
        internal static Dictionary<string, object> Render(List<DocSymbol> symbols, Dictionary<string, List<string>> tasks, string from, int depth)
        {
            var byName = new Dictionary<string, DocSymbol>(StringComparer.OrdinalIgnoreCase);
            foreach (var symbol in symbols.Concat(symbols.SelectMany(symbol => symbol.Members)).Where(symbol => !symbol.Excluded))
                if (!byName.ContainsKey(symbol.Name)) byName[symbol.Name] = symbol;
            List<string> Callees(string name) => byName.TryGetValue(name, out var symbol)
                ? symbol.Calls.Where(byName.ContainsKey).Select(callee => byName[callee].Name).Distinct().ToList() : new List<string>();
            List<string> Programs(List<string> names) => names.Select(program => byName.TryGetValue(program, out var symbol) ? symbol.Name : program).Distinct().ToList();

            var roots = new List<string>();
            var taskOf = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            if (!string.IsNullOrEmpty(from))
            {
                var task = tasks.Keys.FirstOrDefault(key => key.Equals(from, StringComparison.OrdinalIgnoreCase));
                if (task != null) taskOf[task] = Programs(tasks[task]);
                else if (byName.TryGetValue(from, out var symbol)) roots.Add(symbol.Name);
                else return null;
            }
            else if (tasks.Count > 0) foreach (var task in tasks.Keys.OrderBy(key => key, StringComparer.OrdinalIgnoreCase)) taskOf[task] = Programs(tasks[task]);
            else roots.AddRange(symbols.Where(symbol => symbol.Kind == "PROGRAM" && !symbol.Excluded && symbol.CalledBy.Count == 0).Select(symbol => symbol.Name).OrderBy(name => name, StringComparer.OrdinalIgnoreCase));

            // Breadth first, so a node is drawn at its shallowest level.
            var level = new Dictionary<string, int>(StringComparer.Ordinal);
            var queue = new Queue<string>();
            foreach (var root in taskOf.Values.SelectMany(programs => programs).Concat(roots))
                if (!level.ContainsKey(root)) { level[root] = taskOf.Count > 0 ? 1 : 0; queue.Enqueue(root); }
            var edges = new List<KeyValuePair<string, string>>();
            var cut = new Dictionary<string, int>(StringComparer.Ordinal);
            while (queue.Count > 0)
            {
                var current = queue.Dequeue();
                var callees = Callees(current);
                if (level[current] >= depth)
                {
                    if (callees.Count > 0) cut[current] = callees.Count;
                    continue;
                }
                foreach (var callee in callees)
                {
                    edges.Add(new KeyValuePair<string, string>(current, callee));
                    if (level.ContainsKey(callee)) continue;
                    level[callee] = level[current] + 1;
                    queue.Enqueue(callee);
                }
            }
            // A program running forty blocks that call nothing drawn: one list
            // of the forty, under the first one's id.
            var calls = taskOf.SelectMany(task => task.Value.Select(program => new KeyValuePair<string, string>("task " + task.Key, program))).Concat(edges).ToList();
            var callers = calls.GroupBy(call => call.Value, StringComparer.Ordinal).ToDictionary(group => group.Key, group => group.Select(call => call.Key).Distinct().ToList(), StringComparer.Ordinal);
            var calling = new HashSet<string>(edges.Select(edge => edge.Key), StringComparer.Ordinal);
            var fanOf = level.Keys.Where(name => byName.ContainsKey(name) && !calling.Contains(name) && callers.TryGetValue(name, out var by) && by.Count == 1)
                .GroupBy(name => callers[name][0] + " " + byName[name].Kind, StringComparer.Ordinal).Where(fan => fan.Count() > MostFan)
                .SelectMany(fan => fan.Select(name => new KeyValuePair<string, List<string>>(name, fan.ToList()))).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
            string Text(string name) => Label(name + (cut.TryGetValue(name, out var more) ? " +" + more : ""));

            // Ids, not names: a node called "end" ends a mermaid flowchart.
            var ids = new Dictionary<string, string>(StringComparer.Ordinal);
            string Id(string key) => ids.TryGetValue(key, out var id) ? id : ids[key] = "n" + (ids.Count + 1);
            var lines = new List<string> { "flowchart TD" };
            foreach (var task in taskOf.Keys) lines.Add("    " + Id("task " + task) + "{{\"" + Label("task " + task) + "\"}}");
            foreach (var name in level.Keys)
            {
                if (!byName.TryGetValue(name, out var symbol))
                {
                    lines.Add("    " + Id(name) + "[\"" + Label(name) + " (no text)\"]");
                    continue;
                }
                var text = Text(name);
                if (fanOf.TryGetValue(name, out var fan))
                {
                    if (fan[0] != name) continue;
                    text = ProjectDocs.Many(fan.Count, symbol.Kind) + string.Concat(fan.Take(MostNames).Select(leaf => "<br>" + Text(leaf)))
                        + (fan.Count > MostNames ? "<br>... " + (fan.Count - MostNames) + " more" : "");
                }
                var kind = symbol.Kind;
                lines.Add("    " + Id(name) + (kind == "PROGRAM" ? "[[\"" + text + "\"]]" : kind == "FUNCTION" ? "(\"" + text + "\")"
                    : kind == "FUNCTION_BLOCK" ? "[\"" + text + "\"]" : "([\"" + text + "\"])"));
            }
            foreach (var call in calls.Where(call => !fanOf.TryGetValue(call.Value, out var fan) || fan[0] == call.Value))
                lines.Add("    " + Id(call.Key) + " --> " + Id(call.Value));
            return new Dictionary<string, object>
            {
                ["tasks"] = taskOf.Count,
                ["objects"] = level.Count,
                ["calls"] = calls.Count,
                ["cut"] = cut.Count,
                ["mermaid"] = taskOf.Count + level.Count > 0 ? string.Join("\n", lines) : "",
            };
        }

        // Mermaid's quoted label takes no double quote.
        static string Label(string text) => text.Replace("\"", "#quot;");
    }
}
