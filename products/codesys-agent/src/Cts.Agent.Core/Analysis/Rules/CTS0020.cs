using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An assignment to the POU's own VAR_INPUT (or a field or element of it).
    internal sealed class CTS0020 : Rule
    {
        static readonly Regex Assignment = new Regex(@"^\s*(?<lhs>(?<root>[A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*|\s*\[[^\]]+\])*)\s*:=", RegexOptions.IgnoreCase | RegexOptions.Singleline);

        internal CTS0020() : base("CTS0020", "Write to input variable", Analysis.Severity.Danger, "Interfaces", "VAR_INPUT parameters must not be modified by their owner POU.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var inputs = new HashSet<string>(unit.Members("VAR_INPUT").Select(member => member.Name.ToUpperInvariant()));
            if (inputs.Count == 0) yield break;
            foreach (var statement in section.Statements())
            {
                var match = Assignment.Match(statement.Value);
                if (!match.Success || !inputs.Contains(match.Groups["root"].Value.ToUpperInvariant())) continue;
                var lhs = match.Groups["lhs"];
                var offset = statement.Key + lhs.Index;
                yield return Finding.In(unit, "input '" + match.Groups["root"].Value + "' is written inside the POU", offset, offset + lhs.Length, match.Groups["root"].Value, statement.Value);
            }
        }
    }
}
