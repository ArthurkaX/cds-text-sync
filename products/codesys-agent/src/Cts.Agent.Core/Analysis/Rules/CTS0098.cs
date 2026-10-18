using System.Collections.Generic;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // An expression mixing AND and OR in one group: AND binds first, which
    // the reader may not expect. Each expression is read whole, however its
    // lines are broken, and each parenthesis or argument is a group of its
    // own: (a AND b) OR c is grouped, a OR b AND c is not.
    internal sealed class CTS0098 : Rule
    {
        // What ends an expression: a ';', or a keyword around a condition or a statement.
        static readonly Regex Boundary = new Regex(@";|\b(?:IF|THEN|ELSIF|ELSE|END_\w+|CASE|OF|FOR|TO|BY|DO|WHILE|REPEAT|UNTIL|RETURN|EXIT)\b", RegexOptions.IgnoreCase);
        static readonly Regex Token = new Regex(@"[(),]|\b(?:AND|OR)\b", RegexOptions.IgnoreCase);

        internal CTS0098() : base("CTS0098", "Mixed AND and OR without parentheses", Analysis.Severity.Suspicious, "Correctness", "Mixed boolean operators should be explicitly grouped with parentheses.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            var boundaries = Boundary.Matches(section.Text);
            for (var i = 0; i <= boundaries.Count; i++)
            {
                var from = i == 0 ? 0 : boundaries[i - 1].Index + boundaries[i - 1].Length;
                var end = i < boundaries.Count ? boundaries[i].Index : section.Text.Length;
                if (!Mixed(section.Text.Substring(from, end - from))) continue;
                var raw = section.Raw.Substring(from, end - from);
                var offset = section.At(from + raw.Length - raw.TrimStart().Length);
                var expression = StText.Squeezed(StText.Blank(raw));
                yield return Finding.In(unit, "boolean expression '" + expression + "' mixes AND and OR without parentheses",
                    offset, offset + raw.Trim().Length, expression, expression);
            }
        }

        // Whether one group of the blanked expression holds both AND and OR.
        static bool Mixed(string expression)
        {
            var outer = new Stack<int>();
            var seen = 0;
            foreach (Match token in Token.Matches(expression))
            {
                var text = token.Value.ToUpperInvariant();
                if (text == "(") { outer.Push(seen); seen = 0; }
                else if (text == ")") seen = outer.Count > 0 ? outer.Pop() : 0;
                else if (text == ",") seen = 0;
                else seen |= text == "AND" ? 1 : 2;
                if (seen == 3) return true;
            }
            return false;
        }
    }
}
