using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An exact '=' with a REAL or LREAL variable on either side: rounding
    // makes it a coin toss, a tolerance (ABS(a - b) < eps) does not.
    internal sealed class CTS0014 : Rule
    {
        static readonly Regex Equality = new Regex(@"(?<![<>=:])=(?!=)");
        static readonly Regex Identifier = new Regex(@"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*");
        static readonly HashSet<string> FloatTypes = new HashSet<string> { "REAL", "LREAL" };

        internal CTS0014() : base("CTS0014", "Floating-point equality", Analysis.Severity.Danger, "Correctness", "REAL and LREAL values should not be compared for exact equality.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            var reals = new HashSet<string>(unit.Members().Where(m => FloatTypes.Contains(m.Type.Trim().Trim('\'', '"').TrimEnd(';').ToUpperInvariant())).Select(m => m.Name.ToUpperInvariant()));
            var identifiers = Identifier.Matches(text).Cast<Match>().ToList();
            foreach (Match match in Equality.Matches(text))
            {
                var before = identifiers.LastOrDefault(id => id.Index + id.Length <= match.Index);
                var left = before == null ? null : Name(before.Value);
                var after = Identifier.Match(text, match.Index + match.Length);
                var right = after.Success && text.Substring(match.Index + match.Length, after.Index - match.Index - match.Length).Trim().Length == 0 ? Name(after.Value) : null;
                if (!reals.Contains(left ?? "") && !reals.Contains(right ?? "")) continue;
                yield return Finding.In(unit, "floating-point equality should use a tolerance comparison", section.At(match.Index), section.At(match.Index + match.Length),
                    "=", (left ?? "?") + " = " + (right ?? "?"));
            }
        }

        static string Name(string value) => value.Replace(" ", "").ToUpperInvariant();
    }
}
