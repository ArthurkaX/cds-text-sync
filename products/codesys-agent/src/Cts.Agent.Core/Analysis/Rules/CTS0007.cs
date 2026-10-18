using System.Collections.Generic;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // Implementation indentation that disagrees with the ST block nesting,
    // measured by the scan cts fmt corrects it with.
    internal sealed class CTS0007 : Rule
    {
        internal CTS0007() : base("CTS0007", "Structural indentation", Analysis.Severity.Style, "Style", "Implementation indentation must reflect actual ST block nesting.", "CALLABLE")
        {
            Merge = "adjacent";
            Options["merge"] = true;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (string.IsNullOrEmpty(unit.Implementation)) yield break;
            var raw = unit.Body.Raw.Split('\n');
            var starts = new int[raw.Length];
            for (var i = 1; i < raw.Length; i++) starts[i] = starts[i - 1] + raw[i - 1].Length + 1;
            foreach (var row in StFormatter.ScanIndentation(raw, unit.Body.Text.Split('\n')))
            {
                if (row.Actual == row.Expected) continue;
                yield return Finding.In(unit, "structural indentation is inconsistent: block level " + row.Level + " expects an indent of " + row.Expected + " columns, the line has " + row.Actual,
                    unit.Body.At(starts[row.Index]), unit.Body.At(starts[row.Index] + row.Prefix.Length), "level:" + row.Level, raw[row.Index].TrimStart(' ', '\t'));
            }
        }
    }
}
