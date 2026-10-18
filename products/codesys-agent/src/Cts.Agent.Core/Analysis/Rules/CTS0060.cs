using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "p^" with no "p <> 0" guarding it, not after "IF p = 0 THEN ...
    // RETURN" and not last set from ADR(...) on the path (see NonZeroFlow):
    // a null pointer faults the PLC. "p <> 0 AND p^" in
    // one condition is CTS0082's finding.
    internal sealed class CTS0060 : Rule
    {
        static readonly Regex Dereference = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)\s*\^");
        // Where the condition or statement holding a use starts.
        static readonly Regex SegmentStart = new Regex(@";|\b(?:THEN|DO)\b", RegexOptions.IgnoreCase | RegexOptions.RightToLeft);
        static readonly Regex ShortCircuit = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*<>\s*0\s+AND\b", RegexOptions.IgnoreCase);

        internal CTS0060() : base("CTS0060", "Unchecked pointer dereference", Analysis.Severity.Danger, "Correctness", "A pointer is dereferenced without a simple dominating null check.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var pointers = new HashSet<string>(context.Snapshot.MembersSeenBy(unit).Where(member => StDeclarations.ClassifyType(member.Type).Base == "POINTER").Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (pointers.Count == 0) yield break;
            var section = unit.Body;
            var flow = new NonZeroFlow(unit, context, true);
            foreach (Match match in Dereference.Matches(section.Text))
            {
                var name = match.Groups["name"].Value;
                if (!pointers.Contains(name) || InShortCircuit(section.Text, name, match.Index)) continue;
                var offset = section.At(match.Index);
                if (flow.At(name, offset) == true) continue;
                var expression = match.Value.Trim();
                yield return Finding.In(unit, "pointer '" + name + "' is dereferenced without a dominating non-null check",
                    offset, section.At(match.Index + match.Length), expression, expression);
            }
        }

        static bool InShortCircuit(string text, string name, int offset)
        {
            var start = SegmentStart.Match(text, 0, offset);
            var from = start.Success ? start.Index + start.Length : 0;
            return ShortCircuit.Matches(text.Substring(from, offset - from)).Cast<Match>().Any(guard => guard.Groups["name"].Value.Equals(name, StringComparison.OrdinalIgnoreCase));
        }
    }
}
