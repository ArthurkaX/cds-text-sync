using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A `///` comment on the line of a declaration, after it. CODESYS takes
    // `///` as the documentation of the declaration below, so the line's own
    // variable shows no comment and the next one shows this one.
    internal sealed class CTS0101 : Rule
    {
        internal CTS0101() : base("CTS0101", "Documentation comment after a declaration", Analysis.Severity.Suspicious, "Code quality", "A /// comment documents the declaration below it, not the one on its line.", "ANY")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.DeclarationSection;
            if (section.IsEmpty) yield break;
            var lines = section.Lines().ToList();
            var comments = StText.Comments(section.Raw);
            var members = unit.Members().Where(member => member.Line >= 1 && member.Line <= lines.Count).OrderBy(member => member.Line).ToList();
            foreach (var group in members.GroupBy(member => member.Line))
            {
                var line = lines[group.Key - 1];
                var start = line.Item2 - section.Base;
                var comment = comments.FirstOrDefault(item => item.Start > start && item.Start < start + line.Item3.Length
                    && section.Raw.Substring(item.Start).StartsWith("///", StringComparison.Ordinal)
                    && section.Raw.Substring(start, item.Start - start).Trim().Length > 0);
                if (comment == null) continue;
                var name = group.First().Name;
                var next = members.FirstOrDefault(member => member.Line > group.Key);
                var offset = section.Base + comment.Start;
                yield return Finding.In(unit, "the /// comment after '" + name + "' documents " + (next == null ? "nothing" : "'" + next.Name + "'") + ", the declaration below it, not '" + name
                    + "'; put it on the line above '" + name + "', or write // for a comment of this line",
                    offset, offset + 3, name, line.Item3.Trim());
            }
        }
    }
}
