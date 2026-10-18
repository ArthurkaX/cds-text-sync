using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A local without an initial value read before anything writes it: a
    // VAR_TEMP anywhere, a VAR in a function, method, action or accessor
    // (where VAR is not kept between calls).
    internal sealed class CTS0018 : Rule
    {
        static readonly Regex Selector = new Regex(@"\G\s*(?:\.\s*(?<field>[A-Za-z_]\w*|%[A-Za-z]\w*|\d+)|\[(?<index>[^\]]*)\])", RegexOptions.IgnoreCase);
        static readonly HashSet<string> TransientVar = new HashSet<string> { Analysis.Kinds.Function, Analysis.Kinds.Method, Analysis.Kinds.Action, Analysis.Kinds.PropertyGet, Analysis.Kinds.PropertySet };

        internal CTS0018() : base("CTS0018", "Read before assignment", Analysis.Severity.Suspicious, "Correctness", "Local variables read before their first assignment.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        sealed class Local
        {
            internal string Name;
            internal readonly HashSet<string> Assigned = new HashSet<string>();
            internal bool Aggregate, Reported;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var locals = unit.Members()
                .Where(member => member.Name.Length > 0 && string.IsNullOrWhiteSpace(member.Initial))
                .Where(member => member.Scope == "VAR_TEMP" || member.Scope == "VAR" && TransientVar.Contains(unit.Kind))
                .ToLookup(member => member.Name.ToLowerInvariant(), member => new Local { Name = member.Name });
            if (locals.Count == 0) yield break;
            var text = section.Text;
            foreach (Match match in StText.Name.Matches(text))
            {
                var tracked = locals[match.Value.ToLowerInvariant()].Where(local => !local.Reported).ToList();
                if (tracked.Count == 0) continue;
                var end = match.Index + match.Length;
                // In "arg => local" the left name labels an argument; it is no read.
                if (StBlocks.LabelsArgument(text, end)) continue;
                var (path, pathEnd) = PathAfter(text, end);
                var written = StBlocks.WrittenAt(text, match.Index, pathEnd);
                foreach (var local in tracked)
                {
                    if (written)
                    {
                        local.Assigned.Add(path);
                        // A field or element write initializes the whole value
                        // here: unions and buffer-building loops.
                        if (path.Length > 0) local.Aggregate = true;
                        continue;
                    }
                    if (local.Aggregate || local.Assigned.Contains(path) || path.Length > 0 && local.Assigned.Contains("")) continue;
                    local.Reported = true;
                    yield return Finding.In(unit, "local '" + local.Name + "' is read before its first assignment", section.At(match.Index), section.At(end), local.Name, local.Name);
                }
            }
        }

        // The selectors after a name (".field", "[i]"), lower case, and where they end.
        static (string, int) PathAfter(string text, int position)
        {
            var path = new System.Text.StringBuilder();
            for (var selector = Selector.Match(text, position); selector.Success; selector = Selector.Match(text, position))
            {
                path.Append(selector.Groups["field"].Success ? "." + selector.Groups["field"].Value.ToLowerInvariant() : "[" + StText.Unspaced(selector.Groups["index"].Value).ToLowerInvariant() + "]");
                position = selector.Index + selector.Length;
            }
            return (path.ToString(), position);
        }
    }
}
