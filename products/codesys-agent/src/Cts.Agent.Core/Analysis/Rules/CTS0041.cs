using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Finds bit accesses whose literal index is outside the declared type width.
    internal sealed class CTS0041 : Rule
    {
        static readonly Regex Access = new Regex(@"\b(?<value>[A-Za-z_]\w*)\s*\.\s*(?<bit>\d+)");

        internal CTS0041() : base("CTS0041", "Bit index outside type width", Analysis.Severity.Danger, "Correctness", "A literal bit index must fit within the declared operand width.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            var widths = IecTypes.Widths(context.Snapshot.MembersSeenBy(unit));
            foreach (Match match in Access.Matches(unit.Body.Text))
            {
                var value = match.Groups["value"].Value;
                var bit = match.Groups["bit"];
                if (!widths.TryGetValue(value.ToLowerInvariant(), out var width)
                    || IecTypes.Literal(bit.Value) < width) continue;
                yield return Finding.In(unit,
                    "bit index " + bit.Value + " is outside the " + width + "-bit width of '" + value + "'",
                    unit.Body.At(bit.Index), unit.Body.At(bit.Index + bit.Length), match.Value, match.Value);
            }
        }
    }
}
