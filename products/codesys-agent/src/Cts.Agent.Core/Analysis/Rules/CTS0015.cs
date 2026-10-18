using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A CASE label given twice: the second branch can never run.
    internal sealed class CTS0015 : Rule
    {
        static readonly Regex LabelSeparator = new Regex(@"\s*,\s*");

        internal CTS0015() : base("CTS0015", "Duplicate CASE label", Analysis.Severity.Danger, "Correctness", "CASE labels must be unique within each CASE statement.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (var block in unit.Tree.Descendants().Where(b => b.Kind == "CASE"))
            {
                var seen = new HashSet<string>();
                foreach (var branch in block.Branches)
                    foreach (var value in LabelSeparator.Split(branch.Label).Select(part => part.Trim().ToUpperInvariant()).Where(part => part.Length > 0 && part != "ELSE"))
                    {
                        if (!seen.Add(value))
                            yield return Finding.In(unit, "duplicate CASE label " + Quoted(value) + " makes a branch unreachable", branch.Start, branch.Start + branch.Label.Length, value, value);
                    }
            }
        }
    }
}
