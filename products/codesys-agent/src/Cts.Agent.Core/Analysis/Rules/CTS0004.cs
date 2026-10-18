using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Repeated non-trivial numeric literals that should have a name.
    internal sealed class CTS0004 : Rule
    {
        static readonly Regex Number = new Regex(@"(?<![A-Za-z0-9_#])[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|(?:2|8|16)#[0-9A-Fa-f]+)(?![A-Za-z0-9_#])");

        internal CTS0004() : base("CTS0004", "Magic numeric literal", Analysis.Severity.Style, "Code quality", "Repeated non-trivial numeric literals should be named constants or parameters.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
            Merge = "identical";
            Options["min_occurrences"] = 2;
            Options["max_trivial_integer"] = 10;
            Options["merge"] = true;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            var maxTrivial = context.Option<int>("max_trivial_integer");
            var minimum = context.Option<int>("min_occurrences");
            var matches = Number.Matches(unit.Body.Text).Cast<Match>().Where(match => !Trivial(match.Value, maxTrivial) && !ArrayPosition(unit.Body.Text, match)).ToList();
            var counts = matches.GroupBy(match => Normalize(match.Value)).ToDictionary(group => group.Key, group => group.Count());
            foreach (var match in matches)
            {
                var value = Normalize(match.Value);
                if (counts[value] < minimum) continue;
                yield return Finding.In(unit, "repeated numeric literal " + match.Value + " could be a CONSTANT or input parameter",
                    unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length), value, match.Value);
            }
        }

        static bool Trivial(string value, int maximum)
        {
            var integer = IecTypes.Integer(value);
            if (integer.HasValue) return BigInteger.Abs(integer.Value) <= maximum;
            if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) return false;
            return number % 1 == 0 ? System.Math.Abs(number) <= maximum : System.Math.Abs(number) <= 1;
        }

        static bool ArrayPosition(string text, Match match)
        {
            var before = text.Substring(0, match.Index).TrimEnd();
            var after = text.Substring(match.Index + match.Length).TrimStart();
            return before.EndsWith("[", System.StringComparison.Ordinal) || (after.StartsWith("]", System.StringComparison.Ordinal) && Regex.IsMatch(after, @"^\]\s*\.\s*\d"));
        }

        // One key per value: 16#64, 100 and 100.0 are the same number.
        static string Normalize(string value)
        {
            var integer = IecTypes.Integer(value);
            if (integer.HasValue) return integer.Value.ToString(CultureInfo.InvariantCulture);
            value = value.ToUpperInvariant();
            if (!value.Contains("#") && double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number))
                return number % 1 == 0 ? number.ToString("0", CultureInfo.InvariantCulture) : number.ToString("G15", CultureInfo.InvariantCulture);
            return value.StartsWith("+", System.StringComparison.Ordinal) ? value.Substring(1) : value;
        }
    }
}
