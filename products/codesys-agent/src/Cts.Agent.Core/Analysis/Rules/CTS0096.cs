using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // A FUNCTION that writes project-global state through an assignment.
    internal sealed class CTS0096 : Rule
    {
        internal CTS0096() : base("CTS0096", "Function writes global state", Analysis.Severity.Suspicious, "Correctness", "A FUNCTION modifies project-global state instead of remaining side-effect free.", Analysis.Kinds.Function)
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var reported = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase);
            foreach (var access in context.Globals.AccessesFor(unit).Where(access => access.Write))
            {
                if (!reported.Add(access.Target)) continue;
                yield return Finding.In(unit,
                    "FUNCTION writes global '" + access.Target + "'; the side effect is hidden from the function's call contract",
                    access.Offset, access.EndOffset + 2, access.Target + " :=", access.Target + " :=");
            }
        }
    }
}
