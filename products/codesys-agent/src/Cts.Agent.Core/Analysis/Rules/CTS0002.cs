using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An input that is never referenced by its callable or owned methods.
    internal sealed class CTS0002 : Rule
    {
        static readonly Regex Identifier = new Regex(@"[A-Za-z_]\w*");

        internal CTS0002() : base("CTS0002", "Unused input", Analysis.Severity.Suspicious, "Interfaces", "VAR_INPUT members never read by their owner.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var inputs = unit.Members("VAR_INPUT").ToList();
            if (inputs.Count == 0) yield break;
            var candidates = new[] { unit }.Concat(context.Snapshot.OwnedBy(unit.QualifiedName));
            var tokens = new HashSet<string>();
            foreach (var candidate in candidates.Where(item => !string.IsNullOrEmpty(item.Implementation)))
            {
                var clean = Regex.Replace(candidate.Body.Text, @"\bTHIS\s*\.", " ", RegexOptions.IgnoreCase);
                clean = Regex.Replace(clean, @"\bSUPER\s*\^", " ", RegexOptions.IgnoreCase);
                foreach (Match match in Identifier.Matches(clean)) tokens.Add(match.Value.ToLowerInvariant());
            }
            foreach (var member in inputs)
            {
                if (tokens.Contains(member.Name.ToLowerInvariant())) continue;
                yield return Finding.In(unit, "input '" + member.Name + "' is never read by " + unit.QualifiedName + " or its methods/actions",
                    unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
            }
        }
    }
}
