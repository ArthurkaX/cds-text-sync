using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A division whose divisor is an ordinary or typed numeric zero literal.
    internal sealed class CTS0035 : Rule
    {
        static readonly Regex ZeroDivisor = new Regex(
            @"/(?<space>\s*)(?<zero>(?:(?:BOOL|BYTE|WORD|DWORD|LWORD|SINT|USINT|INT|UINT|DINT|UDINT|LINT|ULINT|REAL|LREAL)#)?0(?:\.0*)?(?:[eE][+-]?0+)?)(?![\w.])",
            RegexOptions.IgnoreCase);

        internal CTS0035() : base("CTS0035", "Division by literal zero", Analysis.Severity.Danger, "Correctness", "Division expressions whose divisor is a literal zero.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            foreach (Match match in ZeroDivisor.Matches(unit.Body.Text))
            {
                var literal = match.Groups["zero"];
                yield return Finding.In(unit, "division by a literal zero", unit.Body.At(literal.Index), unit.Body.At(literal.Index + literal.Length),
                    literal.Value, match.Value);
            }
        }
    }
}
