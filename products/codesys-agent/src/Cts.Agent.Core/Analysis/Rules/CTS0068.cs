using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Direct hardware addresses used in executable Structured Text.
    internal sealed class CTS0068 : Rule
    {
        static readonly Regex DirectAddress = new Regex(
            @"(?<![A-Za-z0-9_])%(?:I|Q|M)(?:X|B|W|D|L)(?:\d+(?:\.\d+)?)(?![A-Za-z0-9_])",
            RegexOptions.IgnoreCase);

        internal CTS0068() : base("CTS0068", "Direct hardware address in logic", Analysis.Severity.Suspicious, "Code quality", "Use symbolic variables for hardware addresses instead of direct addresses in logic.", "CALLABLE")
        {
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (Match match in DirectAddress.Matches(unit.Body.Text))
            {
                var address = match.Value;
                var offset = unit.Body.At(match.Index);
                yield return Finding.In(unit, "direct hardware address '" + address + "' is used in executable logic",
                    offset, offset + address.Length, address, address);
            }
        }
    }
}
