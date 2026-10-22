using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Assignments between differently typed pointers lack an explicit conversion.
    internal sealed class CTS0091 : Rule
    {
        // Whole names on both sides: not a field (p^.q, a.b) nor what is
        // read through one (p^, a[i], f(x)).
        static readonly Regex Assignment = new Regex(@"(?<![\w.])(?<!\.\s*)(?<left>[A-Za-z_]\w*)\s*:=\s*(?<right>[A-Za-z_]\w*)\b(?!\s*[\^.\[(])");

        internal CTS0091() : base("CTS0091", "Implicit pointer conversion", Analysis.Severity.Danger, "Correctness", "Incompatible pointer bases are assigned without an explicit conversion.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            var pointers = ProjectLookup.PointerMembers(unit, context);
            foreach (Match match in Assignment.Matches(unit.Body.Text))
            {
                if (!pointers.TryGetValue(match.Groups["left"].Value.ToLowerInvariant(), out var left)
                    || !pointers.TryGetValue(match.Groups["right"].Value.ToLowerInvariant(), out var right)
                    || left.Item2 == right.Item2
                    || left.Item2 == "byte" || right.Item2 == "byte") continue;

                yield return Finding.In(unit,
                    "pointer '" + right.Item1 + "' to " + right.Item2 + " is assigned to pointer '" + left.Item1 + "' to " + left.Item2 + " without an explicit conversion",
                    unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length), match.Value, match.Value);
            }
        }
    }
}
