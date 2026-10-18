using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // "x AND NOT x", "x OR TRUE": a condition with one result whatever x
    // is. An operand that a tighter operator takes ("a OR TRUE AND b" is
    // a OR (TRUE AND b)) is not one of the pair. A whole IF/ELSIF condition
    // over boolean variables is also put to every combination of them.
    internal sealed class CTS0081 : Rule
    {
        const string Operand = @"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)?";
        // Not from inside a name: a later letter of it cannot match where its start did not.
        static readonly Regex SameNegated = new Regex(@"(?<![A-Za-z_])(?<left>" + Operand + @")\s+(?<operator>AND|OR)\s+NOT\s+(?<right>" + Operand + @")", RegexOptions.IgnoreCase);
        static readonly Regex Constant = new Regex(@"(?<![A-Za-z_])(?<left>" + Operand + @"|TRUE|FALSE)\s+(?<operator>AND|OR)\s+(?<right>" + Operand + @"|TRUE|FALSE)", RegexOptions.IgnoreCase);
        // Operators that bind tighter than AND, and than OR, on either side of the pair.
        static readonly Regex TighterThanAndAfter = new Regex(@"\G\s*(?:[=<>+\-*/]|\^)");
        static readonly Regex TighterThanOrAfter = new Regex(@"\G\s*(?:[=<>+\-*/&]|\^|(?:AND|XOR)\b)", RegexOptions.IgnoreCase);

        internal CTS0081() : base("CTS0081", "Tautological or contradictory boolean expression", Analysis.Severity.Suspicious, "Correctness", "Boolean expressions that always evaluate to the same result should be simplified.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            var reported = new HashSet<int>();
            foreach (Match match in SameNegated.Matches(section.Text))
            {
                if (!Normalise(match.Groups["left"].Value).Equals(Normalise(match.Groups["right"].Value), StringComparison.Ordinal) || Bound(section.Text, match)) continue;
                var result = match.Groups["operator"].Value.Equals("OR", StringComparison.OrdinalIgnoreCase);
                reported.Add(match.Index);
                yield return Finding.In(unit, Message(match.Value, result), section.At(match.Index), section.At(match.Index + match.Length), match.Value, match.Value);
            }
            foreach (Match match in Constant.Matches(section.Text))
            {
                if (reported.Contains(match.Index) || Bound(section.Text, match)) continue;
                var result = ConstantResult(match.Groups["left"].Value, match.Groups["operator"].Value, match.Groups["right"].Value);
                if (!result.HasValue) continue;
                reported.Add(match.Index);
                yield return Finding.In(unit, Message(match.Value, result.Value), section.At(match.Index), section.At(match.Index + match.Length), match.Value, match.Value);
            }
            foreach (var branch in unit.Tree.Descendants().Where(block => block.Kind == "IF").SelectMany(block => block.Branches))
            {
                var condition = Guards.ConditionOf(branch.Label);
                if (condition == null) continue;
                var start = section.Text.IndexOf(condition, branch.Start - section.Base, StringComparison.Ordinal);
                if (start < 0 || reported.Any(index => start <= index && index < start + condition.Length) || !(BoolLogic.Constant(condition) is bool result)) continue;
                var shown = StText.Squeezed(condition);
                yield return Finding.In(unit, Message(shown, result), section.At(start), section.At(start + condition.Length), shown, shown);
            }
        }

        // Whether an operator binding tighter than the pair's own takes its left or right operand.
        static bool Bound(string text, Match match)
        {
            var or = match.Groups["operator"].Value.Equals("OR", StringComparison.OrdinalIgnoreCase);
            return (or ? TighterThanOrAfter : TighterThanAndAfter).IsMatch(text, match.Index + match.Length)
                || TighterBefore(text, match.Index, or);
        }

        // The token before *index*, past white space: = (not :=), < > + - * /,
        // and for OR also &, AND, XOR. Read backwards from the pair, not
        // over the whole text before it once per pair.
        static bool TighterBefore(string text, int index, bool or)
        {
            var end = index;
            while (end > 0 && char.IsWhiteSpace(text[end - 1])) end--;
            if (end == 0) return false;
            var last = text[end - 1];
            if ("<>+-*/".IndexOf(last) >= 0 || or && last == '&') return true;
            if (last == '=') return end < 2 || text[end - 2] != ':';
            if (!or || end < 3) return false;
            var word = text.Substring(end - 3, 3);
            return (word.Equals("AND", StringComparison.OrdinalIgnoreCase) || word.Equals("XOR", StringComparison.OrdinalIgnoreCase))
                && (end == 3 || !(char.IsLetterOrDigit(text[end - 4]) || text[end - 4] == '_'));
        }

        static string Normalise(string value) => StText.Unspaced(value).ToLowerInvariant();

        static string Message(string expression, bool result) => "boolean expression '" + expression + "' is always " + result.ToString().ToLowerInvariant();

        static bool? ConstantResult(string left, string operation, string right)
        {
            var leftValue = BooleanConstant(left);
            var rightValue = BooleanConstant(right);
            if (!leftValue.HasValue && !rightValue.HasValue) return null;
            if (operation.Equals("AND", StringComparison.OrdinalIgnoreCase))
            {
                if (leftValue == false || rightValue == false) return false;
                if (leftValue == true && rightValue.HasValue) return rightValue.Value;
                if (rightValue == true && leftValue.HasValue) return leftValue.Value;
            }
            if (operation.Equals("OR", StringComparison.OrdinalIgnoreCase))
            {
                if (leftValue == true || rightValue == true) return true;
                if (leftValue == false && rightValue.HasValue) return rightValue.Value;
                if (rightValue == false && leftValue.HasValue) return leftValue.Value;
            }
            return null;
        }

        static bool? BooleanConstant(string value)
        {
            if (value.Equals("TRUE", StringComparison.OrdinalIgnoreCase)) return true;
            if (value.Equals("FALSE", StringComparison.OrdinalIgnoreCase)) return false;
            return null;
        }
    }
}
