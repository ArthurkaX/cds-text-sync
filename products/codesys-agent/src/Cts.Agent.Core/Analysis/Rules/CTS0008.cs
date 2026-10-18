using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // Declarations of one group (the lines cts fmt aligns together) that do
    // not share the group's indentation or the ':' column cts fmt gives it
    // (StFormatter.TableColumn), both measured as the editor shows them
    // (StFormatter.Width: a tab to the next stop).
    internal sealed class CTS0008 : Rule
    {
        internal CTS0008() : base("CTS0008", "Variable declaration alignment", Analysis.Severity.Style, "Style", "Variable declarations in one group should form a readable aligned table.")
        {
            Merge = "adjacent";
            Options["merge"] = true;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.DeclarationSection;
            if (section.IsEmpty) yield break;
            var clean = section.Text.Split('\n');
            var raw = section.Raw.Split('\n');
            var starts = new int[raw.Length];
            for (var i = 1; i < raw.Length; i++) starts[i] = starts[i - 1] + raw[i - 1].Length + 1;
            foreach (var group in StFormatter.DeclarationGroups(clean).Where(group => group.Count > 1))
            {
                var rows = group.Select(index => new { Index = index, Match = StFormatter.Declaration.Match(clean[index]), Colon = StFormatter.Width(clean[index].Substring(0, clean[index].IndexOf(':'))) }).ToList();
                var indent = StFormatter.Width(rows[0].Match.Groups["indent"].Value);
                var column = StFormatter.TableColumn(rows.Select(row => row.Colon).ToList(), rows.Max(row => StFormatter.Width(rows[0].Match.Groups["indent"].Value + row.Match.Groups["names"].Value)));
                foreach (var row in rows)
                {
                    var problems = new List<string>();
                    if (StFormatter.Width(row.Match.Groups["indent"].Value) != indent) problems.Add("base indentation differs from the declaration group");
                    if (row.Colon != column) problems.Add("the ':' is not aligned with the declaration group");
                    if (problems.Count == 0) continue;
                    var start = section.At(starts[row.Index]);
                    yield return Finding.In(unit, "variable declaration is not aligned: " + string.Join("; ", problems), start,
                        start + row.Match.Groups["indent"].Length + row.Match.Groups["names"].Length, "column:" + column, raw[row.Index].Trim());
                }
            }
        }
    }
}
