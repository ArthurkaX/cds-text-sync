using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "IF i < u" with i : INT and u : UINT: the compiler widens both
    // silently and a negative i compares as a large number.
    internal sealed class CTS0055 : Rule
    {
        // Two plain variables: not a member after '.', not a bit or member access after the right one.
        static readonly Regex Comparison = new Regex(@"(?<![\w.])(?<left>[A-Za-z_]\w*)\s*(?<op><>|<=|>=|=|<|>)\s*(?<right>[A-Za-z_]\w*)\b(?!\s*\.)");

        internal CTS0055() : base("CTS0055", "Mixed signed and unsigned comparison", Analysis.Severity.Suspicious, "Correctness", "Comparisons must not mix signed and unsigned integer operands implicitly.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var types = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind == "scalar" && IecTypes.Range(shape.Base) != null && !types.ContainsKey(member.Name)) types[member.Name] = shape.Base.ToUpperInvariant();
            }
            if (types.Count < 2) yield break;
            var section = unit.Body;
            foreach (Match match in Comparison.Matches(section.Text))
            {
                if (!types.TryGetValue(match.Groups["left"].Value, out var left) || !types.TryGetValue(match.Groups["right"].Value, out var right)) continue;
                if (IecTypes.Range(left).Item1 < 0 == IecTypes.Range(right).Item1 < 0) continue;
                yield return Finding.In(unit, "comparison mixes signed " + left + " and unsigned " + right + " values; make the conversion explicit",
                    section.At(match.Index), section.At(match.Index + match.Length), match.Value, match.Value);
            }
        }
    }
}
