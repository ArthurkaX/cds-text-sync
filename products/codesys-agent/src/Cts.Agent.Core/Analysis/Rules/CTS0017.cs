using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // IF TRUE THEN / WHILE FALSE DO: a condition left as a stub.
    internal sealed class CTS0017 : Rule
    {
        static readonly Regex Condition = new Regex(@"\b(?<keyword>IF|ELSIF|WHILE)\s+(?<value>TRUE|FALSE)\s+(?<delimiter>THEN|DO)\b", RegexOptions.IgnoreCase);

        internal CTS0017() : base("CTS0017", "Constant control-flow condition", Analysis.Severity.Suspicious, "Code quality", "Literal TRUE/FALSE conditions that commonly mark temporary stubs.", "CALLABLE")
        {
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (Match match in Condition.Matches(section.Text))
            {
                var value = match.Groups["value"];
                yield return Finding.In(unit, "constant condition " + value.Value.ToUpperInvariant() + " looks like a temporary stub", section.At(value.Index), section.At(value.Index + value.Length),
                    value.Value.ToUpperInvariant(), match.Value);
            }
        }
    }
}
