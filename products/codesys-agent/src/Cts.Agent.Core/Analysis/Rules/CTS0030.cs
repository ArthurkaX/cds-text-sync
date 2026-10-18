using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "FOR i := ... DO ... i := ...": the loop's counter written in its body.
    internal sealed class CTS0030 : Rule
    {
        internal CTS0030() : base("CTS0030", "Modifying a FOR loop control variable inside the loop", Analysis.Severity.Suspicious, "Correctness", "A FOR loop control variable is assigned from inside the loop body.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            foreach (var loop in ForLoop.Of(unit).Where(loop => loop.Counter != null))
            {
                var assignment = new Regex(@"(?<![.\w])" + Regex.Escape(loop.Counter) + @"\s*:=", RegexOptions.IgnoreCase);
                for (var match = assignment.Match(text, loop.BodyStart); match.Success && match.Index + match.Length <= loop.End; match = match.NextMatch())
                {
                    if (InsideCall(text, match.Index)) continue;
                    yield return Finding.In(unit, "FOR loop control variable '" + loop.Counter + "' is modified inside the loop", section.At(match.Index), section.At(match.Index + match.Length),
                        loop.Counter, loop.Counter + " :=");
                }
            }
        }

        // "F(i := 1)" names an argument: more '(' than ')' since the line or statement began.
        static bool InsideCall(string text, int offset)
        {
            var boundary = offset == 0 ? -1 : System.Math.Max(text.LastIndexOf(';', offset - 1), text.LastIndexOf('\n', offset - 1));
            var depth = 0;
            for (var i = boundary + 1; i < offset; i++)
                depth += text[i] == '(' ? 1 : text[i] == ')' ? -1 : 0;
            return depth > 0;
        }
    }
}
