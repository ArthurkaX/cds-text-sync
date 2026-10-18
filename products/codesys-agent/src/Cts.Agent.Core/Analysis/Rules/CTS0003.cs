using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // A CASE block that has no explicit fallback branch, unless its labels
    // name every member of one project enum.
    internal sealed class CTS0003 : Rule
    {
        internal CTS0003() : base("CTS0003", "CASE without ELSE", Analysis.Severity.Suspicious, "Correctness", "CASE statements must explicitly handle unexpected values.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "CASE" && block.Branches.All(branch => branch.Label != "ELSE")))
            {
                if (EnumType.Covers(block, context.Enums)) continue;
                yield return Finding.In(unit, "CASE statement has no ELSE branch for unexpected values", unit.Body.At(block.Start - unit.Body.Base),
                    anchor: "CASE", context: "CASE without ELSE");
            }
        }
    }
}
