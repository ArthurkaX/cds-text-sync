using System;
using System.Collections.Generic;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "b > 300" for a BYTE b: the comparison has one answer for every value
    // the type can hold.
    internal sealed class CTS0043 : Rule
    {
        static readonly Regex Compare = new Regex(@"\b(?<value>[A-Za-z_]\w*)\s*(?<op><>|<=|>=|=|<|>)\s*(?<const>[+-]?\d+)\b");

        internal CTS0043() : base("CTS0043", "Comparison outside type range", Analysis.Severity.Suspicious, "Correctness", "A comparison is always true or false across the variable's type range.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var ranges = new Dictionary<string, Tuple<BigInteger, BigInteger>>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                var range = shape.Kind == "scalar" ? IecTypes.Range(shape.Base) : null;
                if (range != null && !ranges.ContainsKey(member.Name)) ranges[member.Name] = range;
            }
            if (ranges.Count == 0) yield break;
            foreach (Match match in Compare.Matches(section.Text))
            {
                if (!ranges.TryGetValue(match.Groups["value"].Value, out var range)) continue;
                var result = Constant(match.Groups["op"].Value, range.Item1, range.Item2, IecTypes.Literal(match.Groups["const"].Value));
                if (result == null) continue;
                yield return Finding.In(unit, "comparison is " + (result.Value ? "always true" : "always false") + " for the full type range [" + range.Item1 + ".." + range.Item2 + "]",
                    section.At(match.Index), section.At(match.Index + match.Length), match.Value, match.Value);
            }
        }

        // The comparison's answer when it is the same for every value in [low..high], else null.
        static bool? Constant(string op, BigInteger low, BigInteger high, BigInteger constant)
        {
            var outside = constant < low || constant > high;
            switch (op)
            {
                case "=": return outside ? false : (bool?)null;
                case "<>": return outside ? true : (bool?)null;
                case "<": return low >= constant ? false : high < constant ? true : (bool?)null;
                case "<=": return low > constant ? false : high <= constant ? true : (bool?)null;
                case ">": return high <= constant ? false : low > constant ? true : (bool?)null;
                default: return high < constant ? false : low >= constant ? true : (bool?)null;
            }
        }
    }
}
