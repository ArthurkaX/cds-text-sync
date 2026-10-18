using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "IF p <> 0 AND p^ = 1": AND evaluates both operands, so p^ runs with
    // p = 0. AND_THEN or a nested IF guards; the condition ends at THEN, DO
    // or ';' and may span lines.
    internal sealed class CTS0082 : Rule
    {
        static readonly Regex Guard = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*<>\s*0\s+AND\b(?<tail>(?:(?!\b(?:THEN|DO)\b)[^;])*)", RegexOptions.IgnoreCase);
        static readonly Regex Dereference = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*\^");

        internal CTS0082() : base("CTS0082", "Pointer guard relies on short-circuit evaluation", Analysis.Severity.Danger, "Correctness", "A pointer dereference is guarded only by the left operand of AND.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var pointers = ProjectLookup.PointerMembers(unit, context);
            if (pointers.Count == 0) yield break;
            var section = unit.Body;
            foreach (Match match in Guard.Matches(section.Text))
            {
                var name = match.Groups["name"].Value;
                if (!pointers.ContainsKey(name.ToLowerInvariant())) continue;
                var dereference = Dereference.Matches(match.Groups["tail"].Value).Cast<Match>().FirstOrDefault(item => item.Groups["name"].Value.Equals(name, StringComparison.OrdinalIgnoreCase));
                if (dereference == null) continue;
                var end = match.Groups["tail"].Index + dereference.Index + dereference.Length;
                var expression = section.Text.Substring(match.Index, end - match.Index).Trim();
                yield return Finding.In(unit, "pointer '" + name + "' is dereferenced in an AND condition; do not rely on short-circuit evaluation for the null check",
                    section.At(match.Index), section.At(end), expression, expression);
            }
        }
    }
}
