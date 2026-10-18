using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "ratio := a / b" with integer a, b and REAL ratio: the division
    // truncates before the conversion to REAL, so 7 / 2 gives 3.0. A
    // function's or method's own name is its result variable.
    internal sealed class CTS0077 : Rule
    {
        // Not a member after '.', not part of "1.5" or "16#10".
        static readonly Regex Assignment = new Regex(@"(?<![\w.])(?<target>[A-Za-z_]\w*)\s*:=\s*(?<expression>[^;]+)");
        static readonly Regex Division = new Regex(@"(?<![\w.#])(?<left>[A-Za-z_]\w*|[+-]?\d+)\s*/\s*(?<right>[A-Za-z_]\w*|[+-]?\d+)(?![\w.#])");

        internal CTS0077() : base("CTS0077", "Integer division assigned to floating point", Analysis.Severity.Suspicious, "Correctness", "Integer division must not silently discard the fractional part before a REAL assignment.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var types = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var header = unit.Header;
            if (header.Groups["type"].Success) types[header.Groups["name"].Value] = header.Groups["type"].Value.Trim().ToUpperInvariant();
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind == "scalar" && !types.ContainsKey(member.Name)) types[member.Name] = shape.Base.ToUpperInvariant();
            }
            var section = unit.Body;
            foreach (Match assignment in Assignment.Matches(section.Text))
            {
                if (!types.TryGetValue(assignment.Groups["target"].Value, out var target) || target != "REAL" && target != "LREAL") continue;
                var expression = assignment.Groups["expression"];
                foreach (Match division in Division.Matches(expression.Value))
                {
                    if (!IsInteger(division.Groups["left"].Value, types) || !IsInteger(division.Groups["right"].Value, types)) continue;
                    var start = expression.Index + division.Index;
                    yield return Finding.In(unit, "integer division '" + division.Value + "' loses its fractional part before assignment to " + target + "; convert an operand to REAL",
                        section.At(start), section.At(start + division.Length), division.Value, division.Value);
                }
            }
        }

        static bool IsInteger(string operand, Dictionary<string, string> types) =>
            IecTypes.IsDecimal(operand) || types.TryGetValue(operand, out var type) && IecTypes.Range(type) != null;
    }
}
