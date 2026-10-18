using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // "x = x", "a.b <> a.b": the answer is fixed, so the code meant to
    // compare two different values.
    internal sealed class CTS0047 : Rule
    {
        // Not from inside a name: a later letter of it cannot match where its start did not.
        static readonly Regex Comparison = new Regex(@"(?<![A-Za-z_])(?<left>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?)\s*(?<operator><>|<=|>=|=|<|>)\s*(?<right>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?)");
        static readonly HashSet<string> AlwaysTrue = new HashSet<string> { "=", "<=", ">=" };

        internal CTS0047() : base("CTS0047", "Self-comparison", Analysis.Severity.Suspicious, "Correctness", "A value is compared with itself, making the result constant.", "CALLABLE")
        {
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (Match match in Comparison.Matches(section.Text))
            {
                if (!string.Equals(StText.Unspaced(match.Groups["left"].Value), StText.Unspaced(match.Groups["right"].Value), StringComparison.OrdinalIgnoreCase)) continue;
                var result = AlwaysTrue.Contains(match.Groups["operator"].Value) ? "always true" : "always false";
                yield return Finding.In(unit, "self-comparison '" + match.Value + "' is " + result + " and does not test two independent values", section.At(match.Index), section.At(match.Index + match.Length),
                    match.Value, match.Value);
            }
        }
    }
}
