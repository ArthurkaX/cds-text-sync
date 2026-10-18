using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // A project POU call graph contains a direct or indirect recursion cycle.
    internal sealed class CTS0085 : Rule
    {
        internal CTS0085() : base("CTS0085", "Recursive POU call cycle", Analysis.Severity.Danger, "Correctness", "Project POU calls must not form a direct or indirect recursion cycle.", "ANY")
        {
            Requires = new[] { Needs.ExecutionGraph };
        }

        internal override bool PerUnit => false;

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            var units = context.Units.Where(unit => Analysis.Kinds.IsCallable(unit.Kind))
                .GroupBy(unit => Key(unit.QualifiedName), StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => group.First(), StringComparer.Ordinal);
            if (units.Count == 0) yield break;
            var edges = units.Keys.ToDictionary(caller => caller,
                caller => new HashSet<string>(context.Graph.Calls.TryGetValue(caller, out var callees) ? callees.Where(units.ContainsKey) : Enumerable.Empty<string>(), StringComparer.Ordinal), StringComparer.Ordinal);
            foreach (var component in StronglyConnected(units.Keys, edges))
            {
                if (component.Count == 1 && !edges[component.First()].Contains(component.First())) continue;
                var candidates = new List<Tuple<string, int, string, string>>();
                foreach (var caller in component.OrderBy(name => name, StringComparer.Ordinal))
                {
                    if (!context.Graph.Sites.TryGetValue(caller, out var sites)) continue;
                    foreach (var site in sites.Where(site => component.Contains(site.Item1)))
                    {
                        var returnPath = Path(site.Item1, caller, edges, component);
                        if (returnPath == null) continue;
                        var cycle = new[] { caller }.Concat(returnPath).Select(name => units[name].QualifiedName);
                        candidates.Add(Tuple.Create(caller, site.Item2, site.Item3, string.Join(" -> ", cycle)));
                    }
                }
                var candidate = candidates.OrderBy(item => item.Item1, StringComparer.Ordinal).ThenBy(item => item.Item2).ThenBy(item => item.Item3, StringComparer.Ordinal).FirstOrDefault();
                if (candidate == null) continue;
                var unit = units[candidate.Item1];
                var anchor = candidate.Item3.Trim();
                yield return Finding.In(unit,
                    "recursive POU call cycle detected: " + candidate.Item4 + "; the fixed PLC call stack may overflow",
                    candidate.Item2, candidate.Item2 + candidate.Item3.Length, anchor, anchor);
            }
        }

        static string Key(string name) => (name ?? "").Trim().ToLowerInvariant();

        static List<string> Path(string start, string target, Dictionary<string, HashSet<string>> edges, HashSet<string> allowed)
        {
            var queue = new Queue<List<string>>();
            queue.Enqueue(new List<string> { start });
            var seen = new HashSet<string>(StringComparer.Ordinal) { start };
            while (queue.Count > 0)
            {
                var path = queue.Dequeue();
                var current = path[path.Count - 1];
                if (current == target) return path;
                foreach (var callee in edges[current].OrderBy(name => name, StringComparer.Ordinal))
                {
                    if (!allowed.Contains(callee) || !seen.Add(callee)) continue;
                    queue.Enqueue(path.Concat(new[] { callee }).ToList());
                }
            }
            return null;
        }

        static List<HashSet<string>> StronglyConnected(IEnumerable<string> nodes, Dictionary<string, HashSet<string>> edges)
        {
            var index = 0;
            var stack = new Stack<string>();
            var onStack = new HashSet<string>(StringComparer.Ordinal);
            var indices = new Dictionary<string, int>(StringComparer.Ordinal);
            var lowLinks = new Dictionary<string, int>(StringComparer.Ordinal);
            var components = new List<HashSet<string>>();
            Action<string> visit = null;
            visit = node =>
            {
                indices[node] = index;
                lowLinks[node] = index++;
                stack.Push(node);
                onStack.Add(node);
                foreach (var callee in edges[node].OrderBy(name => name, StringComparer.Ordinal))
                {
                    if (!indices.ContainsKey(callee))
                    {
                        visit(callee);
                        lowLinks[node] = Math.Min(lowLinks[node], lowLinks[callee]);
                    }
                    else if (onStack.Contains(callee)) lowLinks[node] = Math.Min(lowLinks[node], indices[callee]);
                }
                if (lowLinks[node] != indices[node]) return;
                var component = new HashSet<string>(StringComparer.Ordinal);
                string current;
                do
                {
                    current = stack.Pop();
                    onStack.Remove(current);
                    component.Add(current);
                } while (current != node);
                components.Add(component);
            };
            foreach (var node in nodes.OrderBy(name => name, StringComparer.Ordinal))
                if (!indices.ContainsKey(node)) visit(node);
            return components;
        }
    }
}
