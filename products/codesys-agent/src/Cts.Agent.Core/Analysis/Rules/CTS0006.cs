using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Constant indexes that fall outside a declared one-dimensional array.
    internal sealed class CTS0006 : Rule
    {
        static readonly Regex Access = new Regex(@"\b([A-Za-z_]\w*)\s*\[\s*([+-]?(?:\d+|(?:2|8|16)#[0-9A-Fa-f]+))\s*\]");

        internal CTS0006() : base("CTS0006", "Array index outside bounds", Analysis.Severity.Danger, "Correctness", "Constant array indexes must stay within their declared bounds.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var arrays = new Dictionary<string, (string Name, int Lower, int Upper)>(System.StringComparer.OrdinalIgnoreCase);
            foreach (var member in unit.Members())
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind != "array" || shape.Dimensions.Count != 1) continue;
                if (!ConstantInt(shape.Dimensions[0].Key, out var lower) || !ConstantInt(shape.Dimensions[0].Value, out var upper)) continue;
                if (!arrays.ContainsKey(member.Name)) arrays[member.Name] = (member.Name, lower, upper);
            }
            if (arrays.Count == 0 || unit.Body.IsEmpty) yield break;
            foreach (Match match in Access.Matches(unit.Body.Text))
            {
                if (!arrays.TryGetValue(match.Groups[1].Value, out var info) || !ConstantInt(match.Groups[2].Value, out var index) || index >= info.Lower && index <= info.Upper) continue;
                var indexMatch = match.Groups[2];
                yield return Finding.In(unit, "array '" + info.Name + "' index " + indexMatch.Value + " is outside declared bounds [" + info.Lower + ".." + info.Upper + "]",
                    unit.Body.At(indexMatch.Index), unit.Body.At(indexMatch.Index + indexMatch.Length), info.Name + "[" + indexMatch.Value + "]", match.Value);
            }
        }

        static bool ConstantInt(string value, out int number)
        {
            value = value.Trim().ToUpperInvariant();
            var sign = value.StartsWith("-", System.StringComparison.Ordinal) ? -1 : 1;
            if (value.StartsWith("+", System.StringComparison.Ordinal) || value.StartsWith("-", System.StringComparison.Ordinal)) value = value.Substring(1);
            try
            {
                if (value.Contains("#"))
                {
                    var parts = value.Split('#');
                    number = sign * System.Convert.ToInt32(parts[1], int.Parse(parts[0]));
                    return true;
                }
                number = sign * int.Parse(value, System.Globalization.CultureInfo.InvariantCulture);
                return true;
            }
            catch (System.FormatException) { number = 0; return false; }
            catch (System.OverflowException) { number = 0; return false; }
        }
    }
}
