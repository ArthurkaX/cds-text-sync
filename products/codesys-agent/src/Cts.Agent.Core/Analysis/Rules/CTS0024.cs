using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An output of a function, method, action or accessor written twice in
    // one block arm: the first value never leaves the call. Each IF/ELSIF/ELSE
    // and CASE arm is its own path, and "x := x + 1" builds on the old value.
    internal sealed class CTS0024 : Rule
    {
        static readonly Regex OutputArgument = new Regex(@"=>\s*(?<name>[A-Za-z_]\w*)");
        static readonly HashSet<string> CallKinds = new HashSet<string> { Analysis.Kinds.Function, Analysis.Kinds.Method, Analysis.Kinds.Action, Analysis.Kinds.PropertyGet, Analysis.Kinds.PropertySet };

        internal CTS0024() : base("CTS0024", "Multiple output writes", Analysis.Severity.Suspicious, "Interfaces", "Outputs written more than once along the same control-flow path.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (!CallKinds.Contains(unit.Kind)) yield break;
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var outputs = new Dictionary<string, VarMember>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in unit.Members("VAR_OUTPUT").Where(member => member.Name.Length > 0)) outputs[member.Name] = member;
            if (outputs.Count == 0) yield break;
            var text = section.Text;
            var writes = StBlocks.Assignment.Matches(text).Cast<Match>().Where(match => outputs.ContainsKey(match.Groups["name"].Value) && !BuildsOnItself(text, match))
                .Concat(OutputArgument.Matches(text).Cast<Match>().Where(match => outputs.ContainsKey(match.Groups["name"].Value)))
                .Select(match => Tuple.Create(match.Groups["name"].Value, section.At(match.Groups["name"].Index))).ToList();
            var end = section.At(text.Length);
            foreach (var group in writes.GroupBy(write => write.Item1.ToLowerInvariant() + "|" + unit.Tree.PathTo(write.Item2, end)))
            {
                var occurrences = group.ToList();
                if (occurrences.Count < 2) continue;
                var name = occurrences[1].Item1;
                foreach (var write in occurrences.Skip(1))
                    yield return Finding.In(unit, "output '" + name + "' is written more than once in the same control-flow block", write.Item2, write.Item2 + name.Length,
                        name, name + " : " + outputs[name].Type);
            }
        }

        static bool BuildsOnItself(string text, Match assignment)
        {
            var start = assignment.Index + assignment.Length;
            var statementEnd = text.IndexOf(';', start);
            if (statementEnd < 0) statementEnd = text.Length;
            return Regex.IsMatch(text.Substring(start, statementEnd - start), @"\b" + Regex.Escape(assignment.Groups["name"].Value) + @"\b", RegexOptions.IgnoreCase);
        }
    }
}
