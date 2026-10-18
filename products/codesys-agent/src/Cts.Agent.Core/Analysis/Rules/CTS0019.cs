using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An output of a function, method, action or accessor that some paths
    // leave unassigned. Block.Covers decides: a complete IF or CASE whose
    // every branch assigns, or a loop that surely runs once.
    internal sealed class CTS0019 : Rule
    {
        static readonly Regex OutputArgument = new Regex(@"=>\s*(?<name>[A-Za-z_]\w*)");
        static readonly HashSet<string> CallKinds = new HashSet<string> { Analysis.Kinds.Function, Analysis.Kinds.Method, Analysis.Kinds.Action, Analysis.Kinds.PropertyGet, Analysis.Kinds.PropertySet };

        internal CTS0019() : base("CTS0019", "Output not assigned on all paths", Analysis.Severity.Suspicious, "Interfaces", "Outputs assigned only on some conditional paths.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (!CallKinds.Contains(unit.Kind)) yield break;
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var outputs = unit.Members("VAR_OUTPUT").ToList();
            if (outputs.Count == 0) yield break;
            var assignments = StBlocks.Assignment.Matches(section.Text).Cast<Match>().Concat(OutputArgument.Matches(section.Text).Cast<Match>())
                .Select(match => Tuple.Create(match.Groups["name"].Value, section.At(match.Groups["name"].Index))).ToList();
            var root = unit.Tree;
            foreach (var member in outputs)
            {
                // CTS0009 owns the never-assigned case.
                var writes = assignments.Where(write => write.Item1.Equals(member.Name, StringComparison.OrdinalIgnoreCase)).Select(write => write.Item2).ToList();
                if (writes.Count == 0 || root.Covers(writes, root.Start, section.At(section.Text.Length))) continue;
                yield return Finding.In(unit, "output '" + member.Name + "' is not assigned on all control-flow paths", writes[0], writes[0] + member.Name.Length,
                    member.Name, member.Name + " : " + member.Type);
            }
        }
    }
}
