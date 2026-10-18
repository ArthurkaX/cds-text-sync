using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A simple assignment immediately overwritten before its value is read.
    internal sealed class CTS0012 : Rule
    {
        static readonly Regex SimpleAssignment = new Regex(@"(?s)^\s*(?<name>[A-Za-z_]\w*)\s*:=\s*(?<expression>.+?)\s*$");
        static readonly Regex SelfUpdate = new Regex(@"(?is)^\s*(?<name>[A-Za-z_]\w*)\s*(?:\+|-|\*|/|MOD|AND|OR|XOR)\s*.+$");
        static readonly Regex ConcatUpdate = new Regex(@"(?is)^\s*CONCAT\s*\(\s*(?<name>[A-Za-z_]\w*)\s*,");

        internal CTS0012() : base("CTS0012", "Overwrite without read", Analysis.Severity.Suspicious, "Dead code", "Assignments that are immediately overwritten before being read.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (string.IsNullOrEmpty(unit.Implementation)) yield break;
            string previousName = null;
            int? previousOffset = null;
            string previousStatement = null;
            foreach (var item in unit.Body.Statements())
            {
                var match = SimpleAssignment.Match(item.Value);
                if (!match.Success)
                {
                    previousName = null;
                    previousOffset = null;
                    previousStatement = null;
                    continue;
                }
                var name = match.Groups["name"].Value;
                var expression = match.Groups["expression"].Value;
                if (previousName != null && string.Equals(previousName, name, System.StringComparison.OrdinalIgnoreCase) && !IsSelfUpdate(name, expression))
                {
                    yield return Finding.In(unit, "assignment to '" + previousName + "' is overwritten before the value is read",
                        previousOffset, previousOffset + previousName.Length, anchor: previousName, context: previousStatement);
                }
                previousName = name;
                previousOffset = item.Key;
                previousStatement = item.Value;
            }
        }

        static bool IsSelfUpdate(string name, string expression)
        {
            var selfUpdate = SelfUpdate.Match(expression);
            if (selfUpdate.Success && string.Equals(selfUpdate.Groups["name"].Value, name, System.StringComparison.OrdinalIgnoreCase)) return true;
            var concatUpdate = ConcatUpdate.Match(expression);
            return concatUpdate.Success && string.Equals(concatUpdate.Groups["name"].Value, name, System.StringComparison.OrdinalIgnoreCase);
        }
    }
}
