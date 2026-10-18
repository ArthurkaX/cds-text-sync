using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // "IF a THEN ... ELSIF a THEN", "IF a THEN ... ELSIF a AND b THEN":
    // the later arm can never run.
    internal sealed class CTS0036 : Rule
    {
        internal CTS0036() : base("CTS0036", "Duplicate IF condition", Analysis.Severity.Suspicious, "Correctness", "An IF/ELSIF chain repeats a condition, or has one that holds only when an earlier one does.", "CALLABLE")
        {
            Requires = new[] { Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "IF"))
            {
                var earlier = new List<string>();
                foreach (var branch in block.Branches)
                {
                    var condition = Guards.ConditionOf(branch.Label);
                    if (condition == null) continue;
                    var repeated = earlier.Any(other => StText.Squeezed(other).Equals(StText.Squeezed(condition), System.StringComparison.OrdinalIgnoreCase));
                    if (repeated || earlier.Count > 0 && BoolLogic.Covered(earlier, condition))
                    {
                        var header = branch.Start - section.Base;
                        var start = section.At(System.Math.Max(header, section.Text.IndexOf(condition, header, System.StringComparison.Ordinal)));
                        yield return Finding.In(unit, repeated ? "IF/ELSIF chain repeats a condition; this branch is unreachable"
                            : "an earlier condition of the IF/ELSIF chain holds whenever this one does; this branch is unreachable", start, start + condition.Length, condition, branch.Label.Trim());
                    }
                    earlier.Add(condition);
                }
            }
        }
    }
}
