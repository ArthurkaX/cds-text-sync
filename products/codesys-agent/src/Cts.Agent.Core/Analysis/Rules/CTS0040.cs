using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Finds literal shift amounts that do not fit the operand's known bit width.
    internal sealed class CTS0040 : Rule
    {
        static readonly Regex Call = new Regex(@"\b(?:SHL|SHR|ROL|ROR)\s*\(\s*(?<value>[A-Za-z_]\w*)\s*,\s*(?<amount>[+-]?\d+)\s*\)", RegexOptions.IgnoreCase);

        internal CTS0040() : base("CTS0040", "Shift amount outside operand width", Analysis.Severity.Danger, "Correctness", "A literal shift amount is greater than or equal to the operand width.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            var widths = IecTypes.Widths(context.Snapshot.MembersSeenBy(unit));
            foreach (Match match in Call.Matches(unit.Body.Text))
            {
                var value = match.Groups["value"].Value;
                if (!widths.TryGetValue(value.ToLowerInvariant(), out var width)
                    || IecTypes.Literal(match.Groups["amount"].Value) < width) continue;
                var amount = match.Groups["amount"];
                yield return Finding.In(unit,
                    "shift amount " + amount.Value + " is outside the " + width + "-bit width of '" + value + "'",
                    unit.Body.At(amount.Index), unit.Body.At(amount.Index + amount.Length), amount.Value, match.Value);
            }
        }
    }
}
