using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An edge-trigger instance called in conditional or loop flow may miss a transition.
    internal sealed class CTS0087 : Rule
    {
        static readonly HashSet<string> TriggerTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "R_TRIG", "F_TRIG" };

        internal CTS0087() : base("CTS0087", "Conditional edge-trigger call", Analysis.Severity.Danger, "Correctness", "R_TRIG and F_TRIG instances must be called once on every cycle.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var instances = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit).Where(member => TriggerTypes.Contains(Snapshot.LastSegment(member.Type))))
                instances[member.Name] = member.Name;
            if (instances.Count == 0 || unit.Body.IsEmpty) yield break;

            foreach (Match match in StCalls.Call.Matches(unit.Body.Text))
            {
                var name = match.Groups["name"];
                if (!instances.TryGetValue(name.Value, out var trigger)) continue;
                var absolute = unit.Body.At(name.Index);
                var containing = new List<string>();
                InsideBlocks(unit.Tree, absolute, unit.Body.At(unit.Body.Text.Length), containing);
                if (containing.Count == 0) continue;
                var kinds = string.Join(", ", containing);
                yield return Finding.In(unit, "edge-trigger instance '" + trigger + "' is called inside " + kinds + "; the edge detector may miss or consume a transition",
                    absolute, unit.Body.At(name.Index + name.Length), name.Value, trigger + "(...) in " + kinds);
            }
        }

        static void InsideBlocks(Block node, int offset, int fallbackEnd, List<string> result)
        {
            foreach (var child in node.Children)
            {
                if (child.Start > offset || offset >= (child.End ?? fallbackEnd)) continue;
                result.Add(child.Kind);
                InsideBlocks(child, offset, fallbackEnd, result);
                break;
            }
        }
    }
}
