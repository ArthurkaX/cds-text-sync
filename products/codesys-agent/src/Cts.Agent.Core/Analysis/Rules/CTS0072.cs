using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An address of a VAR_OUTPUT value passed through ADR().
    internal sealed class CTS0072 : Rule
    {

        internal CTS0072() : base("CTS0072", "Escaping address of VAR_OUTPUT", Analysis.Severity.Suspicious, "Interfaces", "Addresses of VAR_OUTPUT values should not be exposed through ADR().", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var outputNames = new HashSet<string>(unit.Members("VAR_OUTPUT").Select(member => member.Name), System.StringComparer.OrdinalIgnoreCase);
            if (outputNames.Count == 0 || unit.Body.IsEmpty)
            {
                yield break;
            }

            foreach (Match match in StCalls.AddressOf.Matches(unit.Body.Text))
            {
                var name = match.Groups["name"].Value;
                if (!outputNames.Contains(name))
                {
                    continue;
                }

                yield return Finding.In(unit,
                    "address of VAR_OUTPUT '" + name + "' is exposed through ADR(); avoid aliases that can outlive this POU call",
                    unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length),
                    anchor: "ADR(" + name + ")", context: match.Value);
            }
        }
    }
}
