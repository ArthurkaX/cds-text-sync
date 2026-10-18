using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Assignment between function-block instances can copy their internal state.
    internal sealed class CTS0088 : Rule
    {
        static readonly Regex Assignment = new Regex(@"\b(?<left>[A-Za-z_]\w*)\s*:=\s*(?<right>[A-Za-z_]\w*)\b");

        internal CTS0088() : base("CTS0088", "Stateful function-block assignment", Analysis.Severity.Danger, "Correctness", "Assignment between FB instances can silently copy their internal state.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var functionBlockTypes = ProjectLookup.FunctionBlockTypes(context);
            var instances = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
                if (ProjectLookup.IsFunctionBlockType(member.Type, functionBlockTypes)) instances[member.Name] = member.Type.Trim();
            foreach (var global in ProjectLookup.GlobalMembers(context).Values.Select(entry => entry.Item2))
                if (ProjectLookup.IsFunctionBlockType(global.Type, functionBlockTypes) && !instances.ContainsKey(global.Name)) instances[global.Name] = global.Type.Trim();
            if (instances.Count == 0 || unit.Body.IsEmpty) yield break;

            foreach (Match match in Assignment.Matches(unit.Body.Text))
            {
                var left = match.Groups["left"].Value;
                var right = match.Groups["right"].Value;
                if (left.Equals(right, StringComparison.OrdinalIgnoreCase) || !instances.ContainsKey(left) || !instances.ContainsKey(right)) continue;
                yield return Finding.In(unit, "assignment copies state from function-block instance '" + right + "' to '" + left + "'",
                    unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length), left + " := " + right, match.Value);
            }
        }
    }
}
