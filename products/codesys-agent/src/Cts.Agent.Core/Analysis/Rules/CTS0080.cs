using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // "s := CONCAT(a, b)" where the longest result (string capacities and
    // literal lengths, nested CONCATs summed) exceeds s's STRING(n). s itself
    // among the arguments counts as empty: appending to a string is reported
    // only when what is appended does not fit even then.
    internal sealed class CTS0080 : Rule
    {
        static readonly Regex Assignment = new Regex(@"\b(?<target>[A-Za-z_]\w*)\s*:=\s*(?<expression>[^;]+)");
        static readonly Regex Concat = new Regex(@"^CONCAT\s*\(", RegexOptions.IgnoreCase);

        internal CTS0080() : base("CTS0080", "CONCAT result exceeds string capacity", Analysis.Severity.Danger, "Correctness", "Provably oversized CONCAT results must not be assigned to a smaller STRING.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var capacities = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
                if (IecTypes.StringCapacity(member.Type) is int capacity && !capacities.ContainsKey(member.Name)) capacities[member.Name] = capacity;
            if (capacities.Count == 0) yield break;
            var section = unit.Body;
            var source = StText.Blank(section.Raw);
            foreach (Match assignment in Assignment.Matches(source))
            {
                var target = assignment.Groups["target"].Value;
                var expression = assignment.Groups["expression"];
                var call = expression.Value.Trim();
                if (!capacities.TryGetValue(target, out var capacity) || !Concat.IsMatch(call) || !(Length(call, target, capacities) is int length) || length <= capacity) continue;
                var start = expression.Index + expression.Value.Length - expression.Value.TrimStart().Length;
                yield return Finding.In(unit, "CONCAT result can contain " + length + " characters but " + target + " is limited to STRING(" + capacity + ")",
                    section.At(start), section.At(start + call.Length), call, call);
            }
        }

        // The most characters an expression can hold: a literal's length, a
        // string variable's capacity (none for target), a two-argument
        // CONCAT's sum; else null.
        static int? Length(string expression, string target, Dictionary<string, int> capacities)
        {
            if (IecTypes.StringLength(expression) is int literal) return literal;
            if (expression.Equals(target, StringComparison.OrdinalIgnoreCase)) return 0;
            if (StText.IsIdentifier(expression)) return capacities.TryGetValue(expression, out var capacity) ? capacity : (int?)null;
            var call = Concat.Match(expression);
            if (!call.Success) return null;
            var opening = call.Length - 1;
            if (StCalls.Close(expression, opening) != expression.Length - 1) return null;
            var arguments = StCalls.Arguments(expression.Substring(opening + 1, expression.Length - opening - 2));
            if (arguments.Count != 2) return null;
            var lengths = arguments.Select(argument => Length(argument, target, capacities)).ToList();
            return lengths.All(length => length.HasValue) ? lengths.Sum() : null;
        }
    }
}
