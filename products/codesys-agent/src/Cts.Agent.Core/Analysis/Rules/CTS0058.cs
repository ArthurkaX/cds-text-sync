using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A TIME literal below zero or above 2^32-1 ms (T#50d, T#-1s): a 32-bit
    // TIME cannot hold it. LTIME literals are not TIME literals.
    internal sealed class CTS0058 : Rule
    {
        static readonly Regex TimeLiteral = new Regex(@"(?<![A-Za-z0-9_])(?<literal>(?:TIME|T)#(?<sign>[+-]?)(?<parts>(?:\d+(?:\.\d+)?(?:ms|us|ns|d|h|m|s))+))\b", RegexOptions.IgnoreCase);
        static readonly Regex Part = new Regex(@"\G(?<value>\d+(?:\.\d+)?)(?<unit>ms|us|ns|d|h|m|s)", RegexOptions.IgnoreCase);
        static readonly Dictionary<string, decimal> UnitMilliseconds = new Dictionary<string, decimal>(StringComparer.OrdinalIgnoreCase)
        {
            ["d"] = 86400000m, ["h"] = 3600000m, ["m"] = 60000m, ["s"] = 1000m, ["ms"] = 1m, ["us"] = 0.001m, ["ns"] = 0.000001m,
        };
        const decimal MaxTime = uint.MaxValue;

        internal CTS0058() : base("CTS0058", "TIME literal outside range", Analysis.Severity.Danger, "Correctness", "A 32-bit TIME literal is outside its representable range.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            // Without an IMPLEMENTATION marker the body is the whole text, declaration included.
            var sections = unit.Implementation == null ? new[] { unit.Body } : new[] { unit.DeclarationSection, unit.Body };
            foreach (var section in sections)
                foreach (Match match in TimeLiteral.Matches(section.Text))
                {
                    var value = Milliseconds(match.Groups["parts"].Value, match.Groups["sign"].Value == "-");
                    if (value >= 0 && value <= MaxTime) continue;
                    var literal = match.Groups["literal"];
                    var message = value == null
                        ? "TIME literal " + literal.Value + " is far outside the 32-bit TIME range [0.." + MaxTime + " ms]"
                        : "TIME literal " + literal.Value + " evaluates to " + value.Value.ToString(CultureInfo.InvariantCulture) + " ms outside the 32-bit TIME range [0.." + MaxTime + " ms]";
                    yield return Finding.In(unit, message, section.At(literal.Index), section.At(literal.Index + literal.Length), literal.Value, literal.Value);
                }
        }

        // The literal's milliseconds, null when they overflow a decimal.
        static decimal? Milliseconds(string parts, bool negative)
        {
            var total = 0m;
            try
            {
                for (var part = Part.Match(parts); part.Success; part = part.NextMatch())
                    total += decimal.Parse(part.Groups["value"].Value, CultureInfo.InvariantCulture) * UnitMilliseconds[part.Groups["unit"].Value];
            }
            catch (OverflowException)
            {
                return null;
            }
            return negative ? -total : total;
        }
    }
}
