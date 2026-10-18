using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Agent
{
    internal static class FsmMermaid
    {
        static readonly Regex Unsafe = new Regex(@"[:;#""\n]", RegexOptions.Compiled);

        internal static string Render(IDictionary<string, object> machine)
        {
            var lines = new List<string> { "stateDiagram-v2" };
            if ((bool)machine["deferred"])
                lines.Add("    %% transitions write the next-state variable; they take effect on the following scan");

            var states = (IEnumerable<Dictionary<string, object>>)machine["states"];
            var indexes = new Dictionary<string, string>();
            var index = 0;
            foreach (var state in states)
            {
                var id = "s" + index++;
                indexes[(string)state["label"]] = id;
                lines.Add("    " + id + " : " + (string)state["label"]);
            }

            var transitions = (IEnumerable<Dictionary<string, object>>)machine["transitions"];
            var edges = transitions.ToList();
            if (edges.Any(transition => transition["source"] == null))
                lines.Add("    ANY : (any state)");

            foreach (var transition in edges)
            {
                var source = transition["source"] == null ? "ANY" : indexes[(string)transition["source"]];
                var target = indexes.TryGetValue((string)transition["target"], out var targetId) ? targetId : "s0";
                var guard = SanitizeGuard((string)transition["guard"]);
                lines.Add(guard.Length == 0
                    ? "    " + source + " --> " + target
                    : "    " + source + " --> " + target + " : " + guard);
            }
            return String.Join("\n", lines);
        }

        static string SanitizeGuard(string guard)
        {
            var text = Unsafe.Replace(StText.Squeezed(guard), " ");
            return text.Length > 60 ? text.Substring(0, 60).TrimEnd() + "..." : text;
        }
    }
}
