using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An IF/ELSIF/WHILE condition of literals only ("1 < 2", "NOT (3 = 3)")
    // that is always true or false (see StConstants). A bare TRUE or FALSE
    // is CTS0017's.
    internal sealed class CTS0048 : Rule
    {
        static readonly Regex Condition = new Regex(@"\b(?:IF|ELSIF|WHILE)\b(?<condition>.*?)\b(?:THEN|DO)\b", RegexOptions.IgnoreCase | RegexOptions.Singleline);

        internal CTS0048() : base("CTS0048", "Constant control-flow expression", Analysis.Severity.Suspicious, "Correctness", "A control-flow condition evaluates to a constant result.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            foreach (Match match in Condition.Matches(section.Text))
            {
                var group = match.Groups["condition"];
                var condition = group.Value.Trim();
                if (condition.Equals("TRUE", StringComparison.OrdinalIgnoreCase) || condition.Equals("FALSE", StringComparison.OrdinalIgnoreCase)) continue;
                if (!(StConstants.Value(condition) is bool result)) continue;
                var offset = section.At(group.Index + group.Value.Length - group.Value.TrimStart().Length);
                yield return Finding.In(unit, "control-flow condition " + Quoted(condition) + " is always " + (result ? "true" : "false"),
                    offset, offset + condition.Length, condition, condition);
            }
        }
    }
}
