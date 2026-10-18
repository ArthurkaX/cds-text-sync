using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Variable declarations whose array bounds contain exactly one element.
    internal sealed class CTS0069 : Rule
    {
        static readonly Regex OneDimension = new Regex(
            @"^ARRAY\s*\[\s*(?<low>[^.]+?)\s*\.\.\s*(?<high>[^]]+?)\s*\]\s+OF\s+",
            RegexOptions.IgnoreCase | RegexOptions.Singleline);

        internal CTS0069() : base("CTS0069", "Single-element array", Analysis.Severity.Style, "Style", "Arrays with one element should be represented by a scalar variable.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (var member in unit.Members())
            {
                var match = OneDimension.Match((member.Type ?? "").Trim());
                if (!match.Success || match.Groups["low"].Value.Trim() != match.Groups["high"].Value.Trim()) continue;
                var name = member.Name ?? "";
                yield return Finding.In(unit, "array '" + name + "' has only one element; use a scalar variable",
                    unit.MemberOffset(member), anchor: name, context: name + " : " + (member.Type ?? ""));
            }
        }
    }
}
