using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "a / x" with no "x <> 0" (or "x > 0", ...) guarding it and not after
    // "IF x = 0 THEN ... RETURN" (see Guards); inside "IF x = 0" the
    // division is a certain fault. A reassignment of x voids the guard.
    // "a / INT_TO_REAL(x)" checks x; another call's result is not checked,
    // nor a constant or a local declared non-zero that no code changes. What
    // the path proves about x is NonZeroFlow's.
    internal sealed class CTS0050 : Rule
    {
        // A named divisor, not a typed literal ("INT#5").
        static readonly Regex Division = new Regex(@"/\s*(?<name>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\b(?!\s*#)");
        static readonly Regex Call = new Regex(@"\G\s*\(");
        static readonly Regex Argument = new Regex(@"\G\s*\(\s*(?<name>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*\)");

        internal CTS0050() : base("CTS0050", "Possible zero divisor", Analysis.Severity.Danger, "Correctness", "A variable divisor is not protected by a simple non-zero path check.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            var flow = new NonZeroFlow(unit, context, false);
            foreach (Match match in Division.Matches(section.Text))
            {
                var name = match.Groups["name"];
                var after = match.Index + match.Length;
                if (Call.IsMatch(section.Text, after))
                {
                    var argument = Argument.Match(section.Text, after);
                    if (!NonZeroFlow.Conversion.IsMatch(name.Value) || !argument.Success) continue;
                    name = argument.Groups["name"];
                }
                var divisor = name.Value;
                var offset = section.At(name.Index);
                var state = flow.At(divisor, offset);
                if (state == true) continue;
                yield return Finding.In(unit, state == false
                        ? "division by '" + divisor + "' occurs on a branch where the divisor is proven to be zero"
                        : "division by '" + divisor + "' is not protected by a simple non-zero check on this path",
                    offset, offset + divisor.Length, divisor, match.Value.Trim());
            }
        }
    }
}
