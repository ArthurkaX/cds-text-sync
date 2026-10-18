using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // STRING handled as bytes: s[i], ADR(s), or a non-ASCII literal assigned
    // to it. All of them depend on the single-byte encoding the IDE uses.
    internal sealed class CTS0028 : Rule
    {
        static readonly Regex StringType = new Regex(@"^STRING(?:\s*\(|$)", RegexOptions.IgnoreCase);
        static readonly Regex Index = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*\[");
        static readonly Regex LiteralAssignment = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*:=\s*'(?<value>(?:''|[^'])*)'");
        static readonly Regex Assignment = new Regex(@"\G[A-Za-z_]\w*\s*:=");

        internal CTS0028() : base("CTS0028", "Suspicious STRING operation", Analysis.Severity.Suspicious, "Correctness", "STRING operations that can depend on the configured encoding.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var names = new HashSet<string>(context.Snapshot.MembersSeenBy(unit).Where(member => StringType.IsMatch(member.Type.Trim())).Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (names.Count == 0) yield break;
            foreach (Match match in Index.Matches(section.Text))
                if (names.Contains(match.Groups["name"].Value))
                    yield return Finding.In(unit, "indexed access to STRING may depend on single-byte encoding", section.At(match.Index), section.At(match.Index + match.Length),
                        match.Groups["name"].Value, match.Groups["name"].Value + "[...]");
            foreach (Match match in StCalls.AddressOf.Matches(section.Text))
                if (names.Contains(match.Groups["name"].Value))
                    yield return Finding.In(unit, "taking the address of STRING is encoding-sensitive", section.At(match.Index), section.At(match.Index + match.Length),
                        match.Groups["name"].Value, "ADR(" + match.Groups["name"].Value + ")");
            // The literal is read from the text as written; the blanked text
            // (same positions) tells an assignment from one in a comment.
            foreach (Match match in LiteralAssignment.Matches(section.Raw))
            {
                var name = match.Groups["name"].Value;
                var value = match.Groups["value"].Value.Replace("''", "'");
                if (!names.Contains(name) || !Assignment.IsMatch(section.Text, match.Index) || value.All(c => c <= 127)) continue;
                yield return Finding.In(unit, "non-ASCII literal assigned to STRING may be misencoded", section.At(match.Index), section.At(match.Index + match.Length),
                    name, name + " := '" + value + "'");
            }
        }
    }
}
