using System.Collections.Generic;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // IF c THEN x := TRUE; ELSE x := FALSE; END_IF: one assignment, x := c.
    // Only a plain IF/ELSE with nothing nested inside or around it.
    internal sealed class CTS0010 : Rule
    {
        static readonly Regex Token = new Regex(@"\b(?<token>IF|ELSE|ELSIF|END_IF)\b", RegexOptions.IgnoreCase);
        static readonly Regex Then = new Regex(@"\bTHEN\b", RegexOptions.IgnoreCase);
        static readonly Regex Assignment = new Regex(@"^(?<target>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?)\s*:=\s*(?<value>TRUE|FALSE)\s*;$", RegexOptions.IgnoreCase | RegexOptions.Singleline);

        sealed class Open
        {
            internal int Start, IfEnd;
            internal Match Else;
            internal bool Elsif, Child, Nested;
        }

        internal CTS0010() : base("CTS0010", "Redundant boolean IF", Analysis.Severity.Suspicious, "Style", "Boolean IF/ELSE assignments that can be written as one expression.", "CALLABLE")
        {
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            var stack = new List<Open>();
            foreach (Match token in Token.Matches(text))
            {
                var word = token.Groups["token"].Value.ToUpperInvariant();
                if (word == "IF")
                {
                    stack.Add(new Open { Start = token.Index, IfEnd = token.Index + token.Length, Nested = stack.Count > 0 });
                    continue;
                }
                if (stack.Count == 0) continue;
                var current = stack[stack.Count - 1];
                if (word == "ELSE") current.Else = token;
                else if (word == "ELSIF") current.Elsif = true;
                else
                {
                    stack.RemoveAt(stack.Count - 1);
                    if (stack.Count > 0) stack[stack.Count - 1].Child = true;
                    if (current.Nested || current.Child || current.Else == null || current.Elsif) continue;
                    var then = Then.Match(text, current.IfEnd);
                    if (!then.Success || then.Index > current.Else.Index) continue;
                    var whenTrue = Assignment.Match(text.Substring(then.Index + then.Length, current.Else.Index - then.Index - then.Length).Trim());
                    var whenFalse = Assignment.Match(text.Substring(current.Else.Index + current.Else.Length, token.Index - current.Else.Index - current.Else.Length).Trim());
                    if (!whenTrue.Success || !whenFalse.Success) continue;
                    var target = whenTrue.Groups["target"].Value.Replace(" ", "");
                    var value = whenTrue.Groups["value"].Value.ToUpperInvariant();
                    if (target.ToLowerInvariant() != whenFalse.Groups["target"].Value.Replace(" ", "").ToLowerInvariant() || value == whenFalse.Groups["value"].Value.ToUpperInvariant()) continue;
                    var condition = StText.Squeezed(text.Substring(current.IfEnd, then.Index - current.IfEnd));
                    var expression = value == "TRUE" ? condition : "NOT (" + condition + ")";
                    var end = token.Index + token.Length;
                    yield return Finding.In(unit, "boolean IF/ELSE assignment to '" + target + "' can be simplified to '" + target + " := " + expression + ";'",
                        section.At(current.Start), section.At(end), target, text.Substring(current.Start, end - current.Start).Trim());
                }
            }
        }
    }
}
