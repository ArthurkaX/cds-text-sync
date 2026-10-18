using System;
using System.Collections.Generic;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "short := long" between STRING(n) variables cuts the value to the
    // shorter capacity without a word.
    internal sealed class CTS0079 : Rule
    {
        // Two plain variables: not a member after '.', not a member, element or call on the right.
        static readonly Regex Assignment = new Regex(@"(?<![\w.])(?<target>[A-Za-z_]\w*)\s*:=\s*(?<source>[A-Za-z_]\w*)\b(?!\s*[.\[(])");

        internal CTS0079() : base("CTS0079", "String assignment may truncate the destination", Analysis.Severity.Danger, "Correctness", "Assignments between explicitly bounded strings must preserve the destination capacity.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var capacities = new Dictionary<string, BigInteger>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var bounded = IecTypes.StringType.Match(member.Type.Trim());
                if (bounded.Success) capacities[member.Name] = BigInteger.Parse(bounded.Groups["size"].Value);
            }
            if (capacities.Count == 0 || unit.Body.IsEmpty) yield break;

            foreach (Match match in Assignment.Matches(unit.Body.Text))
            {
                var target = match.Groups["target"].Value;
                var source = match.Groups["source"].Value;
                if (!capacities.TryGetValue(target, out var targetCapacity) || !capacities.TryGetValue(source, out var sourceCapacity) || sourceCapacity <= targetCapacity)
                    continue;
                var expression = match.Value;
                yield return Finding.In(unit, "STRING(" + sourceCapacity + ") value assigned to " + target + " STRING(" + targetCapacity + ") may be truncated",
                    unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length), expression, expression);
            }
        }
    }
}
