using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "REPEAT ... UNTIL done END_REPEAT" where the body never assigns done.
    // A body with EXIT or RETURN has another way out and is left alone.
    internal sealed class CTS0046 : Rule
    {
        static readonly Regex Until = new Regex(@"\bUNTIL\b", RegexOptions.IgnoreCase);
        static readonly Regex EndRepeat = new Regex(@"\bEND_REPEAT\b", RegexOptions.IgnoreCase);
        static readonly Regex Identifier = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)(?![\w.])");
        static readonly Regex Terminal = new Regex(@"\b(?:EXIT|RETURN)\b", RegexOptions.IgnoreCase);
        static readonly Regex Call = new Regex(@"\G\s*\(");
        static readonly HashSet<string> Keywords = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "AND", "OR", "XOR", "NOT", "MOD", "TRUE", "FALSE" };

        internal CTS0046() : base("CTS0046", "REPEAT condition not changed", Analysis.Severity.Danger, "Correctness", "A REPEAT loop condition is not changed by its body.", "CALLABLE")
        {
            Requires = new[] { Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "REPEAT" && block.End.HasValue))
            {
                var start = block.Start - section.Base;
                var endRepeat = Last(EndRepeat, text, start, block.End.Value - section.Base);
                var until = endRepeat == null ? null : Last(Until, text, start, endRepeat.Index);
                if (until == null) continue;
                var conditionStart = until.Index + until.Length;
                var condition = text.Substring(conditionStart, endRepeat.Index - conditionStart);
                var names = Identifier.Matches(condition).Cast<Match>().Where(name => !Keywords.Contains(name.Value) && !Call.IsMatch(condition, name.Index + name.Length)).ToList();
                var loopBody = text.Substring(start, until.Index - start);
                if (names.Count == 0 || Terminal.IsMatch(loopBody)) continue;
                var assigned = new HashSet<string>(StBlocks.WholeAssignment.Matches(loopBody).Cast<Match>().Select(match => match.Groups["name"].Value), StringComparer.OrdinalIgnoreCase);
                var unchanged = names.Where(name => !assigned.Contains(name.Value)).ToList();
                if (unchanged.Count == 0) continue;
                var offset = section.At(conditionStart + unchanged[0].Index);
                yield return Finding.In(unit, "REPEAT UNTIL condition variable(s) " + Quoted(string.Join(", ", unchanged.Select(name => name.Value))) + " are not assigned in the loop body; the loop may not terminate",
                    offset, offset + unchanged[0].Length, unchanged[0].Value, condition.Trim());
            }
        }

        static Match Last(Regex regex, string text, int start, int end)
        {
            Match last = null;
            for (var match = regex.Match(text, start, end - start); match.Success; match = match.NextMatch()) last = match;
            return last;
        }
    }
}
