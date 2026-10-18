using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "x := x;": a variable written back to itself.
    internal sealed class CTS0021 : Rule
    {
        static readonly Regex SelfAssignment = new Regex(@"^\s*(?<target>[A-Za-z_]\w*)\s*:=\s*(?<source>[A-Za-z_]\w*)\s*\z", RegexOptions.IgnoreCase | RegexOptions.Singleline);

        internal CTS0021() : base("CTS0021", "Self-assignment", Analysis.Severity.Suspicious, "Dead code", "Simple assignments that write a variable back to itself.", "CALLABLE")
        {
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (var statement in section.Statements())
            {
                var match = SelfAssignment.Match(statement.Value);
                if (!match.Success) continue;
                var target = match.Groups["target"];
                if (!string.Equals(target.Value, match.Groups["source"].Value, StringComparison.OrdinalIgnoreCase)) continue;
                var offset = statement.Key + target.Index;
                yield return Finding.In(unit, "assignment to '" + target.Value + "' has no effect", offset, offset + target.Length, target.Value, statement.Value);
            }
        }
    }
}
